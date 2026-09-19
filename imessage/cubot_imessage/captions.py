"""What the robot says back.

Two jobs. First, find who the message is addressed to — "show hack the north some love" is addressed
to Hack the North, and a reply that names them lands far better in a demo than one that does not.
Second, turn a label plus that name into a sentence.

Captions are templates, never the sender's own words echoed back. The only thing lifted from the
inbound text is the greeted name, and it is length-capped, whitespace-collapsed and rejected unless it
looks like a name. That keeps the reply path from becoming a way to make the robot repeat arbitrary
text to a phone number.
"""
from __future__ import annotations

import re
from typing import Optional

MAX_WHO_CHARS = 40
MAX_WHO_WORDS = 4

# Names worth spelling properly when someone texts them casually.
KNOWN_NAMES: dict[str, str] = {
    "hack the north": "Hack the North", "hackthenorth": "Hack the North", "htn": "Hack the North",
    "hack north": "Hack the North", "the judges": "the judges", "judges": "the judges",
    "waterloo": "Waterloo", "uwaterloo": "Waterloo", "uw": "Waterloo", "toronto": "Toronto",
    "everyone": "everyone", "everybody": "everyone", "my team": "my team", "the team": "the team",
}

# Phrases that match the grammar of a name but are not one.
NOT_NAMES = {
    "me", "you", "it", "us", "them", "this", "that", "now", "real", "sure", "fun", "free", "later",
    "once", "ever", "good", "great", "example", "instance", "starters", "a sec", "a second",
    "a minute", "a moment", "a bit", "a while", "a change", "the demo", "the record", "the camera",
    "the win", "the table", "the floor", "the lols", "the meme", "hello", "hi", "hey", "help",
    "love", "some love", "a laugh", "no reason", "old times", "practice", "test", "testing",
}

_VERBS = re.compile(
    r"\b(?:make|draw|build|show|form|write|do|be|spell|turn|become|fold|please|shape|go|get|give)\b",
    re.I)
_DURATION = re.compile(r"\b(?:sec|secs|second|seconds|minute|minutes|hour|hours|\d+)\b", re.I)
_TRAILING = re.compile(r"\s*\b(?:please|pls|plz|now|again|thanks|thank you|ty)\b\s*$", re.I)

_PATTERNS = (
    re.compile(r"\bshow\s+(?P<who>.+?)\s+some\s+(?:love|affection|support)\b", re.I),
    re.compile(r"\bsend\s+(?:some\s+)?love\s+to\s+(?P<who>.+?)(?:\s*[.!?,;]|$)", re.I),
    re.compile(r"\b(?:say\s+(?:hi|hello|hey)\s+to|greet|wave\s+(?:at|to)|hello\s+to|hi\s+to)"
               r"\s+(?P<who>.+?)(?:\s*[.!?,;]|$)", re.I),
    re.compile(r"\b(?:show|give)\s+(?P<who>.+?)\s+(?:a|an|the|some)\s+\w+", re.I),
    re.compile(r"\bfor\s+(?P<who>.+?)(?:\s*[.!?,;]|$)", re.I),
)


def extract_who(text: str) -> Optional[str]:
    """The greeted entity, or None when nobody is addressed.

    'show hack the north some love' -> 'Hack the North'
    'build a bridge for my team'    -> 'my team'
    'make a heart for a sec'        -> None    (a duration, not a name)
    """
    clean = " ".join(str(text).split())
    for pattern in _PATTERNS:
        match = pattern.search(clean)
        if not match:
            continue
        who = _TRAILING.sub("", match.group("who").strip(" \"'")).strip()
        lowered = who.lower()
        if not who or len(who) > MAX_WHO_CHARS or len(who.split()) > MAX_WHO_WORDS:
            continue
        if lowered in NOT_NAMES or _VERBS.search(lowered) or _DURATION.search(lowered):
            continue
        return KNOWN_NAMES.get(lowered) or KNOWN_NAMES.get(lowered.replace("the ", "", 1)) or who
    return None


# Per-label captions: (addressed to someone, addressed to nobody).
TEMPLATES: dict[str, tuple[str, str]] = {
    "heart": ("Showing {who} some love with a heart", "Folding into a heart, with love"),
    # letter jokes the head learns from paraphrases (Jerry→J, creator→U/"you")
    "letter_j": ("A J for {who}", "Making a J — as in Jerry"),
    "letter_u": ("A U for {who}", "Making a U — as in you"),
    "arrow": ("Pointing the way for {who}", "Pointing the way with an arrow"),
    "arrow_up": ("Pointing up for {who}", "Pointing up"),
    "arrow_down": ("Pointing down for {who}", "Pointing down"),
    "arrow_left": ("Pointing left for {who}", "Pointing left"),
    "lightning": ("A lightning bolt for {who}", "Striking a lightning bolt"),
    "plus": ("A plus sign for {who}", "Making a plus sign"),
    "square": ("A square for {who}", "Folding into a square"),
    "ring": ("A ring for {who}", "Closing into a ring"),
    "triangle": ("A triangle for {who}", "Folding into a triangle"),
    "diamond": ("A diamond for {who}", "Folding into a diamond"),
    "spiral": ("Curling into a spiral for {who}", "Curling into a spiral"),
    "staircase": ("Stacking up a staircase for {who}", "Stacking up into a staircase"),
    "square_wave": ("A wave for {who}", "Rolling into a square wave"),
    "hourglass": ("An hourglass for {who}", "Folding into an hourglass"),
    "checkmark": ("A checkmark for {who}", "Marking a checkmark"),
    "hook": ("A hook for {who}", "Curling into a hook"),
    "crown": ("A crown for {who}", "Folding into a crown"),
    "anchor": ("An anchor for {who}", "Dropping into an anchor"),
    "bell": ("A bell for {who}", "Folding into a bell"),
    "boat": ("A boat for {who}", "Setting sail as a boat"),
    "dumbbell": ("A dumbbell for {who}", "Folding into a dumbbell"),
    "flag": ("Flying a flag for {who}", "Raising a flag"),
    "mug": ("A mug for {who}", "Folding into a mug"),
    "umbrella": ("An umbrella for {who}", "Opening into an umbrella"),
    "rocket": ("A rocket for {who}", "Folding into a rocket"),
    "tree": ("A tree for {who}", "Growing into a tree"),
    "mushroom": ("A mushroom for {who}", "Folding into a mushroom"),
    "table": ("A table for {who}", "Folding into a table"),
    "chair": ("A chair for {who}", "Folding into a chair"),
    "music_note": ("A music note for {who}", "Folding into a music note"),
}


def pretty(label: str) -> str:
    """'letter_h' -> 'the letter H'; 'digit_7' -> 'the number 7'; 'square_wave' -> 'a square wave'."""
    if label.startswith("letter_"):
        return f"the letter {label[7:].upper()}"
    if label.startswith("digit_"):
        return f"the number {label[6:]}"
    spaced = label.replace("_", " ")
    return f"{'an' if spaced[:1] in 'aeiou' else 'a'} {spaced}"


def caption_for(label: str, who: Optional[str] = None) -> str:
    """A sentence for one label, naming `who` when there is one."""
    if label in TEMPLATES:
        addressed, alone = TEMPLATES[label]
    elif label.startswith(("letter_", "digit_")):
        nice = pretty(label)[4:]                                  # drop the leading 'the '
        addressed, alone = f"The {nice} for {{who}}", f"Making the {nice}"
    else:
        nice = pretty(label)
        addressed, alone = f"Making {nice} for {{who}}", f"Making {nice}"
    return addressed.format(who=who) if who else alone


def caption(label: str, text: str = "") -> str:
    """Caption for a label, taking the greeted name from the originating message."""
    return caption_for(label, extract_who(text) if text else None)
