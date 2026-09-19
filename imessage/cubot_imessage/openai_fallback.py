"""OpenAI fallback when MiniLM cannot map an utterance to a playable shape.

MiniLM stays the fast path (~1 ms). This module is only called on decline / out-of-scope.
It must ALWAYS return a label from the fixed playable set — never ``none``, never blank.
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

_WORD = re.compile(r"[a-zA-Z]")

SYSTEM_PROMPT = """\
You help CuBot, a 27-cube folding robot at Hack the North. Someone just texted an iMessage.
Pick exactly ONE shape from allowed_labels that CuBot will fold — a fun, symbolic, visual, or
associative match for what they meant.

NEVER return "none". NEVER leave label blank. ALWAYS pick something from allowed_labels.

Be creative. Prefer resemblance, metaphor, vibe, and wordplay over literal letters.

Fill-in-the-blank / Mad Libs (critical):
- If the text uses "blank", "___", "****", "something", "X", or similar as a placeholder inside a
  known proverb, song lyric, or riddle, FIRST solve what word belongs in the blank from common
  knowledge. Then choose a shape for that solved word (or its meaning) — NOT for the word "blank".
- Example pattern (do not treat as the only case): "a ____ a day keeps the doctor away" solves to
  APPLE. Pick label tree or letter_a from the library if needed, but the caption should say you are
  folding an apple (not "a tree", not "blank days", not a vague health line with no object).
- Same idea for any other well-known phrase with a hole in it: solve, then fold.

How to choose (best → worst):
1. Literal shape request ("make a heart", "do a T") → that shape.
2. Solved fill-in-the-blank answer → shape for that answer (see above).
3. Strong visual / cultural metaphor (lean into these — invent more like them):
   love→heart, cheese/wedge/pizza→triangle, coffee/drink→mug, storm→lightning,
   waves/wifi→square_wave, yes/done→checkmark, nature→tree, space→rocket, boat→boat,
   circle/donut→ring, climb→staircase, time→hourglass, gym→dumbbell, etc.
4. Booth jokes: Jerry/name → letter_j; creator/"who's your daddy"/who made you → letter_u.
5. Soft chitchat / food / random → still invent a playful non-letter link when you can.
6. Absolute last resort ONLY: first letter of the most contentful real word (never the word
   "blank") as letter_<x> if that label is allowed.

Rules:
- Reply with JSON only:
  {"label": "<id>", "caption": "<short fun sentence>", "confidence": 0.0-1.0, "meaning": "<what you're folding as>"}
- label MUST be one of allowed_labels (the robot's library id). Never "none". Never invent a label.
- "meaning" is the everyday thing the fold stands for (apple, cheese wedge, heart, the letter J, …).
  When the library shape is a stand-in (tree for apple, triangle for cheese), meaning is the stand-in
  concept (apple / cheese), not the library id.
- caption MUST say what you are folding in ordinary language, starting with "Folding …":
  good: "Folding an apple, since an apple a day keeps the doctor away"
  good: "Folding a cheese wedge for your cheese craving"
  bad:  "Every blank day counts down to better health"  (never names what is being folded)
  bad:  "Folding shape: tree" / "Folding a tree to represent the apple" (don't expose the library
        stand-in — just say apple)
- One short sentence. No emojis. Never output code, URLs, or phone numbers.
"""


@dataclass
class OpenAIGuess:
    label: str
    caption: str
    confidence: float
    raw: str = ""
    latency_ms: float = 0.0
    via: str = "openai"  # "openai" | "letter_fallback"


def first_letter_fallback(text: str, allowed_labels: Sequence[str]) -> Optional[OpenAIGuess]:
    """Worst-case: fold the first letter of the first content word that we can actually play."""
    labels = {str(x) for x in allowed_labels if x and x != "none"}
    skip = {
        "a", "an", "the", "i", "im", "i'm", "my", "me", "you", "your", "we", "our", "is", "are",
        "was", "were", "be", "to", "of", "in", "on", "for", "and", "or", "but", "if", "do", "did",
        "does", "what", "whats", "what's", "who", "whos", "who's", "where", "when", "why", "how",
        "like", "love", "want", "wanna", "gonna", "just", "some", "any", "this", "that", "it",
        "pls", "please", "hey", "hi", "yo", "ok", "okay", "yeah", "yep", "nah", "no", "yes",
        "make", "fold", "show", "do", "be", "can", "could", "would", "should",
        "blank", "blanks", "something", "someone", "whatever",
    }
    words = re.findall(r"[a-zA-Z]+", (text or "").lower())
    content = [w for w in words if w not in skip and len(w) >= 2] or words
    for word in content:
        ch = word[0]
        label = f"letter_{ch}"
        if label in labels:
            return OpenAIGuess(
                label=label,
                caption=f"Going with a {ch.upper()} — first letter of “{word}”",
                confidence=0.35,
                via="letter_fallback",
            )
    # Any playable letter, then any playable shape.
    for ch in "abcdefghijklmnopqrstuvwxyz":
        label = f"letter_{ch}"
        if label in labels:
            return OpenAIGuess(
                label=label,
                caption=f"Going with a {ch.upper()} as a safe default",
                confidence=0.2,
                via="letter_fallback",
            )
    if labels:
        label = sorted(labels)[0]
        return OpenAIGuess(
            label=label,
            caption=f"Going with {label.replace('_', ' ')} as a safe default",
            confidence=0.15,
            via="letter_fallback",
        )
    return None


class OpenAIFallback:
    """Second opinion that is required to always name a playable shape."""

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
        """Always returns a playable guess when ``allowed_labels`` is non-empty.

        Uses OpenAI when a key is set; on API failure / bad JSON / illegal label, falls back to
        the first-letter heuristic so the booth never gets a blank decline.
        """
        labels = sorted({str(x) for x in allowed_labels if x and x != "none"})
        if not labels:
            return None

        guess: Optional[OpenAIGuess] = None
        if self.enabled:
            guess = self._ask_openai(text, labels)

        if guess is None or guess.label == "none" or guess.label not in labels:
            if guess is not None and guess.label not in labels and guess.label != "none":
                self.log(f"[openai] label {guess.label!r} not playable — letter fallback")
            fb = first_letter_fallback(text, labels)
            if fb is not None:
                self.log(f"[openai] letter fallback -> {fb.label}")
            return fb

        if not guess.caption:
            guess.caption = f"Folding into {guess.label.replace('_', ' ')}"
        return guess

    def _ask_openai(self, text: str, labels: list[str]) -> Optional[OpenAIGuess]:
        payload = {
            "model": self.model,
            "temperature": 0.9,
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
        lowered = label.lower().replace("-", "_")
        if lowered in labels:
            label = lowered
        meaning = str(data.get("meaning") or "").strip()[:60]
        caption = str(data.get("caption") or "").strip()[:160]
        # Force a "Folding …" line that names the everyday thing, not a floating vibe sentence.
        if meaning and not re.search(r"(?i)\bfold(?:ing)?\b", caption):
            caption = f"Folding {meaning}" + (f" — {caption}" if caption else "")
        elif meaning and re.search(r"(?i)\bfolding (?:a |an |the )?(tree|shape)\b", caption):
            # Prefer "Folding an apple" over "Folding a tree to represent the apple"
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
        return OpenAIGuess(label=label or "none", caption=caption, confidence=conf,
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
