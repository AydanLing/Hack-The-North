"""The semantic layer: an utterance in, a shape label out, using snake_pipeline's MiniLM head.

This module deliberately owns no model of its own. `snake_pipeline/snakeshape/local_model.py` already
holds the trained classifier — a hybrid encoder (all-MiniLM-L6-v2 through onnxruntime, concatenated
with a numpy TF-IDF) over class centroids plus a one-vs-rest linear head, fitted on
`snake_pipeline/data/utterances.jsonl` and cached in `data/intent_head.npz`. It is the thing that
already knows "show hack the north some love" means a heart, and it runs offline in ~20 ms.

We add three things on top of it:

* locating that checkout (it is not a package on PyPI and not vendored here),
* full per-class scores, so a request the robot cannot fold can still be answered with the nearest
  shape it *can* fold (`restricted_best`),
* a hard rule that the utterance is only ever data: the single value that escapes this module is a
  label from the head's own class list.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .config import Settings, find_snake_pipeline


class IntentUnavailable(RuntimeError):
    """snake_pipeline (or its cached head) could not be loaded."""


@dataclass
class IntentResult:
    """What the classifier made of one utterance, before the handoff vocabulary is consulted."""

    text: str
    label: str                      # e.g. "heart", "letter_H" — always one of the head's classes
    confidence: float
    margin: float
    accepted: bool                  # cleared the head's margin/confidence thresholds
    caption: str = ""               # snake_pipeline's template caption, with the greeted entity filled in
    who: Optional[str] = None       # "Hack the North" for "show hack the north some love"
    latency_ms: float = 0.0
    ranked: list[tuple[str, float]] = field(default_factory=list)   # top labels, best first

    @property
    def runner_up(self) -> Optional[str]:
        return self.ranked[1][0] if len(self.ranked) > 1 else None


class Classifier:
    """Lazy wrapper around `snakeshape.local_model.LocalInterpreter`.

    Construction is free; the model loads on the first `classify` (or an explicit `warmup`, which is
    what the server does at boot so the first text of the demo is not the one that pays for it).
    """

    def __init__(self, snake_pipeline_dir: Optional[str] = None, min_margin: Optional[float] = None,
                 min_confidence: Optional[float] = None, encoder: str = "auto"):
        self.dir = snake_pipeline_dir or find_snake_pipeline()
        self.min_margin = min_margin
        self.min_confidence = min_confidence
        self.encoder_kind = encoder
        self._lm = None                                    # the snakeshape.local_model module
        self._interp = None                                # LocalInterpreter
        self.load_seconds = 0.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "Classifier":
        return cls(settings.snake_pipeline_dir, settings.min_margin, settings.min_confidence)

    # -- setup -------------------------------------------------------------------------------
    def _ensure(self):
        if self._interp is not None:
            return self._interp
        if not self.dir:
            raise IntentUnavailable(
                "snake_pipeline not found. Set SNAKE_PIPELINE_DIR to the checkout holding "
                "snakeshape/local_model.py (the MiniLM intent head lives there)."
            )
        t0 = time.perf_counter()
        if self.dir not in sys.path:
            sys.path.insert(0, self.dir)
        try:
            from snakeshape import local_model as lm            # noqa: PLC0415  (deliberately lazy)
        except Exception as e:
            raise IntentUnavailable(f"cannot import snakeshape.local_model from {self.dir}: {e}") from None

        head_path = os.path.join(self.dir, "data", "intent_head.npz")
        if not os.path.exists(head_path):
            raise IntentUnavailable(
                f"no trained head at {head_path}. Run `python3 train_intent.py --no-llm` in "
                f"{self.dir} first — training at demo time takes minutes."
            )
        kw = {"auto_train": False, "encoder": self.encoder_kind,
              "dataset_path": os.path.join(self.dir, "data", "utterances.jsonl"),
              "head_path": head_path}
        if self.min_margin is not None:
            kw["margin_threshold"] = self.min_margin
        if self.min_confidence is not None:
            kw["min_confidence"] = self.min_confidence
        try:
            interp = lm.LocalInterpreter(**kw)
            interp._ensure_ready()
        except Exception as e:
            raise IntentUnavailable(f"cannot load the intent head at {head_path}: {e}") from None
        self._lm, self._interp = lm, interp
        self.load_seconds = time.perf_counter() - t0
        return interp

    def warmup(self) -> "Classifier":
        self._ensure()
        self.classify("warm up")
        return self

    # -- introspection -----------------------------------------------------------------------
    @property
    def labels(self) -> list[str]:
        """Every class the head can emit (139 at the time of writing)."""
        return list(self._ensure().head.classes)

    @property
    def encoder_name(self) -> str:
        return str(self._ensure().encoder.name)

    @property
    def thresholds(self) -> tuple[float, float]:
        interp = self._ensure()
        return float(interp.margin_threshold), float(interp.min_confidence)

    def extract_who(self, text: str) -> Optional[str]:
        """The greeted entity, via snake_pipeline's own patterns ('show hack the north some love' ->
        'Hack the North'). Returns None when nobody is addressed."""
        self._ensure()
        assert self._lm is not None
        who = self._lm.extract_who(text)
        return str(who)[:40] if who else None

    def caption_for(self, label: str, text: str = "") -> str:
        """snake_pipeline's template caption for a label, with the greeted entity from `text`."""
        self._ensure()
        assert self._lm is not None
        return str(self._lm.caption_for(label, self.extract_who(text) if text else None))

    # -- inference ---------------------------------------------------------------------------
    def _scores(self, text: str):
        interp = self._ensure()
        return interp.head.scores(interp.encoder.encode([text]))[0]

    def classify(self, text: str, top_k: int = 5) -> IntentResult:
        """Classify one utterance. Always returns a result; `accepted` says whether the head cleared
        its own margin and confidence thresholds (it does not for chitchat)."""
        interp = self._ensure()
        t0 = time.perf_counter()
        row = self._scores(text)
        classes = interp.head.classes
        order = sorted(range(len(classes)), key=lambda i: -row[i])
        top = order[0]
        confidence = float(row[top])
        margin = confidence - (float(row[order[1]]) if len(order) > 1 else 0.0)
        accepted = margin >= interp.margin_threshold and confidence >= interp.min_confidence
        label = str(classes[top])
        return IntentResult(
            text=text,
            label=label,
            confidence=confidence,
            margin=margin,
            accepted=accepted,
            caption=self.caption_for(label, text),
            who=self.extract_who(text),
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            ranked=[(str(classes[i]), float(row[i])) for i in order[:max(1, top_k)]],
        )

    def restricted_best(self, text: str, allowed: Sequence[str]) -> Optional[tuple[str, float]]:
        """Best-scoring label restricted to `allowed` — the nearest shape the robot can actually fold.
        Returns None when none of `allowed` is a class of the head."""
        interp = self._ensure()
        row = self._scores(text)
        index = {str(c): i for i, c in enumerate(interp.head.classes)}
        pairs = [(a, float(row[index[a]])) for a in allowed if a in index]
        if not pairs:
            return None
        return max(pairs, key=lambda p: p[1])
