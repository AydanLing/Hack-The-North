"""Loading and splitting the utterance corpus.

The corpus is JSONL, one `{"text": ..., "label": ...}` per line, at `imessage/data/utterances.jsonl`.
Labels are the classifier's own namespace (`letter_h`, `digit_0`, `square_wave`, `none`); mapping them
onto CuBot's shape directory names is `vocab.py`'s job, not this module's.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(PACKAGE_DIR), "data")
CORPUS_PATH = os.path.join(DATA_DIR, "utterances.jsonl")
HEAD_PATH = os.path.join(DATA_DIR, "intent_head.npz")


@dataclass
class Corpus:
    texts: list[str]
    labels: list[str]
    path: str = ""

    def __len__(self) -> int:
        return len(self.texts)

    @property
    def classes(self) -> list[str]:
        """Sorted, with `none` last so the out-of-scope class is visually distinct in reports."""
        seen = sorted(set(self.labels))
        return [c for c in seen if c != "none"] + (["none"] if "none" in seen else [])

    @property
    def counts(self) -> Counter:
        return Counter(self.labels)

    def hash(self) -> str:
        """Content hash, so a stale head can be detected without re-reading the corpus."""
        digest = hashlib.sha256()
        for text, label in zip(self.texts, self.labels):
            digest.update(f"{label}\x1f{text}\x1e".encode())
        return digest.hexdigest()[:16]

    def report(self) -> str:
        counts = self.counts
        thin = [f"{c} ({counts[c]})" for c in self.classes if counts[c] < 30]
        lines = [f"{len(self)} rows, {len(self.classes)} classes",
                 f"  rows per class: min {min(counts.values())}, "
                 f"median {int(np.median(list(counts.values())))}, max {max(counts.values())}"]
        if thin:
            lines.append(f"  thin classes (<30 rows): {', '.join(thin)}")
        return "\n".join(lines)


def load_corpus(path: str = CORPUS_PATH) -> Corpus:
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"no corpus at {path}. Build it with the authoring workflow, or point --corpus elsewhere.")
    texts, labels, seen = [], [], set()
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: {e}") from None
            text = str(row.get("text", "")).strip()
            label = str(row.get("label", "")).strip()
            if not text or not label:
                raise ValueError(f"{path}:{lineno}: row needs a non-empty 'text' and 'label'")
            key = (label, " ".join(text.lower().split()))
            if key in seen:                                   # exact duplicates add nothing but bias
                continue
            seen.add(key)
            texts.append(text)
            labels.append(label)
    if not texts:
        raise ValueError(f"{path} has no usable rows")
    return Corpus(texts, labels, path)


def stratified_split(labels: Sequence[str], test_fraction: float = 0.2,
                     seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Train/test indices holding class proportions, with at least one test row per class."""
    rng = np.random.default_rng(seed)
    labels = np.asarray(labels)
    train, test = [], []
    for c in np.unique(labels):
        idx = np.flatnonzero(labels == c)
        rng.shuffle(idx)
        n_test = max(1, int(round(len(idx) * test_fraction))) if len(idx) > 1 else 0
        test.extend(idx[:n_test].tolist())
        train.extend(idx[n_test:].tolist())
    return np.array(sorted(train)), np.array(sorted(test))


def per_class_recall(truths: Sequence[str], predictions: Sequence[str]) -> dict[str, float]:
    totals: Counter = Counter(truths)
    hits: Counter = Counter(t for t, p in zip(truths, predictions) if t == p)
    return {c: hits[c] / totals[c] for c in totals}


def confusions(truths: Sequence[str], predictions: Sequence[str],
               limit: int = 10) -> list[tuple[str, str, int]]:
    """The most frequent (truth, prediction) mistakes, worst first."""
    wrong: Counter = Counter((t, p) for t, p in zip(truths, predictions) if t != p)
    return [(t, p, n) for (t, p), n in wrong.most_common(limit)]
