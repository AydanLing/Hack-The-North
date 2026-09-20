"""Bridging two vocabularies: the classifier's labels and CuBot V2's shape names.

Three things have to be reconciled.

**Spelling.** The classifier and the planner name shapes differently, mostly mechanically::

    classifier   heart  lightning  plus  letter_h  digit_0  square_wave  arrow_up   checkmark
    cubot-v2     heart  lightning  plus  h         d0       square-wave  up-arrow   checkmark

`letter_h -> letter-h -> h` is a rule; the rest is an alias table mirroring
`cubot/generate/parametric.py::_ALIASES`. It is duplicated here rather than imported because
`handoff/` is a dependency-free folder by design — the bridge must run without the planner installed.

**Variants.** A handoff folder is one *mask*, not one concept. In the 84-shape export, dirs 50-84 are
glyph-atlas candidates carrying a `-vNN` mask suffix, so `spiral`, `spiral-v01` and `spiral-v02` are
three drawings of one idea. A text says "spiral"; something has to pick which drawing to fold.
`Vocabulary` groups dirs by concept and ranks the variants — a plan that passes its hard checks beats
one that does not, finishing flat beats finishing on edge, then fewer moves, then the lower demo
number (so the reviewed demo seven always win their own concept).

**Reachability.** A cubot icon is in one of three states, and a reply should distinguish them:

* **playable** — a fold path exists under `handoff/shapes/`. Read live from `handoff/index.json`, so
  exporting more shapes needs no code change here.
* **plannable** — verified in `parametric.py` but not exported. One `tools/export_handoff.py` away.
* **rejected** — dropped in review for poor recognizability. Not coming back.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

VARIANT_SUFFIX = re.compile(r"-v\d+$")

# --------------------------------------------------------------------------- cubot-v2 shape registry
# Mirrors cubot/generate/parametric.py (DEMO_NAMES / EXPLORED_NAMES / REJECTED_NAMES).
CUBOT_DEMO = ("heart", "arrow", "lightning", "plus", "h", "t", "n")
CUBOT_PLANNABLE = (
    # mask-first exploration winners, plus the single-letter glyph-atlas candidates (docs/DISCOVERY.md
    # lists b c d f h j l n o q t u y z; g, p, r and x have no cubot shape at all)
    "a", "b", "c", "d", "e", "f", "i", "j", "k", "l", "m", "q", "s", "u", "v", "w", "y", "z",
    "d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9",
    "square", "ring", "square-wave", "spiral", "staircase", "checkmark", "triangle", "hourglass",
    "anchor", "dumbbell", "flag", "mug", "umbrella", "bell", "boat", "rocket", "tree",
    "up-arrow", "arrow-down", "arrow-left", "hook", "crown", "diamond", "mushroom", "table", "chair",
)
CUBOT_REJECTED = ("house", "fish", "star", "music-note", "key", "question-mark", "smiley")

CUBOT_ALIASES: dict[str, str] = {
    "bolt": "lightning", "lightning-bolt": "lightning", "cross": "plus", "+": "plus",
    "note": "music-note", "music": "music-note", "question": "question-mark", "?": "question-mark",
    "smile": "smiley", "wave": "square-wave", "signal": "square-wave", "zigzag": "square-wave",
    "cup": "mug", "check": "checkmark", "tick": "checkmark",
    # "stairs" is its own handoff shape (100+); only map near-synonyms onto staircase.
    "stair": "staircase", "stair-case": "staircase",
    "barbell": "dumbbell",
    # "box" stays the flat 2-D square glyph; 3-D "cube"/"block" route to cube-frame.
    "box": "square", "o": "ring", "circle": "ring", "ship": "boat",
    "arrow-up": "up-arrow", "plane": "aeroplane",
    "cube": "cube-frame", "block": "cube-frame", "cubeframe": "cube-frame",
    "cube-frame": "cube-frame",
    # newly playable concepts that used to live only under CUBOT_REJECTED / near-synonyms
    "television": "tv", "telly": "tv", "happy-face": "smiley", "chat-bubble": "speech-bubble",
    "moon": "crescent-moon", "wineglass": "wine-glass", "rubbish": "trash", "bin": "trash",
    "mobile": "phone", "cellphone": "phone",
    # Gear-safe letter demos (handoff 137–138). Silhouette-verified; ≤4 cubes/move.
    "easy-u": "easy-u", "tip-u": "easy-u", "soft-u": "easy-u", "demo-u": "easy-u",
    "gentle-u": "easy-u",
    "easy-l": "easy-l", "tip-l": "easy-l", "soft-l": "easy-l", "demo-l": "easy-l",
    "gentle-l": "easy-l",
    **{f"letter-{c}": c for c in "abcdefghijklmnopqrstuvwxyz"},
    # cubot writes digits both ways depending on the run: "d0" in the exploration export, "0" in
    # parametric's registry. Accept either and canonicalise on the "d" form.
    **{f"digit-{d}": f"d{d}" for d in range(10)},
    **{str(d): f"d{d}" for d in range(10)},
    **{w: f"d{d}" for d, w in enumerate(
        ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"))},
}

# Classifier labels the mechanical `_`->`-` rule would miss or send to the wrong concept.
# The rule handles most of the namespace on its own: letter_h -> letter-h -> h, digit_0 -> digit-0
# -> d0, square_wave -> square-wave, music_note -> music-note.
LABEL_OVERRIDES: dict[str, str] = {
    "arrow_up": "up-arrow",          # cubot's exploration export calls it up-arrow
    "none": "",                      # the out-of-scope class names no shape at all
    # tolerated spellings, in case a head trained elsewhere is loaded
    "arrow_right": "arrow",
    "circle": "ring",
    "box": "square",
    "cup": "mug",
    "check": "checkmark",
    "zigzag": "square-wave",
}

OUT_OF_SCOPE = "none"          # the classifier's explicit chitchat class; never names a shape

STATUS_PLAYABLE = "playable"
STATUS_PLANNABLE = "plannable"
STATUS_REJECTED = "rejected"
STATUS_UNMAPPED = "unmapped"
STATUS_UNSURE = "unsure"


def strip_variant(name: str) -> str:
    """'check-v01' -> 'check'; leaves a name without a mask suffix alone."""
    return VARIANT_SUFFIX.sub("", str(name).strip().lower())


def normalize_label(label: str) -> str:
    """Classifier label -> cubot alias spelling: 'letter_h' -> 'letter-h', 'digit_0' -> 'digit-0'."""
    return str(label).strip().lower().replace("_", "-")


def label_to_icon(label: str) -> str:
    """Best cubot concept name for a classifier label. Returns the normalized label unchanged when
    there is no alias for it — the caller then sees STATUS_UNMAPPED. The out-of-scope class names no
    shape and maps to the empty string."""
    if label in LABEL_OVERRIDES:
        candidate = LABEL_OVERRIDES[label]
        if not candidate:                       # 'none' -> no shape at all
            return ""
    else:
        candidate = normalize_label(label)
    return CUBOT_ALIASES.get(candidate, candidate)


def icon_key(name: str) -> str:
    """Canonical concept key for any cubot name, variant suffix and aliases resolved."""
    base = strip_variant(name)
    return CUBOT_ALIASES.get(base, base)


@dataclass
class Resolution:
    """What the bridge decided a classified utterance means for the robot."""

    status: str
    label: str
    icon: str = ""                     # cubot concept name
    shape: str = ""                    # the handoff dir name to fold (a specific mask variant)
    variants: list[str] = field(default_factory=list)   # every playable mask of this concept
    nearest_playable: str = ""
    nearest_score: float = 0.0
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PLAYABLE


def _variant_rank(row: dict) -> tuple:
    """Sort key for choosing between masks of one concept. Lower is better:
    passes hard checks, finishes flat, fewer moves, then the reviewed demo shapes first."""
    return (
        0 if row.get("loose_hard_ok", True) else 1,
        0 if row.get("ends_flat_on_table", True) else 1,
        int(row.get("moves", 999) or 999),
        int(row.get("number", 999) or 999),
    )


class Vocabulary:
    """The playable set, read from `handoff/index.json`. Works unchanged for a 7-shape or an
    84-shape export."""

    def __init__(self, handoff_dir: str):
        self.handoff_dir = handoff_dir
        self.index_path = os.path.join(handoff_dir, "index.json")
        self.rows: dict[str, dict] = {}                      # handoff dir name -> index row
        self.concepts: dict[str, list[str]] = {}             # concept -> its mask names, best first
        self._alias_to_concept: dict[str, str] = {}
        self.roll: str = ""
        self.load()

    def load(self) -> "Vocabulary":
        if not os.path.isfile(self.index_path):
            raise FileNotFoundError(
                f"no handoff index at {self.index_path}. Point CUBOT_HANDOFF_DIR at cubot-v2/handoff-17, "
                f"or regenerate it with `uv run python tools/export_handoff.py`."
            )
        with open(self.index_path, encoding="utf-8") as f:
            index = json.load(f)
        self.roll = str(index.get("roll", ""))
        self.rows, self.concepts, self._alias_to_concept = {}, {}, {}

        grouped: dict[str, list[dict]] = {}
        for row in index.get("shapes", []):
            name = str(row.get("name", "")).strip().lower()
            if not name:
                continue
            self.rows[name] = row
            grouped.setdefault(icon_key(name), []).append(row)

        for concept, rows in grouped.items():
            rows.sort(key=_variant_rank)
            self.concepts[concept] = [str(r["name"]).lower() for r in rows]
            self._alias_to_concept[concept] = concept
            for row in rows:                                  # each mask name also addresses its concept
                self._alias_to_concept[str(row["name"]).lower()] = concept
                for alias in row.get("aliases", []) or []:
                    self._alias_to_concept.setdefault(str(alias).lower(), concept)
        for alias, canonical in CUBOT_ALIASES.items():
            if canonical in self.concepts:
                self._alias_to_concept.setdefault(alias, canonical)
        return self

    # -- queries -----------------------------------------------------------------------------
    @property
    def playable(self) -> list[str]:
        """One name per concept — the mask the bridge would actually fold, in demo order."""
        best = [self.concepts[c][0] for c in self.concepts]
        return sorted(best, key=lambda n: self.rows[n].get("number", 999))

    @property
    def playable_concepts(self) -> list[str]:
        return sorted(self.concepts, key=lambda c: self.rows[self.concepts[c][0]].get("number", 999))

    def shape_for_icon(self, icon: str) -> Optional[str]:
        """The handoff dir name to fold for a concept (best variant), or None."""
        concept = self._alias_to_concept.get(icon_key(icon)) or self._alias_to_concept.get(str(icon).lower())
        return self.concepts[concept][0] if concept else None

    def variants_for_icon(self, icon: str) -> list[str]:
        concept = self._alias_to_concept.get(icon_key(icon)) or self._alias_to_concept.get(str(icon).lower())
        return list(self.concepts.get(concept, [])) if concept else []

    def playable_labels(self, labels: Optional[list[str]] = None) -> dict[str, str]:
        """MiniLM label -> handoff shape, for the labels that reach one. Used to restrict the
        classifier's scores to what the robot can actually fold."""
        out: dict[str, str] = {}
        for label in (labels or _ALL_KNOWN_LABELS):
            shape = self.shape_for_icon(label_to_icon(label))
            if shape:
                out[label] = shape
        return out

    def is_flagged(self, shape: str) -> tuple[bool, str]:
        """Shapes the handoff itself warns about (failed hard checks)."""
        row = self.rows.get(str(shape).lower(), {})
        notes = []
        if row.get("loose_hard_ok") is False:
            violations = row.get("loose_violations")
            count = violations if isinstance(violations, int) else len(violations or [])
            notes.append(f"{count} hard-check violation(s) — expected to fail physically")
        return bool(notes), "; ".join(notes)

    # -- the decision ------------------------------------------------------------------------
    def resolve(self, label: str, accepted: bool = True, nearest: Optional[tuple[str, float]] = None,
                nearest_label_map: Optional[dict[str, str]] = None) -> Resolution:
        """Turn a classifier label into a Resolution.

        `accepted` is the head's own threshold verdict; `nearest` an optional (label, score) from
        `Classifier.restricted_best`, used to offer something foldable when the request is not.
        """
        near_shape, near_score = "", 0.0
        if nearest:
            near_label, near_score = nearest
            near_shape = (nearest_label_map or {}).get(near_label, "") or \
                self.shape_for_icon(label_to_icon(near_label)) or ""

        if label == OUT_OF_SCOPE or not accepted:
            # The classifier's out-of-scope class is a decision, not a missing mapping. The head
            # already refuses to accept it, but say so here too so the semantics hold however
            # resolve() is called.
            detail = ("That did not look like a shape request."
                      if label == OUT_OF_SCOPE else "I could not tell which shape that meant.")
            return Resolution(STATUS_UNSURE, label, nearest_playable=near_shape,
                              nearest_score=near_score, detail=detail)

        icon = label_to_icon(label)
        shape = self.shape_for_icon(icon)
        if shape:
            flagged, why = self.is_flagged(shape)
            return Resolution(STATUS_PLAYABLE, label, icon=icon, shape=shape,
                              variants=self.variants_for_icon(icon), nearest_playable=shape,
                              nearest_score=near_score, detail=why if flagged else "")
        if icon_key(icon) in {icon_key(p) for p in CUBOT_PLANNABLE}:
            return Resolution(STATUS_PLANNABLE, label, icon=icon, nearest_playable=near_shape,
                              nearest_score=near_score,
                              detail=f"'{icon}' is planned and verified in cubot-v2 but not exported to "
                                     f"handoff/ yet, so there is no fold path to run.")
        if icon in CUBOT_REJECTED:
            return Resolution(STATUS_REJECTED, label, icon=icon, nearest_playable=near_shape,
                              nearest_score=near_score,
                              detail=f"'{icon}' was reviewed and dropped for poor recognizability.")
        return Resolution(STATUS_UNMAPPED, label, icon=icon, nearest_playable=near_shape,
                          nearest_score=near_score, detail=f"'{label}' has no cubot-v2 shape.")


# Labels the head is known to emit; only used to precompute `playable_labels()` when the caller has
# no classifier handy. An unknown label still resolves correctly through `label_to_icon`.
_ALL_KNOWN_LABELS: tuple[str, ...] = (
    "heart", "arrow", "arrow_up", "arrow_down", "arrow_left", "lightning", "plus",
    *(f"letter_{c}" for c in "abcdefghijklmnopqrstuvwxyz"),
    *(f"digit_{d}" for d in range(10)),
    "square", "ring", "triangle", "diamond", "spiral", "staircase", "square_wave", "hourglass",
    "checkmark", "hook", "crown",
    "anchor", "bell", "boat", "dumbbell", "flag", "mug", "umbrella", "rocket", "tree", "mushroom",
    "table", "chair", "music_note",
)
