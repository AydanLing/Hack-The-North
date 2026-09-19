"""Sentence encoders for the shape-intent classifier.

Two of them, and their concatenation:

* `TransformerEncoder` — a frozen sentence-transformer run through onnxruntime on the CPU. Frozen
  means inference only: no weights are ever updated, so there is nothing here that wants a GPU. The
  model is named by its Hugging Face repo id, so upgrading the encoder is a constant, not a rewrite.
* `TfidfEncoder` — pure numpy, word and character n-grams. It contributes the lexical half: a rare
  exact token like "hourglass" or "dumbbell" is a strong signal that a 384-dimensional semantic
  vector smooths away.
* `HybridEncoder` — both, each L2-normalised and scaled by 1/sqrt(2) before concatenation, so the
  cosine similarity of two utterances is the plain mean of a semantic and a lexical similarity.

The hybrid exists because the two halves fail differently. "show hackthenorth some love" has no token
in common with "heart" and is carried entirely by the transformer; "d9" versus "d6" is a lexical
distinction the transformer barely represents.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Optional, Sequence

import numpy as np

# Registry of encoders known to work here. `prefix` is prepended at encode time because the E5 and
# BGE families were trained with an instruction prefix and score materially worse without it.
MODELS: dict[str, dict] = {
    "minilm": {"repo": "sentence-transformers/all-MiniLM-L6-v2", "dim": 384, "prefix": ""},
    "bge-small": {"repo": "BAAI/bge-small-en-v1.5", "dim": 384, "prefix": ""},
    "bge-base": {"repo": "BAAI/bge-base-en-v1.5", "dim": 768, "prefix": ""},
    "e5-small": {"repo": "intfloat/e5-small-v2", "dim": 384, "prefix": "query: "},
    "e5-base": {"repo": "intfloat/e5-base-v2", "dim": 768, "prefix": "query: "},
    "gte-small": {"repo": "thenlper/gte-small", "dim": 384, "prefix": ""},
}
DEFAULT_MODEL = "minilm"
ONNX_CANDIDATES = ("onnx/model.onnx", "onnx/model_quantized.onnx", "model.onnx")

_TOKEN = re.compile(r"[a-z0-9']+")


def normalize(text: str) -> str:
    """Lower-case, keep letters/digits/apostrophes, collapse whitespace.

    Text-message input is already this shape most of the time; normalising makes "HEART!!" and
    "heart" the same row and keeps the TF-IDF vocabulary from splitting on punctuation.
    """
    return " ".join(_TOKEN.findall(str(text).lower()))


def l2(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)


# --------------------------------------------------------------------------------- transformer

class TransformerEncoder:
    """A frozen sentence-transformer via onnxruntime: mean-pooled over real tokens, L2-normalised."""

    kind = "transformer"

    def __init__(self, model: str = DEFAULT_MODEL, max_length: int = 64, batch_size: int = 128,
                 allow_download: bool = True, prefer_vendored: bool = True):
        spec = MODELS.get(model)
        if spec is None:
            raise ValueError(f"unknown encoder {model!r}; known: {', '.join(MODELS)}")
        self.model = model
        self.repo = spec["repo"]
        self.prefix = spec["prefix"]
        self.batch_size = batch_size

        import onnxruntime as ort
        from tokenizers import Tokenizer

        # Weights committed to the repo win over the Hugging Face cache, so a fresh clone needs no
        # network. `self.source` records which was used: the head must be fitted on the same bytes
        # that serve it, because int8 and float embeddings are not interchangeable.
        entry = _vendored(model) if prefer_vendored else None
        if entry:
            weights_path, tokenizer_path = entry["weights"], entry["tokenizer"]
            self.source = "vendored" + (":int8" if entry["manifest"].get("quantized") else ":fp32")
        else:
            weights_path = _onnx_weights(self.repo, allow_download)
            tokenizer_path = _hub_file(self.repo, "tokenizer.json", allow_download)
            self.source = "hub"
        # The source is part of the name so it lands in the saved head and in `doctor`, which is how
        # you notice a head fitted on float weights being served by int8 ones.
        self.name = f"transformer:{model}@{self.source}"

        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding()

        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            weights_path, options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        shape = self.session.get_outputs()[0].shape
        self.dim = int(shape[-1]) if isinstance(shape[-1], int) else int(spec["dim"])

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        prepared = [self.prefix + (t.strip() or ".") for t in texts]
        chunks = []
        for start in range(0, len(prepared), self.batch_size):
            batch = prepared[start:start + self.batch_size]
            encoded = self.tokenizer.encode_batch(batch)
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feeds["token_type_ids"] = np.array([e.type_ids for e in encoded], dtype=np.int64)
            hidden = self.session.run(None, feeds)[0]                     # (n, seq, dim)
            weights = mask[:, :, None].astype(np.float32)
            chunks.append((hidden * weights).sum(1) / np.maximum(weights.sum(1), 1e-9))
        return l2(np.concatenate(chunks, axis=0).astype(np.float64))

    def state(self) -> dict:
        return {"encoder_model": np.array(self.model)}


def _vendored(model: str):
    """Repo-local weights for `model`, or None. Imported lazily to keep the module cycle-free."""
    try:
        from .vendor import vendored
    except ImportError:
        return None
    return vendored(model)


def _hub_file(repo: str, filename: str, allow_download: bool = True) -> str:
    """Local Hugging Face cache first, so a warm machine never touches the network."""
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    cached = try_to_load_from_cache(repo, filename)
    if isinstance(cached, str) and os.path.exists(cached):
        return cached
    if not allow_download:
        raise FileNotFoundError(f"{repo}/{filename} is not cached and downloads are disabled")
    return hf_hub_download(repo, filename)


def _onnx_weights(repo: str, allow_download: bool = True) -> str:
    """Path to ONNX weights, preferring anything already cached over a download."""
    from huggingface_hub import try_to_load_from_cache

    for candidate in ONNX_CANDIDATES:
        cached = try_to_load_from_cache(repo, candidate)
        if isinstance(cached, str) and os.path.exists(cached):
            return cached
    errors = []
    for candidate in ONNX_CANDIDATES:
        try:
            return _hub_file(repo, candidate, allow_download)
        except Exception as e:
            errors.append(f"{candidate}: {type(e).__name__}")
    raise RuntimeError(f"no ONNX weights for {repo} (tried {', '.join(errors)})")


# --------------------------------------------------------------------------------- tf-idf

class TfidfEncoder:
    """Word and character n-grams with sublinear tf and L2 rows. Pure numpy, no download.

    Character n-grams are what make this robust to the typos a phone keyboard produces: "hart" and
    "heart" share four trigrams even though they share no word.

    `min_df=2` matters more than it looks. Char 3-5 grams over a few thousand short texts produce a
    very long tail — about 62% of the raw vocabulary occurs in exactly one row on this corpus. Those
    features cannot generalise (nothing else shares them) but they triple the matrix, so dropping
    them costs no accuracy and takes the dense design matrix from roughly a gigabyte to something
    that trains in seconds.
    """

    kind = "tfidf"
    name = "tfidf"

    def __init__(self, vocabulary: Optional[Sequence[str]] = None, idf: Optional[np.ndarray] = None,
                 word_ngrams: tuple[int, int] = (1, 2), char_ngrams: tuple[int, int] = (3, 5),
                 min_df: int = 2, max_features: int = 12000):
        self.word_ngrams = word_ngrams
        self.char_ngrams = char_ngrams
        self.min_df = min_df
        self.max_features = max_features
        self.vocabulary: list[str] = list(vocabulary or [])
        self.index: dict[str, int] = {t: i for i, t in enumerate(self.vocabulary)}
        self.idf = np.asarray(idf, dtype=np.float64) if idf is not None else np.zeros(0)
        self.dim = len(self.vocabulary)

    def features(self, text: str) -> Iterable[str]:
        """Every n-gram of one utterance. Word grams are prefixed `w:` and char grams `c:` so the two
        namespaces cannot collide."""
        clean = normalize(text)
        words = clean.split()
        for n in range(self.word_ngrams[0], self.word_ngrams[1] + 1):
            for i in range(len(words) - n + 1):
                yield "w:" + " ".join(words[i:i + n])
        padded = f" {clean} "
        for n in range(self.char_ngrams[0], self.char_ngrams[1] + 1):
            for i in range(len(padded) - n + 1):
                yield "c:" + padded[i:i + n]

    def fit(self, texts: Sequence[str]) -> "TfidfEncoder":
        counts: dict[str, int] = {}
        for text in texts:
            for token in set(self.features(text)):
                counts[token] = counts.get(token, 0) + 1
        kept = [t for t, c in counts.items() if c >= self.min_df]
        kept.sort(key=lambda t: (-counts[t], t))              # frequent first, ties broken by name
        kept = sorted(kept[:self.max_features])               # then sorted, so the order is stable
        n = max(1, len(texts))
        self.vocabulary = kept
        self.index = {t: i for i, t in enumerate(kept)}
        # smoothed idf, as in scikit-learn: log((1+n)/(1+df)) + 1, always positive
        self.idf = np.array([np.log((1.0 + n) / (1.0 + counts[t])) + 1.0 for t in kept])
        self.dim = len(kept)
        return self

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float64)
        if not self.dim:
            return out
        for row, text in enumerate(texts):
            counts: dict[int, int] = {}
            for token in self.features(text):
                j = self.index.get(token)
                if j is not None:
                    counts[j] = counts.get(j, 0) + 1
            for j, tf in counts.items():
                out[row, j] = (1.0 + np.log(tf)) * self.idf[j]     # sublinear tf
        return l2(out)

    def state(self) -> dict:
        return {"tfidf_vocabulary": np.array(self.vocabulary, dtype=str), "tfidf_idf": self.idf}

    @classmethod
    def from_state(cls, state: dict) -> "TfidfEncoder":
        return cls([str(t) for t in state["tfidf_vocabulary"]], state["tfidf_idf"])


# --------------------------------------------------------------------------------- hybrid

class HybridEncoder:
    """Transformer and TF-IDF concatenated, each L2-normalised and scaled by 1/sqrt(2)."""

    kind = "hybrid"

    def __init__(self, transformer: Optional[TransformerEncoder] = None,
                 tfidf: Optional[TfidfEncoder] = None, model: str = DEFAULT_MODEL):
        self.transformer = transformer or TransformerEncoder(model)
        self.tfidf = tfidf or TfidfEncoder()
        self.name = f"hybrid:{self.transformer.model}@{self.transformer.source}"

    @property
    def dim(self) -> int:
        return self.transformer.dim + self.tfidf.dim

    def fit(self, texts: Sequence[str]) -> "HybridEncoder":
        self.tfidf.fit(texts)
        return self

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        return np.hstack([self.transformer.encode(texts), self.tfidf.encode(texts)]) / np.sqrt(2.0)

    def state(self) -> dict:
        return {**self.transformer.state(), **self.tfidf.state()}


def build_encoder(kind: str = "hybrid", model: str = DEFAULT_MODEL, allow_download: bool = True):
    """`kind` is 'hybrid' (default), 'transformer' or 'tfidf'. TF-IDF alone needs no download and is
    the honest fallback on a machine with no cached weights and no network."""
    if kind == "tfidf":
        return TfidfEncoder()
    transformer = TransformerEncoder(model, allow_download=allow_download)
    if kind == "transformer":
        return transformer
    if kind == "hybrid":
        return HybridEncoder(transformer, TfidfEncoder())
    raise ValueError(f"unknown encoder kind {kind!r} (hybrid | transformer | tfidf)")


def restore_encoder(state: dict, allow_download: bool = True):
    """Rebuild the encoder a saved head was trained with, including its fitted TF-IDF vocabulary."""
    model = str(state["encoder_model"]) if "encoder_model" in state else ""
    has_tfidf = "tfidf_vocabulary" in state
    if not model:
        return TfidfEncoder.from_state(state)
    transformer = TransformerEncoder(model, allow_download=allow_download)
    if not has_tfidf:
        return transformer
    return HybridEncoder(transformer, TfidfEncoder.from_state(state))
