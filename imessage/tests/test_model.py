"""Tests for the intent model: encoder, head, corpus and captions.

None of these download anything. The transformer half of the encoder is exercised only by the
`--eval-only` training run, which is a manual step; everything here runs on TF-IDF, which is pure
numpy, so the suite stays fast and works offline.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubot_imessage.captions import caption_for, extract_who, pretty          # noqa: E402
from cubot_imessage.model.dataset import (Corpus, confusions, load_corpus,    # noqa: E402
                                          per_class_recall, stratified_split)
from cubot_imessage.model import vendor                                      # noqa: E402
from cubot_imessage.model.encoder import TfidfEncoder, normalize             # noqa: E402
from cubot_imessage.model.head import (NONE_LABEL, IntentHead,               # noqa: E402
                                        choose_thresholds, softmax)


# ------------------------------------------------------------------------------- encoder

def test_normalize_strips_punctuation_and_case():
    assert normalize("HEART!!  pls??") == "heart pls"
    assert normalize("it's a 7") == "it's a 7"


def test_tfidf_rows_are_l2_normalised():
    enc = TfidfEncoder().fit(["make a heart", "make an arrow", "fold into a square"])
    X = enc.encode(["make a heart", "totally unseen tokens"])
    assert X.shape[1] == enc.dim
    assert np.isclose(np.linalg.norm(X[0]), 1.0)
    assert np.linalg.norm(X[1]) in (0.0, pytest.approx(1.0))   # unseen text may be all-zero


def test_char_ngrams_survive_a_typo():
    """The lexical half exists so 'hart' still reaches 'heart'; word grams alone cannot do that.

    min_df=1 here because the production default of 2 would drop almost every feature of a
    four-document corpus — it is tuned for the real one, where 62% of char n-grams are hapax.
    """
    corpus = ["make a heart", "make an arrow", "fold a square", "do a triangle"]
    enc = TfidfEncoder(min_df=1).fit(corpus)
    X = enc.encode(corpus)
    typo = enc.encode(["mkae a hart"])[0]
    similarities = X @ typo
    assert int(np.argmax(similarities)) == 0, "typo should still be closest to the heart row"


def test_tfidf_state_round_trips():
    enc = TfidfEncoder().fit(["make a heart", "make an arrow"])
    restored = TfidfEncoder.from_state(enc.state())
    assert restored.vocabulary == enc.vocabulary
    assert np.allclose(restored.encode(["make a heart"]), enc.encode(["make a heart"]))


def test_unfitted_tfidf_returns_empty_rows_rather_than_raising():
    assert TfidfEncoder().encode(["anything"]).shape == (1, 0)


# ------------------------------------------------------------------------------- head

def _toy(n_per_class: int = 30):
    """Three well-separated clusters in 2-D, so the head's job is unambiguous."""
    rng = np.random.default_rng(0)
    centres = {"heart": [3.0, 0.0], "arrow": [0.0, 3.0], NONE_LABEL: [-3.0, -3.0]}
    X, y = [], []
    for label, centre in centres.items():
        X.append(rng.normal(centre, 0.25, size=(n_per_class, 2)))
        y += [label] * n_per_class
    return np.vstack(X), y


def test_softmax_rows_sum_to_one():
    P = softmax(np.array([[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]]))
    assert np.allclose(P.sum(axis=1), 1.0)
    assert np.allclose(P[1], 1 / 3)


def test_softmax_is_shift_invariant_and_overflow_safe():
    z = np.array([[1000.0, 1001.0, 999.0]])
    P = softmax(z)
    assert np.isfinite(P).all() and np.allclose(P.sum(), 1.0)


def test_head_learns_separable_classes():
    X, y = _toy()
    head = IntentHead.fit(X, y, epochs=300)
    decisions = head.decide(X)
    accuracy = np.mean([d.label == t for d, t in zip(decisions, y)])
    assert accuracy > 0.98


def test_head_rejects_the_out_of_scope_class_even_when_confident():
    X, y = _toy()
    head = IntentHead.fit(X, y, epochs=300)
    none_rows = np.array([[-3.0, -3.0]])
    decision = head.decide(none_rows)[0]
    assert decision.label == NONE_LABEL
    assert decision.accepted is False, "the none class must never be accepted as a shape"


def test_head_declines_an_ambiguous_point():
    X, y = _toy()
    head = IntentHead.fit(X, y, epochs=300)
    midpoint = head.decide(np.array([[1.5, 1.5]]))[0]      # equidistant from heart and arrow
    assert midpoint.margin < 0.5
    assert midpoint.accepted is False


def test_balanced_training_does_not_favour_the_larger_class():
    """A 10:1 imbalance must not make the majority class swallow the minority's territory."""
    rng = np.random.default_rng(1)
    X = np.vstack([rng.normal([3.0, 0.0], 0.3, size=(200, 2)),
                   rng.normal([0.0, 3.0], 0.3, size=(20, 2))])
    y = ["heart"] * 200 + ["arrow"] * 20
    head = IntentHead.fit(X, y, epochs=400, balanced=True)
    arrow_rows = head.decide(X[200:])
    assert np.mean([d.label == "arrow" for d in arrow_rows]) > 0.9


def test_scores_for_restricts_to_allowed_labels():
    X, y = _toy()
    head = IntentHead.fit(X, y, epochs=200)
    ranked = head.scores_for(np.array([[3.0, 0.0]]), ["arrow"])
    assert [label for label, _ in ranked] == ["arrow"]
    assert head.scores_for(np.array([[3.0, 0.0]]), ["nonexistent"]) == []


def test_head_round_trips_through_disk(tmp_path):
    X, y = _toy()
    head = IntentHead.fit(X, y, epochs=200, encoder_name="tfidf", corpus_hash="abc123",
                          encoder_state=TfidfEncoder().fit(["a b", "c d"]).state())
    path = str(tmp_path / "head.npz")
    head.save(path)
    loaded = IntentHead.load(path)
    assert loaded.classes == head.classes
    assert loaded.corpus_hash == "abc123"
    assert loaded.encoder_name == "tfidf"
    assert np.allclose(loaded.probabilities(X), head.probabilities(X))


def test_fit_rejects_a_label_outside_the_class_list():
    X, y = _toy()
    with pytest.raises(ValueError, match="absent from the class list"):
        IntentHead.fit(X, y, classes=["heart", "arrow"])


def test_choose_thresholds_hits_the_precision_target():
    X, y = _toy()
    head = IntentHead.fit(X, y, epochs=300)
    decisions = head.decide(X)
    margin, confidence, operating = choose_thresholds(decisions, y, target_precision=0.95)
    assert 0.0 <= margin <= 1.0 and 0.0 <= confidence <= 1.0
    assert operating["precision"] >= 0.95


# ------------------------------------------------------------------------------- corpus

def _write_corpus(tmp_path, rows):
    path = tmp_path / "utterances.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return str(path)


def test_load_corpus_drops_exact_duplicates(tmp_path):
    path = _write_corpus(tmp_path, [
        {"text": "make a heart", "label": "heart"},
        {"text": "Make a  HEART", "label": "heart"},        # same row after normalisation
        {"text": "make an arrow", "label": "arrow"},
    ])
    corpus = load_corpus(path)
    assert len(corpus) == 2


def test_load_corpus_keeps_the_same_text_under_different_labels(tmp_path):
    """Deduplication is per (label, text) — a genuine cross-label collision must survive to be
    caught by the corpus critic rather than silently dropped here."""
    path = _write_corpus(tmp_path, [{"text": "make an o", "label": "letter_o"},
                                    {"text": "make an o", "label": "ring"}])
    assert len(load_corpus(path)) == 2


def test_load_corpus_rejects_a_row_missing_a_field(tmp_path):
    path = _write_corpus(tmp_path, [{"text": "make a heart"}])
    with pytest.raises(ValueError, match="non-empty"):
        load_corpus(path)


def test_corpus_classes_put_none_last():
    corpus = Corpus(["a", "b", "c"], ["none", "arrow", "heart"])
    assert corpus.classes == ["arrow", "heart", "none"]


def test_corpus_hash_is_content_addressed():
    a = Corpus(["make a heart"], ["heart"])
    b = Corpus(["make a heart"], ["heart"])
    c = Corpus(["make a heart"], ["arrow"])
    assert a.hash() == b.hash() != c.hash()


def test_stratified_split_covers_every_class_on_both_sides():
    labels = ["heart"] * 20 + ["arrow"] * 10 + ["none"] * 15
    train, test = stratified_split(labels, test_fraction=0.2, seed=0)
    assert not set(train) & set(test)
    assert len(train) + len(test) == len(labels)
    for side in (train, test):
        assert {labels[i] for i in side} == {"heart", "arrow", "none"}


def test_stratified_split_is_deterministic_per_seed():
    labels = ["heart"] * 20 + ["arrow"] * 10
    assert np.array_equal(stratified_split(labels, seed=3)[0], stratified_split(labels, seed=3)[0])


def test_recall_and_confusions():
    truths = ["heart", "heart", "arrow", "arrow"]
    predictions = ["heart", "arrow", "arrow", "arrow"]
    assert per_class_recall(truths, predictions) == {"heart": 0.5, "arrow": 1.0}
    assert confusions(truths, predictions) == [("heart", "arrow", 1)]


# ------------------------------------------------------------------------------- captions

@pytest.mark.parametrize("text,expected", [
    ("show hack the north some love", "Hack the North"),
    ("show hackthenorth some love", "Hack the North"),
    ("show htn some love", "Hack the North"),
    ("make a heart for my team", "my team"),
    ("say hi to the judges", "the judges"),
    ("send love to Waterloo", "Waterloo"),
])
def test_extract_who_finds_the_addressee(text, expected):
    assert extract_who(text) == expected


@pytest.mark.parametrize("text", [
    "make a heart",
    "make a heart for a sec",           # a duration, not a name
    "do it for the lols",               # in the not-a-name list
    "show me some love",                # 'me' is not a name
    "make a heart for " + "x" * 60,     # too long to be a name
])
def test_extract_who_declines_non_names(text):
    assert extract_who(text) is None


def test_caption_names_the_addressee_when_there_is_one():
    assert caption_for("heart", "Hack the North") == "Showing Hack the North some love with a heart"
    assert caption_for("heart") == "Folding into a heart, with love"


def test_caption_falls_back_for_letters_digits_and_unknowns():
    assert caption_for("letter_h") == "Making the letter H"
    assert caption_for("digit_7", "the judges") == "The number 7 for the judges"
    assert caption_for("kraken") == "Making a kraken"


def test_pretty_names():
    assert pretty("letter_h") == "the letter H"
    assert pretty("digit_0") == "the number 0"
    assert pretty("square_wave") == "a square wave"
    assert pretty("anchor") == "an anchor"


# ------------------------------------------------------------------------------- vendored encoder

def test_vendored_returns_none_when_incomplete(tmp_path, monkeypatch):
    """A half-written encoder directory must read as absent, not as usable — otherwise a failed
    vendor run turns into a confusing onnxruntime error at demo time."""
    monkeypatch.setattr(vendor, "VENDOR_DIR", str(tmp_path))
    assert vendor.vendored("minilm") is None

    (tmp_path / "minilm").mkdir()
    (tmp_path / "minilm" / "model.onnx").write_bytes(b"not really onnx")
    assert vendor.vendored("minilm") is None            # tokenizer still missing

    (tmp_path / "minilm" / "tokenizer.json").write_text("{}")
    entry = vendor.vendored("minilm")
    assert entry is not None and entry["manifest"] == {}   # no manifest is tolerated


def test_vendored_reads_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(vendor, "VENDOR_DIR", str(tmp_path))
    base = tmp_path / "minilm"
    base.mkdir()
    (base / "model.onnx").write_bytes(b"x")
    (base / "tokenizer.json").write_text("{}")
    (base / "manifest.json").write_text(json.dumps({"quantized": True, "model": "minilm"}))
    assert vendor.vendored("minilm")["manifest"]["quantized"] is True


def test_the_real_vendored_encoder_is_int8_and_matches_its_manifest():
    """When weights are committed, their checksum must match what the manifest recorded. A silent
    mismatch means the head is being served by bytes it was not fitted on."""
    entry = vendor.vendored("minilm")
    if not entry or not entry["manifest"]:
        pytest.skip("no encoder vendored in this checkout")
    manifest = entry["manifest"]
    assert manifest["quantized"] is True
    assert vendor.sha256(entry["weights"]) == manifest["weights_sha256"]
    assert vendor.sha256(entry["tokenizer"]) == manifest["tokenizer_sha256"]
