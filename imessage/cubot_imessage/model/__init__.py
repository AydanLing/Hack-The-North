"""The shape-intent model: a frozen sentence encoder plus a linear head, trained in this repo.

Self-contained by design — the corpus, the encoder and the head all live here, so the bridge has no
dependency on any other checkout. Everything runs on the CPU; the encoder is inference-only.
"""
from .dataset import CORPUS_PATH, HEAD_PATH, Corpus, load_corpus, stratified_split
from .encoder import (DEFAULT_MODEL, MODELS, HybridEncoder, TfidfEncoder, TransformerEncoder,
                      build_encoder, restore_encoder)
from .head import NONE_LABEL, Decision, IntentHead, choose_thresholds

__all__ = [
    "CORPUS_PATH", "HEAD_PATH", "Corpus", "load_corpus", "stratified_split",
    "DEFAULT_MODEL", "MODELS", "HybridEncoder", "TfidfEncoder", "TransformerEncoder",
    "build_encoder", "restore_encoder", "NONE_LABEL", "Decision", "IntentHead", "choose_thresholds",
]
