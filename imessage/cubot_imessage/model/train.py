"""Train and evaluate the shape-intent head.

    python3 -m cubot_imessage.model.train                      # evaluate, then fit on everything
    python3 -m cubot_imessage.model.train --encoder tfidf      # no download, no network
    python3 -m cubot_imessage.model.train --model bge-small    # a different frozen encoder
    python3 -m cubot_imessage.model.train --eval-only          # report without writing the head

Held-out evaluation runs first, over several seeds, and prints the numbers that actually matter for a
live demo: accuracy among *accepted* predictions, what fraction of in-scope requests are accepted at
all, and whether the out-of-scope class catches chitchat. Thresholds are then chosen on held-out data
to hit a precision target rather than being guessed. Only after that is the head refitted on the full
corpus and written to `data/intent_head.npz`.

Everything here runs on the CPU. The encoder is frozen — no weights are updated, only the linear head
is fitted — so a GPU would have nothing to do.
"""
from __future__ import annotations

import argparse
import time
from typing import Optional

import numpy as np

from .dataset import (CORPUS_PATH, HEAD_PATH, confusions, load_corpus, per_class_recall,
                      stratified_split)
from .encoder import DEFAULT_MODEL, MODELS, build_encoder
from .head import NONE_LABEL, IntentHead, choose_thresholds


def evaluate(corpus, encoder_kind: str, model: str, seeds: tuple[int, ...], epochs: int,
             lr: float, l2: float, target_precision: float, log=print) -> dict:
    """Fit on each seed's training split, score the held-out split, and pick thresholds."""
    accuracies, accepted_accuracies, coverages = [], [], []
    last_truths: list[str] = []
    last_decisions = []

    for seed in seeds:
        train_idx, test_idx = stratified_split(corpus.labels, seed=seed)
        train_texts = [corpus.texts[i] for i in train_idx]
        train_labels = [corpus.labels[i] for i in train_idx]
        test_texts = [corpus.texts[i] for i in test_idx]
        test_labels = [corpus.labels[i] for i in test_idx]

        encoder = build_encoder(encoder_kind, model)
        if hasattr(encoder, "fit"):
            encoder.fit(train_texts)                       # TF-IDF must never see the test split
        head = IntentHead.fit(encoder.encode(train_texts), train_labels, classes=corpus.classes,
                              epochs=epochs, lr=lr, l2=l2, encoder_name=encoder.name)
        decisions = head.decide(encoder.encode(test_texts))

        predictions = [d.label for d in decisions]
        accuracy = float(np.mean([p == t for p, t in zip(predictions, test_labels)]))
        in_scope = [(d, t) for d, t in zip(decisions, test_labels) if t != NONE_LABEL]
        accepted = [(d, t) for d, t in in_scope if d.accepted]
        accuracies.append(accuracy)
        accepted_accuracies.append(
            float(np.mean([d.label == t for d, t in accepted])) if accepted else 0.0)
        coverages.append(len(accepted) / max(1, len(in_scope)))
        log(f"  seed {seed}: top-1 {accuracy:.3f}   accepted {accepted_accuracies[-1]:.3f} "
            f"at {coverages[-1]:.1%} coverage")
        last_truths, last_decisions = test_labels, decisions

    margin, confidence, operating = choose_thresholds(last_decisions, last_truths, target_precision)

    predictions = [d.label for d in last_decisions]
    recalls = per_class_recall(last_truths, predictions)
    worst = sorted(recalls.items(), key=lambda kv: kv[1])[:10]

    log("")
    log(f"top-1 accuracy      {np.mean(accuracies):.3f} +/- {np.std(accuracies):.3f} "
        f"over {len(seeds)} seeds")
    log(f"accepted accuracy   {np.mean(accepted_accuracies):.3f} "
        f"(coverage {np.mean(coverages):.1%})")

    none_rows = [(d, t) for d, t in zip(last_decisions, last_truths) if t == NONE_LABEL]
    if none_rows:
        caught = sum(1 for d, _ in none_rows if not d.accepted)
        log(f"out-of-scope        {caught}/{len(none_rows)} chitchat rows correctly declined "
            f"({caught / len(none_rows):.1%})")

    log(f"\nchosen thresholds   margin >= {margin}, confidence >= {confidence}")
    log(f"                    -> {operating.get('precision', 0):.1%} precision at "
        f"{operating.get('coverage', 0):.1%} coverage (target {target_precision:.0%})")

    log("\nweakest classes (held-out recall, last seed)")
    for label, recall in worst:
        log(f"  {label:16} {recall:.2f}")
    log("\nmost frequent confusions (truth -> predicted, count)")
    for truth, predicted, n in confusions(last_truths, predictions):
        log(f"  {truth:16} -> {predicted:16} {n}")

    return {"accuracy": float(np.mean(accuracies)), "accepted_accuracy": float(np.mean(accepted_accuracies)),
            "coverage": float(np.mean(coverages)), "margin": margin, "confidence": confidence}


def train(corpus_path: str = CORPUS_PATH, head_path: str = HEAD_PATH, encoder_kind: str = "hybrid",
          model: str = DEFAULT_MODEL, seeds: tuple[int, ...] = (0, 1, 2), epochs: int = 600,
          lr: float = 0.05, l2: float = 1e-4, target_precision: float = 0.97,
          eval_only: bool = False, log=print) -> Optional[str]:
    started = time.perf_counter()
    corpus = load_corpus(corpus_path)
    log(f"corpus {corpus_path}")
    log(corpus.report())
    log(f"\nencoder {encoder_kind}" + (f" ({model})" if encoder_kind != "tfidf" else ""))
    log("\nheld-out evaluation")
    result = evaluate(corpus, encoder_kind, model, seeds, epochs, lr, l2, target_precision, log)

    if eval_only:
        log(f"\n--eval-only: nothing written ({time.perf_counter() - started:.1f}s)")
        return None

    log("\nrefitting on the full corpus")
    encoder = build_encoder(encoder_kind, model)
    if hasattr(encoder, "fit"):
        encoder.fit(corpus.texts)
    head = IntentHead.fit(encoder.encode(corpus.texts), corpus.labels, classes=corpus.classes,
                          epochs=epochs, lr=lr, l2=l2, encoder_name=encoder.name,
                          corpus_hash=corpus.hash(), encoder_state=encoder.state())
    head.margin_threshold = result["margin"]
    head.confidence_threshold = result["confidence"]
    head.save(head_path)
    size_mb = __import__("os").path.getsize(head_path) / 1e6
    log(f"wrote {head_path} ({size_mb:.1f} MB) in {time.perf_counter() - started:.1f}s total")
    return head_path


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Train the CuBot shape-intent head (CPU only).")
    p.add_argument("--corpus", default=CORPUS_PATH)
    p.add_argument("--out", default=HEAD_PATH)
    p.add_argument("--encoder", default="hybrid", choices=("hybrid", "transformer", "tfidf"))
    p.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS),
                   help="which frozen sentence encoder to use")
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    p.add_argument("--epochs", type=int, default=600)
    p.add_argument("--lr", type=float, default=0.05)
    p.add_argument("--l2", type=float, default=1e-4)
    p.add_argument("--target-precision", type=float, default=0.97)
    p.add_argument("--eval-only", action="store_true")
    args = p.parse_args(argv)

    train(args.corpus, args.out, args.encoder, args.model, tuple(args.seeds), args.epochs,
          args.lr, args.l2, args.target_precision, args.eval_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
