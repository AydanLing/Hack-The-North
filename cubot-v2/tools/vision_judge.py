"""Optional blind-naming judge for silhouettes, backed by the Claude API.

This lives under ``tools/`` on purpose: the ``cubot`` package must not import
an LLM SDK (``tests/test_integration_qa.py`` enforces it).  The discovery
stage receives ``judge_factory`` from here by injection.

The judge is an *annotation* on the discovery summary: it asks a vision
model what an unlabeled silhouette depicts and records whether the answer
matches the intended concept.  It never ranks, gates, or picks — the human
blind review remains the recognizability authority — and it is not a core
dependency: ``anthropic`` is an optional extra (``uv sync --extra judge``)
and every entry point degrades to a no-op without it.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

DEFAULT_MODEL = "claude-opus-5"
PROMPT_VERSION = 1
SYSTEM_PROMPT = (
    "You are judging whether low-resolution silhouettes are recognizable. "
    "Each image is a flat shape built from 27 identical square blocks laid on a table, "
    "shown as one dark silhouette. Answer honestly and briefly; do not guess a category "
    "you do not actually see."
)
USER_PROMPT = (
    "What does this silhouette depict? Reply with JSON only, no prose: "
    '{"label": "<one or two words>", "confidence": <0.0-1.0>, '
    '"alternatives": ["<word>", "<word>"]}. '
    'Use the label "unclear" if it does not clearly depict anything.'
)

_ARTICLES = {"a", "an", "the", "of", "letter", "number", "digit", "sign", "symbol", "shape", "icon"}


@dataclass(slots=True)
class Judgement:
    label: str
    confidence: float
    alternatives: list[str]
    matched: bool
    matched_alternative: bool
    raw: str
    model: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise(text: str) -> str:
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", text.casefold()).split() if w not in _ARTICLES]
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]
    return " ".join(words)


def label_matches(label: str, aliases: Sequence[str]) -> bool:
    wanted = {normalise(alias) for alias in aliases if normalise(alias)}
    got = normalise(label)
    if not got:
        return False
    if got in wanted:
        return True
    squashed = got.replace(" ", "")
    if any(alias.replace(" ", "") == squashed for alias in wanted):
        return True
    tokens = set(got.split())
    return any(alias in tokens or (" " in alias and alias in got) for alias in wanted)


def parse_reply(text: str) -> tuple[str, float, list[str]]:
    candidate = text.strip()
    match = re.search(r"\{.*\}", candidate, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            label = str(data.get("label", "unclear"))
            confidence = float(data.get("confidence", 0.0))
            alternatives = [str(a) for a in data.get("alternatives", []) if str(a).strip()]
            return label, max(0.0, min(1.0, confidence)), alternatives[:3]
        except (ValueError, TypeError, AttributeError):
            pass
    first_line = candidate.splitlines()[0] if candidate else "unclear"
    return first_line[:40], 0.0, []


def make_client(*, log: Callable[[str], None] = print) -> Any | None:
    """Return an Anthropic client, or ``None`` with a one-line reason."""

    try:
        import anthropic
    except ImportError:
        log("judge: skipped — the anthropic SDK is not installed (uv sync --extra judge)")
        return None
    try:
        return anthropic.Anthropic(max_retries=3)
    except Exception as error:  # noqa: BLE001 - credentials/env problems are non-fatal here
        log(f"judge: skipped — could not create a client ({error})")
        return None


def _cache_key(png: bytes, model: str) -> str:
    return hashlib.sha256(png + model.encode() + str(PROMPT_VERSION).encode()).hexdigest()


def _read_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            cache[row["key"]] = row
    return cache


def judge_silhouette(
    client: Any,
    png_path: Path,
    *,
    aliases: Sequence[str],
    model: str = DEFAULT_MODEL,
    cache_path: Path | None = None,
    log: Callable[[str], None] = print,
) -> Judgement | None:
    """Blind-name one PNG; cached by image bytes + model + prompt version."""

    png = Path(png_path).read_bytes()
    key = _cache_key(png, model)
    cache = _read_cache(cache_path)
    cached = cache.get(key)
    if cached is not None:
        raw = cached["raw"]
    else:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=256,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": base64.standard_b64encode(png).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": USER_PROMPT},
                        ],
                    }
                ],
            )
        except Exception as error:  # noqa: BLE001 - never let the judge break a run
            log(f"judge: {png_path.name}: request failed ({type(error).__name__}: {error})")
            return None
        raw = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text")
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"key": key, "model": model, "raw": raw}, sort_keys=True) + "\n")
    label, confidence, alternatives = parse_reply(raw)
    matched = label_matches(label, aliases)
    matched_alt = any(label_matches(alt, aliases) for alt in alternatives)
    return Judgement(label, confidence, alternatives, matched, matched_alt, raw, model)


__all__ = [
    "DEFAULT_MODEL",
    "judge_factory",
    "Judgement",
    "judge_silhouette",
    "label_matches",
    "make_client",
    "normalise",
    "parse_reply",
]


def judge_factory(
    *,
    model: str = DEFAULT_MODEL,
    cache_path: Path | None = None,
    log: Callable[[str], None] = print,
) -> Callable[[Path, Sequence[str]], dict[str, Any] | None] | None:
    """Build the ``judge(png, aliases)`` callable the discovery stage expects."""

    client = make_client(log=log)
    if client is None:
        return None

    def judge(png_path: Path, aliases: Sequence[str]) -> dict[str, Any] | None:
        result = judge_silhouette(client, png_path, aliases=aliases, model=model, cache_path=cache_path, log=log)
        return None if result is None else result.as_dict()

    return judge
