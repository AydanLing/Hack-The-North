"""The semantic layer: an utterance in, a shape label out.

The model is this repo's own (`model/`): a frozen sentence encoder plus a linear head, trained on
`data/utterances.jsonl` and cached in `data/intent_head.npz`. Loading is lazy, inference is offline,
and nothing here needs a network or an API key once the encoder weights are in the Hugging Face
cache.

The utterance is data, not instruction. The only value that leaves this module is one label from the
head's own fixed class list — including `none`, the explicit out-of-scope class that lets the robot
decline chitchat instead of folding something at random.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .captions import caption, extract_who
from .config import Settings
from .model.dataset import CORPUS_PATH, HEAD_PATH, load_corpus
from .model.encoder import build_encoder, restore_encoder
from .model.head import NONE_LABEL, IntentHead


class IntentUnavailable(RuntimeError):
    """The trained head could not be loaded."""


@dataclass
class IntentResult:
    """What the classifier made of one utterance, before the handoff vocabulary is consulted."""

    text: str
    label: str
    confidence: float
    margin: float
    accepted: bool
    caption: str = ""
    who: Optional[str] = None
    latency_ms: float = 0.0
    ranked: list[tuple[str, float]] = field(default_factory=list)

    @property
    def runner_up(self) -> Optional[str]:
        return self.ranked[1][0] if len(self.ranked) > 1 else None

    @property
    def out_of_scope(self) -> bool:
        return self.label == NONE_LABEL


class Classifier:
    """Lazy wrapper around the trained head.

    Construction is free; the encoder and head load on the first `classify`, or on an explicit
    `warmup` — which the server calls at boot so the first text of the demo is not the one that pays
    for it.
    """

    def __init__(self, head_path: str = HEAD_PATH, corpus_path: str = CORPUS_PATH,
                 min_margin: Optional[float] = None, min_confidence: Optional[float] = None,
                 allow_download: bool = True):
        self.head_path = head_path
        self.corpus_path = corpus_path
        self.min_margin = min_margin
        self.min_confidence = min_confidence
        self.allow_download = allow_download
        self.head: Optional[IntentHead] = None
        self.encoder = None
        self.load_seconds = 0.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "Classifier":
        return cls(head_path=settings.head_path or HEAD_PATH,
                   min_margin=settings.min_margin, min_confidence=settings.min_confidence)

    # -- setup -------------------------------------------------------------------------------
    def _ensure(self) -> IntentHead:
        if self.head is not None:
            return self.head
        if not os.path.exists(self.head_path):
            raise IntentUnavailable(
                f"no trained head at {self.head_path}. Train one first:\n"
                f"    python3 -m cubot_imessage.model.train\n"
                f"It takes about a minute on CPU. Do not let it run during a demo."
            )
        started = time.perf_counter()
        try:
            head = IntentHead.load(self.head_path)
            encoder = restore_encoder(head.encoder_state, allow_download=self.allow_download)
        except Exception as e:
            raise IntentUnavailable(f"cannot load {self.head_path}: {type(e).__name__}: {e}") from None
        if self.min_margin is not None:
            head.margin_threshold = self.min_margin
        if self.min_confidence is not None:
            head.confidence_threshold = self.min_confidence
        self.head, self.encoder = head, encoder
        self.load_seconds = time.perf_counter() - started
        return head

    def warmup(self) -> "Classifier":
        self._ensure()
        self.classify("warm up")
        return self

    def is_stale(self) -> bool:
        """True when the corpus has changed since the head was fitted, so a retrain is due."""
        head = self._ensure()
        if not head.corpus_hash or not os.path.exists(self.corpus_path):
            return False
        try:
            return load_corpus(self.corpus_path).hash() != head.corpus_hash
        except (OSError, ValueError):
            return False

    # -- introspection -----------------------------------------------------------------------
    @property
    def labels(self) -> list[str]:
        return list(self._ensure().classes)

    @property
    def encoder_name(self) -> str:
        self._ensure()
        return str(getattr(self.encoder, "name", "unknown"))

    @property
    def thresholds(self) -> tuple[float, float]:
        head = self._ensure()
        return head.margin_threshold, head.confidence_threshold

    def extract_who(self, text: str) -> Optional[str]:
        return extract_who(text)

    def caption_for(self, label: str, text: str = "") -> str:
        return caption(label, text)

    # -- inference ---------------------------------------------------------------------------
    def classify(self, text: str, top_k: int = 5) -> IntentResult:
        """Classify one utterance. Always returns a result; `accepted` says whether the head cleared
        its thresholds and did not land on the out-of-scope class."""
        head = self._ensure()
        started = time.perf_counter()
        decision = head.decide(self.encoder.encode([text]), top_k=top_k)[0]
        return IntentResult(
            text=text,
            label=decision.label,
            confidence=decision.confidence,
            margin=decision.margin,
            accepted=decision.accepted,
            caption=caption(decision.label, text),
            who=extract_who(text),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            ranked=decision.ranked,
        )

    def restricted_best(self, text: str, allowed: Sequence[str]) -> Optional[tuple[str, float]]:
        """Best-scoring label restricted to `allowed` — the nearest shape the robot can actually
        fold. Returns None when none of `allowed` is a class of the head."""
        head = self._ensure()
        ranked = head.scores_for(self.encoder.encode([text]),
                                 [a for a in allowed if a != NONE_LABEL])
        return ranked[0] if ranked else None
