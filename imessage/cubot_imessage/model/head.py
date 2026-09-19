"""The classifier head: multinomial softmax over frozen sentence embeddings, fitted in numpy.

The encoder does the representation work and never changes. All that is learned here is a linear
decision rule on top of it — a `(classes, dim)` weight matrix and a bias. That is a convex problem
with a few thousand rows, which is why this trains on a CPU in seconds and why no part of this
project wants a GPU.

Three choices worth stating, because they differ from the obvious version:

* **Multinomial softmax, not one-vs-rest.** The classes are mutually exclusive — an utterance means
  one shape — so the probabilities should compete. One-vs-rest lets several classes each be
  confidently positive, which makes the top-two margin (the whole basis for declining) much less
  meaningful.
* **Class-balanced loss.** The corpus is not uniform: the demo shapes carry more rows than a rare
  letter. Weighting each class inversely to its frequency stops the head from quietly preferring
  whichever shape happened to get the most training data.
* **Adam, not plain gradient descent.** The feature scales are very uneven — dense transformer
  dimensions alongside sparse TF-IDF ones — and a single global learning rate serves them badly.
  Adam's per-parameter step sizes converge in a few hundred epochs where fixed-step descent needs
  thousands and still trails.

`decide()` returns a `Decision` and is the only entry point the bridge uses.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

NONE_LABEL = "none"          # the explicit out-of-scope class
DEFAULT_MARGIN = 0.15
DEFAULT_CONFIDENCE = 0.35


@dataclass
class Decision:
    """One classification, with everything the caller needs to accept or decline it."""

    label: str
    confidence: float          # probability of the winning class
    margin: float              # top-1 minus top-2 probability
    accepted: bool             # cleared the thresholds and is not the out-of-scope class
    ranked: list[tuple[str, float]]

    @property
    def runner_up(self) -> Optional[str]:
        return self.ranked[1][0] if len(self.ranked) > 1 else None


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)


class IntentHead:
    """Linear softmax classifier over fixed embeddings."""

    def __init__(self, classes: Sequence[str], W: np.ndarray, b: np.ndarray,
                 encoder_name: str = "", corpus_hash: str = "", encoder_state: Optional[dict] = None,
                 margin_threshold: float = DEFAULT_MARGIN,
                 confidence_threshold: float = DEFAULT_CONFIDENCE):
        self.classes = list(classes)
        self.W = np.asarray(W, dtype=np.float64)
        self.b = np.asarray(b, dtype=np.float64)
        self.encoder_name = encoder_name
        self.corpus_hash = corpus_hash
        self.encoder_state = encoder_state or {}
        self.margin_threshold = float(margin_threshold)
        self.confidence_threshold = float(confidence_threshold)

    # -- training ----------------------------------------------------------------------------
    @classmethod
    def fit(cls, X: np.ndarray, labels: Sequence[str], classes: Optional[Sequence[str]] = None,
            epochs: int = 600, lr: float = 0.05, l2: float = 1e-4, balanced: bool = True,
            encoder_name: str = "", corpus_hash: str = "", encoder_state: Optional[dict] = None,
            log=None) -> "IntentHead":
        X = np.asarray(X, dtype=np.float64)
        labels = np.asarray(labels)
        classes = list(classes) if classes is not None else sorted(set(labels.tolist()))
        index = {c: i for i, c in enumerate(classes)}
        missing = sorted(set(labels.tolist()) - set(classes))
        if missing:
            raise ValueError(f"labels absent from the class list: {', '.join(missing)}")

        n, d = X.shape
        k = len(classes)
        y = np.array([index[l] for l in labels])
        Y = np.zeros((n, k))
        Y[np.arange(n), y] = 1.0

        # per-row weight, so every class contributes equally regardless of how many rows it has
        if balanced:
            counts = np.maximum(Y.sum(0), 1.0)
            weights = (n / (k * counts))[y]
        else:
            weights = np.ones(n)
        weights = (weights / weights.sum())[:, None]

        W = np.zeros((k, d))
        b = np.zeros(k)
        mW, vW = np.zeros_like(W), np.zeros_like(W)
        mb, vb = np.zeros_like(b), np.zeros_like(b)
        beta1, beta2, eps = 0.9, 0.999, 1e-8

        for step in range(1, epochs + 1):
            P = softmax(X @ W.T + b)
            G = (P - Y) * weights                             # (n, k)
            gW = G.T @ X + l2 * W
            gb = G.sum(0)

            mW = beta1 * mW + (1 - beta1) * gW
            vW = beta2 * vW + (1 - beta2) * gW * gW
            mb = beta1 * mb + (1 - beta1) * gb
            vb = beta2 * vb + (1 - beta2) * gb * gb
            hW = mW / (1 - beta1 ** step)
            hV = vW / (1 - beta2 ** step)
            hb = mb / (1 - beta1 ** step)
            hvb = vb / (1 - beta2 ** step)

            W -= lr * hW / (np.sqrt(hV) + eps)
            b -= lr * hb / (np.sqrt(hvb) + eps)

            if log and (step % 100 == 0 or step == 1):
                loss = float(-(weights * Y * np.log(np.maximum(P, 1e-12))).sum())
                log(f"  epoch {step:5d}  loss {loss:.5f}")

        return cls(classes, W, b, encoder_name, corpus_hash, encoder_state)

    # -- inference ---------------------------------------------------------------------------
    def probabilities(self, X: np.ndarray) -> np.ndarray:
        return softmax(np.atleast_2d(np.asarray(X, dtype=np.float64)) @ self.W.T + self.b)

    def decide(self, X: np.ndarray, top_k: int = 5) -> list[Decision]:
        out: list[Decision] = []
        for row in self.probabilities(X):
            order = np.argsort(-row)
            label = self.classes[order[0]]
            confidence = float(row[order[0]])
            margin = confidence - (float(row[order[1]]) if len(order) > 1 else 0.0)
            out.append(Decision(
                label=label,
                confidence=confidence,
                margin=margin,
                accepted=(label != NONE_LABEL
                          and margin >= self.margin_threshold
                          and confidence >= self.confidence_threshold),
                ranked=[(self.classes[i], float(row[i])) for i in order[:max(1, top_k)]],
            ))
        return out

    def scores_for(self, X: np.ndarray, allowed: Sequence[str]) -> list[tuple[str, float]]:
        """(label, probability) restricted to `allowed`, best first. Used to offer the nearest shape
        the robot can actually fold when the requested one is unavailable."""
        row = self.probabilities(X)[0]
        index = {c: i for i, c in enumerate(self.classes)}
        pairs = [(a, float(row[index[a]])) for a in allowed if a in index]
        return sorted(pairs, key=lambda p: -p[1])

    # -- persistence -------------------------------------------------------------------------
    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        meta = json.dumps({
            "encoder_name": self.encoder_name,
            "corpus_hash": self.corpus_hash,
            "margin_threshold": self.margin_threshold,
            "confidence_threshold": self.confidence_threshold,
        })
        np.savez_compressed(path, classes=np.array(self.classes, dtype=str), W=self.W, b=self.b,
                            meta=np.array(meta), **self.encoder_state)
        return path

    @classmethod
    def load(cls, path: str) -> "IntentHead":
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            state = {k: z[k] for k in z.files
                     if k.startswith("tfidf_") or k == "encoder_model"}
            return cls(
                [str(c) for c in z["classes"]], z["W"], z["b"],
                encoder_name=meta.get("encoder_name", ""),
                corpus_hash=meta.get("corpus_hash", ""),
                encoder_state=state,
                margin_threshold=float(meta.get("margin_threshold", DEFAULT_MARGIN)),
                confidence_threshold=float(meta.get("confidence_threshold", DEFAULT_CONFIDENCE)),
            )


# --------------------------------------------------------------------------------- thresholds

def choose_thresholds(decisions: Sequence[Decision], truths: Sequence[str],
                      target_precision: float = 0.97) -> tuple[float, float, dict]:
    """Pick (margin, confidence) on held-out data to hit `target_precision` among accepted rows.

    The two error costs are not symmetric. A false accept folds the wrong shape in front of judges
    and takes half a minute to undo; a false reject only costs a fallback. So the operating point is
    chosen as the highest-coverage pair that still clears the precision target, rather than whatever
    maximises raw accuracy.
    """
    grid_m = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    grid_c = [0.20, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70]
    best = (DEFAULT_MARGIN, DEFAULT_CONFIDENCE, {"coverage": 0.0, "precision": 0.0})
    for m in grid_m:
        for c in grid_c:
            kept = [(d, t) for d, t in zip(decisions, truths)
                    if d.label != NONE_LABEL and d.margin >= m and d.confidence >= c]
            in_scope = [t for t in truths if t != NONE_LABEL]
            if not kept or not in_scope:
                continue
            precision = sum(1 for d, t in kept if d.label == t) / len(kept)
            coverage = len(kept) / len(in_scope)
            if precision >= target_precision and coverage > best[2]["coverage"]:
                best = (m, c, {"coverage": coverage, "precision": precision, "accepted": len(kept)})
    return best
