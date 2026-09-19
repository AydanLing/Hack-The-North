"""Vendor the frozen encoder into the repo, so the demo needs no network and no warm cache.

    python3 -m cubot_imessage.model.vendor              # fetch, quantize, write, verify
    python3 -m cubot_imessage.model.vendor --fp32       # skip quantization (86 MB, GitHub warns)
    python3 -m cubot_imessage.model.vendor --check      # report what is vendored, download nothing

Why this exists: the head in `data/intent_head.npz` is only half the model. The other half is the
frozen sentence encoder, which normally comes from the Hugging Face cache — which means a fresh clone
on conference wifi has to pull 86 MB before it can classify anything. `data/encoder/` removes that
dependency.

**The weights are quantized to int8, and that is not free.** Dynamic quantization changes the
embeddings slightly, so the head must be fitted on the same weights that will serve it or the decision
boundaries sit in the wrong place. `train.py` uses the vendored weights when they exist, so the normal
order is: vendor first, then train. `--check` reports drift against the float weights when both are
available.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from typing import Optional

from .dataset import DATA_DIR
from .encoder import DEFAULT_MODEL, MODELS, ONNX_CANDIDATES

VENDOR_DIR = os.path.join(DATA_DIR, "encoder")
MANIFEST_NAME = "manifest.json"
WEIGHTS_NAME = "model.onnx"
TOKENIZER_NAME = "tokenizer.json"


def vendor_dir(model: str = DEFAULT_MODEL) -> str:
    return os.path.join(VENDOR_DIR, model)


def vendored(model: str = DEFAULT_MODEL) -> Optional[dict]:
    """Paths and manifest for a vendored encoder, or None when it is absent or incomplete.

    Returns None rather than raising so `encoder.py` can treat "not vendored" as an ordinary fallback
    to the Hugging Face cache.
    """
    base = vendor_dir(model)
    weights = os.path.join(base, WEIGHTS_NAME)
    tokenizer = os.path.join(base, TOKENIZER_NAME)
    if not (os.path.isfile(weights) and os.path.isfile(tokenizer)):
        return None
    manifest = {}
    try:
        with open(os.path.join(base, MANIFEST_NAME), encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        pass
    return {"dir": base, "weights": weights, "tokenizer": tokenizer, "manifest": manifest}


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mb(path: str) -> float:
    return os.path.getsize(path) / 1e6


def vendor(model: str = DEFAULT_MODEL, quantize: bool = True, log=print) -> str:
    """Download the encoder, optionally quantize it, and write it under `data/encoder/<model>/`."""
    from .encoder import _hub_file, _onnx_weights          # deferred: these import huggingface_hub

    spec = MODELS.get(model)
    if spec is None:
        raise ValueError(f"unknown encoder {model!r}; known: {', '.join(sorted(MODELS))}")
    repo = spec["repo"]
    base = vendor_dir(model)
    os.makedirs(base, exist_ok=True)

    log(f"source     {repo}")
    source_weights = _onnx_weights(repo, allow_download=True)
    source_tokenizer = _hub_file(repo, TOKENIZER_NAME, allow_download=True)
    log(f"fetched    {os.path.basename(source_weights)} ({_mb(source_weights):.1f} MB)")

    target_weights = os.path.join(base, WEIGHTS_NAME)
    if quantize:
        import tempfile

        from onnxruntime.quantization import QuantType, quantize_dynamic

        log("quantizing to int8 (dynamic) ...")
        # quantize_dynamic writes a `<name>-inferred.onnx` scratch file next to its *input*, and the
        # input here is the Hugging Face cache. Stage a copy somewhere writable instead of littering
        # (or failing on) a read-only cache.
        with tempfile.TemporaryDirectory(prefix="cubot-quantize-") as staging:
            staged = os.path.join(staging, WEIGHTS_NAME)
            shutil.copyfile(source_weights, staged)
            quantize_dynamic(staged, target_weights, weight_type=QuantType.QInt8)
        log(f"quantized  {_mb(source_weights):.1f} MB -> {_mb(target_weights):.1f} MB")
    else:
        shutil.copyfile(source_weights, target_weights)

    shutil.copyfile(source_tokenizer, os.path.join(base, TOKENIZER_NAME))

    manifest = {
        "model": model,
        "repo": repo,
        "source_file": next((c for c in ONNX_CANDIDATES if source_weights.endswith(c)),
                            os.path.basename(source_weights)),
        "quantized": bool(quantize),
        "quantization": "dynamic int8 (weights only)" if quantize else "none, float32",
        "weights_sha256": sha256(target_weights),
        "weights_mb": round(_mb(target_weights), 2),
        "tokenizer_sha256": sha256(os.path.join(base, TOKENIZER_NAME)),
        "note": ("Fit the head on these weights, not the float ones: quantization shifts the "
                 "embeddings and the head is a linear rule over them."),
    }
    with open(os.path.join(base, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    log(f"wrote      {base}")
    return base


def drift(model: str = DEFAULT_MODEL, log=print) -> Optional[float]:
    """Mean cosine similarity between vendored and float embeddings over the corpus.

    The number that matters when deciding whether int8 is acceptable. Returns None when the float
    weights are not available to compare against.
    """
    import numpy as np

    from .dataset import load_corpus
    from .encoder import TransformerEncoder

    entry = vendored(model)
    if not entry:
        log("nothing vendored to compare")
        return None
    try:
        reference = TransformerEncoder(model, allow_download=False, prefer_vendored=False)
    except Exception as e:
        log(f"no float weights cached to compare against ({type(e).__name__})")
        return None

    texts = load_corpus().texts
    quantized = TransformerEncoder(model, prefer_vendored=True)
    a, b = quantized.encode(texts), reference.encode(texts)
    cosine = float(np.mean(np.sum(a * b, axis=1)))
    log(f"embedding drift  mean cosine {cosine:.5f} over {len(texts)} utterances "
        f"(1.0 would be identical)")
    return cosine


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Vendor the frozen sentence encoder into this repo.")
    p.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    p.add_argument("--fp32", action="store_true", help="do not quantize (86 MB for minilm)")
    p.add_argument("--check", action="store_true", help="report what is vendored; download nothing")
    p.add_argument("--drift", action="store_true", help="measure int8 drift against float weights")
    args = p.parse_args(argv)

    if args.check or args.drift:
        entry = vendored(args.model)
        if not entry:
            print(f"{args.model}: not vendored ({vendor_dir(args.model)} is absent or incomplete)")
            return 1
        print(f"{args.model}: vendored at {entry['dir']}")
        for key, value in sorted(entry["manifest"].items()):
            print(f"  {key:18} {value}")
        if args.drift:
            drift(args.model)
        return 0

    vendor(args.model, quantize=not args.fp32)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
