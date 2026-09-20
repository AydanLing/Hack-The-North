"""OpenAI fallback when MiniLM cannot map an utterance to a playable shape.

MiniLM stays the fast path (~1 ms). This module is only called on decline / out-of-scope.
When the text clearly names something foldable, return that label. When it does not,
return ``label="none"`` with a clarifying caption — never invent a random booth shape.
Stdlib only: urllib + json.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Sequence

DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# Explicit letter requests only — "make a C", "letter J", "the letter a".
# Article "a"/"an" is REQUIRED before a single-letter token so "make a carrot"
# does not look like a request for the letter A.
_LETTER_ASK = re.compile(
    r"(?i)(?:"
    r"\b(?:letter|glyph|character)\s+([a-z])\b|"
    r"\b([a-z])\s+(?:letter|glyph)\b|"
    r"\b(?:make|fold|do|show|draw)\s+(?:an?|the)\s+([a-z])\b|"
    r"\bjust\s+([a-z])\b|"
    r"^\s*([a-z])\s*[!?.]*\s*$"
    r")"
)

SYSTEM_PROMPT = """\
You help CuBot, a 27-cube folding robot at Hack the North. Someone just texted an iMessage.

Your job: either (A) pick exactly ONE label from allowed_labels that CuBot should fold, OR
(B) admit you do not know and ask them to name a shape — NEVER invent a random shape.

How to think:
1. Is this a clear request for something that has a simple cut-paper silhouette?
2. If YES: ignore spelling quirks, map to the closest allowed_labels member, caption with
   "Folding …" naming the everyday subject.
3. If NO (chitchat, gibberish, absurd long coined words, vague flex, "hey what's up",
   dictionary jokes, keyboard smash, or anything you cannot honestly silhouette):
   return label "none". Do NOT pick plus, heart, smiley, triangle, or any filler glyph.
   Caption must ask them again, e.g.:
     "Not sure what to fold — try a shape name like checkmark, heart, or C?"
     "I don't know that one. Name a shape?"

Special cases that ARE clear (do fold):
- "straight line" / "home" / "unfold" / "zero" → the chain already handles these elsewhere;
  if you see them here, still prefer label "none" with caption suggesting "straight line"
  only if somehow reached — otherwise fold nothing.
- Explicit letter asks ("make a C", "letter J", bare "C") → letter_* / single letter.
- Person / pet names with no better icon → first letter is OK.
- Food / objects / animals with a silhouette family → map to family (carrot→triangle, etc.).

Silhouette families (for real subjects):
- tapered / wedge / pointed tip → triangle
- round with a hole → ring or donut
- round face / blob → smiley
- drink vessel → mug / bottle / wine_glass
- heart / love → heart
- check / approval → checkmark
- bolt / zig → lightning or square_wave
- stairs → staircase or stairs
- rocket → rocket
- boat → boat
- boxy frame → square or cube_frame

Never answer a common noun with its first letter. Never first-letter gibberish.

Rules:
- JSON only:
  {"label": "<id or none>", "silhouette": "<3-6 words or empty>",
   "meaning": "<subject or empty>", "caption": "<one short sentence>",
   "confidence": 0.0-1.0}
- If folding: label MUST be in allowed_labels. Caption starts with "Folding …".
- If unsure: label MUST be exactly "none". Caption asks them to name a shape. confidence low.
- One short sentence. No emojis. No code, URLs, or phone numbers.
"""


@dataclass
class OpenAIGuess:
    label: str
    caption: str
    confidence: float
    raw: str = ""
    latency_ms: float = 0.0
    via: str = "openai"  # "openai" | "letter_fallback" | "clarify"


def _norm_label(label: str) -> str:
    return str(label or "").strip().lower().replace("-", "_")


_META_SUBJECT = re.compile(
    r"(?i)\b(?:"
    r"long\s+(?:medical\s+)?(?:term|word|name)|"
    r"medical\s+term|disease(?:\s+name)?|diagnosis|"
    r"gibberish|nonsense|gobbledygook|keyboard\s*smash|"
    r"random\s+(?:word|string|text)|tongue[\s-]?twister|"
    r"dictionary\s+(?:word|flex)|made[\s-]?up\s+word|"
    r"unpronounceable|sesquipedalian"
    r")\b"
)

_CLARIFY_CAPTION = (
    "Not sure what to fold — try a shape name like checkmark, heart, C, or headphones?"
)


def _is_letter_label(label: str) -> bool:
    lab = _norm_label(label)
    if lab.startswith("letter_") and len(lab) == 8:
        return True
    return len(lab) == 1 and lab.isalpha()


_NAME_CUE = re.compile(
    r"(?i)\b(?:i(?:'m| am)|my name(?:'s| is)|call me|named|for)\s+([A-Za-z]{2,})\b"
)
_NOT_A_NAME = {
    "carrot", "carrots", "cheese", "pizza", "apple", "coffee", "love", "heart", "dog", "cat",
    "rabbit", "boat", "rocket", "tree", "phone", "home", "house", "triangle", "square",
    "circle", "donut", "mug", "blank", "something", "please", "thanks", "hello", "hack",
    "north", "cubot", "robot", "shape", "letter", "make", "fold", "show", "want", "like",
}


def name_initial_ok(text: str, letter_label: str) -> bool:
    """True when a letter label matches the initial of a probable person/pet name in the text."""
    lab = _norm_label(letter_label)
    ch = lab[-1] if lab.startswith("letter_") else (lab if len(lab) == 1 else "")
    if not ch:
        return False
    m = _NAME_CUE.search(text or "")
    if m:
        word = m.group(1)
        if word.lower() not in _NOT_A_NAME and word[0].lower() == ch:
            return True
    words = re.findall(r"[A-Za-z]{2,}", text or "")
    for i, w in enumerate(words):
        if w.lower() in _NOT_A_NAME:
            continue
        if i == 0 and len(words) > 1 and w.lower() in {"make", "fold", "show", "do", "can", "please"}:
            continue
        if w[0].lower() == ch:
            return True
    return False


def wants_explicit_letter(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_LETTER_ASK.search(t))


def _requested_letter(text: str) -> Optional[str]:
    m = _LETTER_ASK.search((text or "").strip())
    if not m:
        return None
    for g in m.groups():
        if g and len(g) == 1 and g.isalpha():
            return g.lower()
    return None


def _pick_allowed(candidate: str, labels: set[str]) -> Optional[str]:
    c = _norm_label(candidate)
    if not c:
        return None
    by_norm = {_norm_label(x): x for x in labels}
    variants = [c, c.replace("_", "-")]
    if len(c) == 1 and c.isalpha():
        variants.append(f"letter_{c}")
    if c.startswith("letter_") and len(c) == 8:
        variants.append(c[-1])
    for v in variants:
        if v in by_norm:
            return by_norm[v]
        if _norm_label(v) in by_norm:
            return by_norm[_norm_label(v)]
    return None


def clarify_guess(caption: str = "", latency_ms: float = 0.0) -> OpenAIGuess:
    return OpenAIGuess(
        label="none",
        caption=(caption or _CLARIFY_CAPTION).strip()[:160] or _CLARIFY_CAPTION,
        confidence=0.1,
        latency_ms=latency_ms,
        via="clarify",
    )


def first_letter_fallback(text: str, allowed_labels: Sequence[str]) -> Optional[OpenAIGuess]:
    """Only fires for an explicit letter ask. Otherwise returns None (caller should clarify)."""
    labels = {str(x) for x in allowed_labels if x and x != "none"}
    if not labels:
        return None

    asked = _requested_letter(text)
    if asked:
        label = _pick_allowed(f"letter_{asked}", labels) or _pick_allowed(asked, labels)
        if label:
            return OpenAIGuess(
                label=label,
                caption=f"Folding the letter {asked.upper()}",
                confidence=0.7,
                via="letter_fallback",
            )
    return None


class OpenAIFallback:
    """Second opinion: fold a clear shape, or ask again — never a random glyph."""

    def __init__(self, api_key: str = "", model: str = DEFAULT_MODEL,
                 timeout_s: float = 12.0, log=print):
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        self.model = model or DEFAULT_MODEL
        self.timeout_s = timeout_s
        self.log = log

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def resolve(self, text: str, allowed_labels: Sequence[str]) -> Optional[OpenAIGuess]:
        """Return a playable guess, a clarify (label=none), or None if nothing useful."""
        labels = sorted({str(x) for x in allowed_labels if x and x != "none"})
        if not labels:
            return None
        label_set = set(labels)

        guess: Optional[OpenAIGuess] = None
        if self.enabled:
            guess = self._ask_openai(text, labels)

        def _usable(g: Optional[OpenAIGuess]) -> bool:
            if g is None or g.label == "none":
                return False
            if g.label not in label_set:
                return False
            if _is_letter_label(g.label):
                return wants_explicit_letter(text) or name_initial_ok(text, g.label)
            return True

        if guess is not None and guess.label == "none":
            if not (guess.caption or "").strip():
                guess.caption = _CLARIFY_CAPTION
            guess.via = "clarify"
            return guess

        if _usable(guess):
            assert guess is not None
            if not guess.caption:
                guess.caption = f"Folding into {guess.label.replace('_', ' ')}"
            return guess

        if guess is not None and _is_letter_label(guess.label):
            self.log(f"[openai] rejected lazy letter {guess.label!r} for {text!r}")
        elif guess is not None and guess.label not in label_set:
            self.log(f"[openai] label {guess.label!r} not playable")

        # Explicit letter ask only — otherwise ask the human again.
        fb = first_letter_fallback(text, labels)
        if fb is not None:
            self.log(f"[openai] {fb.via} -> {fb.label}")
            return fb
        return clarify_guess(latency_ms=getattr(guess, "latency_ms", 0.0) if guess else 0.0)

    def _ask_openai(self, text: str, labels: list[str]) -> Optional[OpenAIGuess]:
        payload = {
            "model": self.model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({
                    "text": text,
                    "allowed_labels": labels,
                })},
            ],
        }
        import time
        t0 = time.perf_counter()
        try:
            body = self._post(payload)
        except Exception as e:
            self.log(f"[openai] call failed: {e}")
            return None
        elapsed = (time.perf_counter() - t0) * 1000.0
        content = ""
        try:
            content = body["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            self.log(f"[openai] bad response: {e}; raw={content!r:.200}")
            return None

        label = str(data.get("label") or "").strip()
        lowered = _norm_label(label)
        if lowered == "none" or label.lower() == "none":
            caption = str(data.get("caption") or "").strip()[:160]
            if not caption or re.search(r"(?i)\bfolding\b", caption):
                caption = _CLARIFY_CAPTION
            try:
                conf = float(data.get("confidence", 0.2))
            except (TypeError, ValueError):
                conf = 0.2
            return OpenAIGuess(label="none", caption=caption, confidence=max(0.0, min(1.0, conf)),
                               raw=content, latency_ms=elapsed, via="clarify")

        if lowered in labels:
            label = lowered
        elif label not in labels:
            alt = _pick_allowed(label, set(labels))
            label = alt or "none"

        meaning = str(data.get("meaning") or "").strip()[:60]
        caption = str(data.get("caption") or "").strip()[:160]

        # Meta / "long medical term" style → clarify, do not fold junk.
        if label != "none" and (
            _META_SUBJECT.search(meaning) or _META_SUBJECT.search(caption)
            or re.search(r"(?i)\bfolding\s+[a-z]{24,}\b", caption)
            or re.search(r"(?i)\bno clue what that is\b", caption)
        ):
            return OpenAIGuess(label="none", caption=_CLARIFY_CAPTION, confidence=0.15,
                               raw=content, latency_ms=elapsed, via="clarify")

        if label == "none":
            return OpenAIGuess(label="none", caption=caption or _CLARIFY_CAPTION, confidence=0.15,
                               raw=content, latency_ms=elapsed, via="clarify")

        if meaning and not re.search(r"(?i)\bfold(?:ing)?\b", caption):
            caption = f"Folding {meaning}" + (f" — {caption}" if caption else "")
        elif meaning and re.search(r"(?i)\bfolding (?:a |an |the )?(tree|shape)\b", caption):
            caption = re.sub(
                r"(?i)^Folding (?:a |an |the )?(?:tree|shape)\b[^.]*",
                f"Folding {meaning}",
                caption,
                count=1,
            )
        elif not caption and meaning:
            caption = f"Folding {meaning}"

        try:
            conf = float(data.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        conf = max(0.0, min(1.0, conf))
        return OpenAIGuess(label=label, caption=caption, confidence=conf,
                           raw=content, latency_ms=elapsed, via="openai")

    def _post(self, payload: dict) -> dict:
        raw = json.dumps(payload).encode()
        req = urllib.request.Request(OPENAI_URL, data=raw, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"OpenAI {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"OpenAI unreachable: {e.reason}") from None
        return json.loads(text) if text.strip() else {}
