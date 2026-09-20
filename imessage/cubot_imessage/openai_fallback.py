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
Your job: pick exactly ONE label from allowed_labels for CuBot to fold.

NEVER return "none". NEVER leave label blank. ALWAYS pick from allowed_labels.

How to think (do this every time):
1. Name the subject in plain English (what are they talking about?).
2. Picture it as a simple cut-paper silhouette — ignore spelling entirely.
3. Classify that silhouette into a geometric / iconic family, then pick the closest
   allowed_labels member of that family.

Silhouette families (principles, not special cases — apply to whatever subject you imagined):
- tapered, conical, pointed tip, triangular mass, or a WEDGE/SLICE of food → triangle
- round with a hole through it → ring or donut
- round solid face / blob → smiley (or ring if that is all you have)
- round fruit / orchard produce (when no fruit icon exists) → tree as a stand-in
- cup / vessel you drink from → mug or bottle or wine_glass
  (a solid food is not a drink — do not pick mug just because someone said "want")
- bipedal pet / animal with clear library icon → that animal label if present
- heart / love symbol → heart
- check / approval → checkmark
- bolt / zig energy → lightning or square_wave
- stairs / climb → staircase or stairs
- rocket / tall finned vehicle → rocket
- boat / hull → boat
- boxy frame → square or cube_frame
If several labels fit the family, pick the one that would read clearest from across a room.

Spelling is a trap for ordinary nouns (food, objects, animals, vibes) — never answer those
with the first letter of the word. letter_* / single-letter labels are for:
- they clearly asked for that glyph ("make a C", "letter J", "fold an H", or the message is just "C"), OR
- the subject is a person / pet / proper name (or a clear nickname) and no library icon fits better
  — then the first letter of that name is fine (Jerry → letter_j, Sam → letter_s).
Do not treat a common noun as a "name" just to excuse a letter.

Also:
- Fill-in-the-blank / Mad Libs: if the text has "blank", "___", "****", "something" inside a
  known proverb/lyric/riddle, solve the missing word first, then silhouette-match the SOLVED
  word — not the word "blank".
- Names / creator jokes: a proper name or nickname → first letter when no icon fits;
  "who made you" / creator bits → letter_u. Still never first-letter a common noun.
- Last resort for non-names: any clear NON-letter icon from allowed_labels.

Rules:
- Reply with JSON only:
  {"label": "<id>", "silhouette": "<3-6 word outline description>",
   "meaning": "<everyday subject>", "caption": "<short fun sentence>", "confidence": 0.0-1.0}
- label MUST be one of allowed_labels. Never invent a label.
- "silhouette" is your cut-paper reading (e.g. "tapered wedge pointing up") — fill it before
  you commit to label. "meaning" is the everyday subject. Caption starts with "Folding …"
  and names that subject in ordinary language (not the raw library id).
  good: "Folding a carrot" / "Folding a cheese wedge" / "Folding an apple"
  bad:  "Going with a C — first letter of …"
- One short sentence. No emojis. Never output code, URLs, or phone numbers.
"""


@dataclass
class OpenAIGuess:
    label: str
    caption: str
    confidence: float
    raw: str = ""
    latency_ms: float = 0.0
    via: str = "openai"  # "openai" | "icon_fallback" | "letter_fallback"


def _norm_label(label: str) -> str:
    return str(label or "").strip().lower().replace("-", "_")


def _is_letter_label(label: str) -> bool:
    lab = _norm_label(label)
    if lab.startswith("letter_") and len(lab) == 8:
        return True
    return len(lab) == 1 and lab.isalpha()


_NAME_CUE = re.compile(
    r"(?i)\b(?:i(?:'m| am)|my name(?:'s| is)|call me|named|for)\s+([A-Za-z]{2,})\b"
)
# Common nouns we must never treat as "names" for a first-letter excuse.
_NOT_A_NAME = {
    "carrot", "carrots", "cheese", "pizza", "apple", "coffee", "love", "heart", "dog", "cat",
    "rabbit", "boat", "rocket", "tree", "phone", "home", "house", "triangle", "square",
    "circle", "donut", "mug", "blank", "something", "please", "thanks", "hello", "hack",
    "north", "cubot", "robot", "shape", "letter", "make", "fold", "show", "want", "like",
}


def _letter_from_label(label: str) -> Optional[str]:
    lab = _norm_label(label)
    if lab.startswith("letter_") and len(lab) == 8:
        return lab[-1]
    if len(lab) == 1 and lab.isalpha():
        return lab
    return None


def name_initial_ok(text: str, label: str) -> bool:
    """True when a letter label matches the initial of a probable person/pet name in the text."""
    ch = _letter_from_label(label)
    if not ch:
        return False
    raw = text or ""
    # Explicit name cues: "I'm Sam", "my name is Jerry", "for Alex"
    for m in _NAME_CUE.finditer(raw):
        word = m.group(1)
        if word.lower() not in _NOT_A_NAME and word[0].lower() == ch:
            return True
    # Title-case tokens (Jerry, Sam) that aren't sentence-start filler.
    words = re.findall(r"[A-Za-z]+", raw)
    for i, w in enumerate(words):
        if len(w) < 2 or w.lower() in _NOT_A_NAME:
            continue
        if not w[0].isupper():
            continue
        # Skip the first word of the message unless it's clearly a bare name.
        if i == 0 and len(words) > 1 and w.lower() in {"make", "fold", "show", "do", "can", "please"}:
            continue
        if w[0].lower() == ch:
            return True
    return False


def wants_explicit_letter(text: str) -> bool:
    """True only when the utterance is clearly asking for a letter glyph."""
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
    """Map a preferred shape id onto whatever spelling the allowed set uses."""
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


def first_letter_fallback(text: str, allowed_labels: Sequence[str]) -> Optional[OpenAIGuess]:
    """Last-resort booth recovery when the API is down or returns garbage.

    No word→shape dictionary — prefer any non-letter icon over a spelling letter.
    """
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

    icons = sorted(lab for lab in labels if not _is_letter_label(lab))
    if icons and not wants_explicit_letter(text):
        label = icons[0]
        return OpenAIGuess(
            label=label,
            caption=f"Folding {label.replace('_', ' ').replace('-', ' ')} as a safe default",
            confidence=0.25,
            via="icon_fallback",
        )

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
        label = _pick_allowed(f"letter_{ch}", labels) or _pick_allowed(ch, labels)
        if label:
            return OpenAIGuess(
                label=label,
                caption=f"Going with a {ch.upper()} — first letter of “{word}”",
                confidence=0.35,
                via="letter_fallback",
            )
    for ch in "abcdefghijklmnopqrstuvwxyz":
        label = _pick_allowed(f"letter_{ch}", labels) or _pick_allowed(ch, labels)
        if label:
            return OpenAIGuess(
                label=label,
                caption=f"Going with a {ch.upper()} as a safe default",
                confidence=0.2,
                via="letter_fallback",
            )
    label = sorted(labels)[0]
    return OpenAIGuess(
        label=label,
        caption=f"Going with {label.replace('_', ' ')} as a safe default",
        confidence=0.15,
        via="letter_fallback",
    )


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

        Uses OpenAI when a key is set; rejects lazy letter picks unless the user clearly
        asked for a letter; recovers with a non-letter icon when possible.
        """
        labels = sorted({str(x) for x in allowed_labels if x and x != "none"})
        if not labels:
            return None
        label_set = set(labels)

        guess: Optional[OpenAIGuess] = None
        if self.enabled:
            guess = self._ask_openai(text, labels)

        def _usable(g: Optional[OpenAIGuess]) -> bool:
            if g is None or g.label == "none" or g.label not in label_set:
                return False
            if _is_letter_label(g.label):
                return wants_explicit_letter(text) or name_initial_ok(text, g.label)
            return True

        if not _usable(guess):
            if guess is not None and guess.label not in label_set and guess.label != "none":
                self.log(f"[openai] label {guess.label!r} not playable — booth fallback")
            elif guess is not None and _is_letter_label(guess.label):
                self.log(f"[openai] rejected lazy letter {guess.label!r} for {text!r} — booth fallback")
            fb = first_letter_fallback(text, labels)
            if fb is not None:
                self.log(f"[openai] {fb.via} -> {fb.label}")
            return fb

        assert guess is not None
        if not guess.caption:
            guess.caption = f"Folding into {guess.label.replace('_', ' ')}"
        return guess

    def _ask_openai(self, text: str, labels: list[str]) -> Optional[OpenAIGuess]:
        payload = {
            "model": self.model,
            "temperature": 0.7,
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
        if lowered in labels:
            label = lowered
        elif label not in labels:
            alt = _pick_allowed(label, set(labels))
            if alt:
                label = alt
        meaning = str(data.get("meaning") or "").strip()[:60]
        caption = str(data.get("caption") or "").strip()[:160]
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
