"""Deterministic, offline target drawings for the icon-first phase.

Two sources feed the registry: the hand-maintained ``_PATTERNS`` dict below
(the demo seven, the seven harvest-era rejects and the 2026-09-19 exploration
winners) and the file-backed library under ``data/library/<category>/<name>.txt``
(``docs/METHOD.md``, "at scale").  Library files are ASCII masks with optional
``// aliases: a, b`` and ``// variant: <stem>`` header lines; they are appended
after the hand-maintained entries so ``ICON_NAMES`` keeps its order contract
(``DEMO_NAMES + REJECTED_NAMES + EXPLORED_NAMES``).
"""

from __future__ import annotations

from pathlib import Path

from .base import PixelTarget, parse_grid

LIBRARY_ROOT = Path(__file__).resolve().parents[2] / "data" / "library"


_PATTERNS: dict[str, tuple[str, ...]] = {
    "heart": (
        ".##..##",
        "#######",
        "#######",
        "..####.",
        "..###..",
        "...##..",
    ),
    "arrow": (
        "....###...",
        "#####.####",
        ".........#",
        ".........#",
        ".......###",
        "#####.##..",
        "....###...",
    ),
    "lightning": (
        "......#",
        "......#",
        "....###",
        "....#..",
        "...##..",
        "..##...",
        "..#....",
        "..#####",
        "......#",
        "...####",
        "...#...",
        ".###...",
        "##.....",
    ),
    # Recognition-first demo glyphs.  Unlike the looser visual targets above,
    # each mask has exactly 27 cells and has an exact threading under the
    # shipped roll.  The deliberately chunky strokes survive the cube gaps in
    # a clean silhouette render.
    "plus": (
        "...##...",
        ".######.",
        ".#######",
        "########",
        "...##...",
        "...##...",
    ),
    "h": (
        "##....",
        "###.##",
        "###..#",
        "######",
        "##..##",
        "##..##",
        "##....",
    ),
    "t": (
        "##########",
        "##########",
        "......#...",
        "......#...",
        "......#...",
        "......#...",
        "......#...",
        "......#...",
        "......#...",
    ),
    "n": (
        "###..#",
        "#.##.#",
        "#..#.#",
        "#..#.#",
        "#..#.#",
        "#..#.#",
        "#..#.#",
        "#..###",
    ),
    "house": (
        "...#...",
        "..#.#..",
        ".#...#.",
        "#######",
        "#.....#",
        "#..#..#",
        "#######",
    ),
    "fish": (
        "......#.",
        "..###..#",
        ".#...###",
        "#.....##",
        ".#...###",
        "..###..#",
        "......#.",
    ),
    "star": (
        "....#....",
        "....#....",
        "...#.#...",
        "###...###",
        ".#.....#.",
        "..#...#..",
        "..#.#.#..",
        ".#.....#.",
    ),
    "music-note": (
        "...####",
        "...#..#",
        "...#...",
        "...#...",
        "...#...",
        ".###...",
        "#..#...",
        ".##....",
    ),
    "key": (
        ".###....",
        "#...#...",
        "#...#...",
        ".###....",
        "...#....",
        "....#.#.",
        ".....###",
    ),
    "question-mark": (
        ".####.",
        "#....#",
        "....#.",
        "...#..",
        "..#...",
        "......",
        "..#...",
    ),
    "smiley": (
        ".#####.",
        "#.....#",
        "#.#.#.#",
        "#.....#",
        "#.#.#.#",
        "#..#..#",
        ".#####.",
    ),
    # Exploration winners (docs/EXPLORATION-20260919.md): exact 27-cell
    # shipped-roll threadings with a complete loose-passing fold, judged
    # recognizable in review.  Not part of DEMO_NAMES.
    "c": (  # c-v5
        "#######",
        "#######",
        "##.....",
        "##.....",
        "##.....",
        "##.....",
        "#####..",
    ),
    "j": (  # j-v3
        ".....##",
        "......#",
        "......#",
        "......#",
        "......#",
        "......#",
        "##....#",
        "##....#",
        "#######",
        "#######",
    ),
    "m": (  # m-v10
        "###.###",
        "#.#.#.#",
        "#.#.#.#",
        "#.#.#.#",
        "#.#.#.#",
        "#.###.#",
    ),
    "square-wave": (  # wave-v7
        "#....######....",
        "#....#....#....",
        "#....#....#....",
        "#....#....#....",
        "######....#####",
    ),
    "w": (  # w-v10
        "#.###.#",
        "#.#.#.#",
        "#.#.#.#",
        "#.#.#.#",
        "#.#.#.#",
        "###.###",
    ),
    "mug": (  # mug-v2
        "#####..",
        "#...#..",
        "#...#..",
        "#...###",
        "#...#.#",
        "#...###",
        "#...#..",
        "#####..",
    ),
    "2": (  # d2-v2
        "#####",
        "####.",
        "...##",
        "#####",
        "#....",
        "#####",
        "#####",
    ),
    "5": (  # d5-v2
        "#####",
        ".####",
        "##...",
        "#####",
        "....#",
        "#####",
        "#####",
    ),
    "k": (  # k-v9
        "##..##",
        "##.###",
        "##.#..",
        "####..",
        "###...",
        "#####.",
        "##..#.",
    ),
    "s": (  # s-v6
        "######",
        "#.....",
        "#.....",
        "######",
        ".....#",
        "######",
        "######",
    ),
    "checkmark": (  # checkmark-v1
        "...........###",
        "..........##..",
        "..........#...",
        "........###...",
        "........#.....",
        "#.....###.....",
        "#....##.......",
        "###..#........",
        "..#.##........",
        "..###.........",
    ),
    "staircase": (  # staircase-v2
        "#........",
        "#........",
        "#........",
        "#........",
        "###......",
        "..#......",
        "..#......",
        "..#......",
        "..###....",
        "....#....",
        "....#....",
        "....#....",
        "....###..",
        "......#..",
        "......#..",
        "......#..",
        "......###",
        "........#",
        "........#",
    ),
    "i": (  # i-v8
        "######.",
        "####...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...####",
        ".######",
    ),
    "3": (  # d3-v5
        "######",
        ".....#",
        "...###",
        "...###",
        ".....#",
        ".....#",
        "######",
        "######",
    ),
    "v": (  # v-v3
        "##.....##",
        "##.....##",
        ".##....##",
        "..#...###",
        "..#...#..",
        "..#..##..",
        "..##.#...",
        "...###...",
    ),
    "dumbbell": (  # dumbbell-v5
        "##.......##",
        "##.......##",
        "###########",
        "###.......#",
        "###.......#",
    ),
    "4": (  # d4-v5
        "#...##",
        "#...##",
        "#...##",
        "######",
        "...###",
        "...###",
        "...###",
        "...###",
    ),
    "8": (  # d8-v4
        "#####",
        "#...#",
        "#...#",
        "#####",
        "#####",
        "#...#",
        "#...#",
        "####.",
    ),
    "l": (  # l-v3
        "###...",
        "###...",
        "###...",
        "###...",
        "###...",
        "######",
        "######",
    ),
    "1": (  # d1-v2
        "..##.",
        "####.",
        "####.",
        "..##.",
        "..##.",
        "..##.",
        "..##.",
        "#####",
        ".####",
    ),
    "bell": (  # bell-v4
        "..##..",
        ".####.",
        ".#..#.",
        ".####.",
        "######",
        "######",
        ".###..",
    ),
    "7": (  # d7-v4
        "######",
        "######",
        "....##",
        "....##",
        "....##",
        "...###",
        "..##..",
        "..##..",
        "..##..",
    ),
    "0": (  # d0-v8
        ".#####",
        "######",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "######",
    ),
    "u": (  # u-v4
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        "##....##",
        ".#######",
    ),
    "anchor": (  # anchor-v4
        "..###...",
        "..#.#...",
        "..###...",
        "...##...",
        "...##...",
        "...##..#",
        "#..##..#",
        "########",
    ),
    "e": (  # e-v3
        "######",
        "#.....",
        "#.....",
        "######",
        "######",
        "#.....",
        "######",
    ),
    "square": (  # square-v1
        "########",
        "#......#",
        "#......#",
        "#......#",
        "#......#",
        "#......#",
        "#......#",
        "#####.##",
    ),
    "spiral": (  # spiral-v1
        "########",
        ".......#",
        ".......#",
        ".###...#",
        ".#.....#",
        ".#.....#",
        ".#.....#",
        ".#######",
    ),
    "y": (  # y-v2
        "##.....##",
        "####..###",
        "...#..#..",
        "...####..",
        "...##....",
        "...##....",
        "...##....",
        "...##....",
        "...##....",
    ),
    "6": (  # d6-v7
        ".#####",
        "##....",
        "##....",
        "##....",
        "######",
        "#....#",
        "#....#",
        "######",
    ),
    "9": (  # d9-v6
        "######",
        "#....#",
        "#....#",
        "######",
        "....##",
        "....##",
        "....##",
        "#####.",
    ),
    "flag": (  # flag-v2
        "#######",
        "#######",
        "#######",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
    ),
    "f": (  # f-v3
        "######",
        "##...#",
        "##....",
        "####..",
        "####..",
        "##....",
        "##....",
        "##....",
        "##....",
    ),
    "ring": (  # ring-v1
        ".#####.",
        "##...##",
        "##....#",
        "#.....#",
        "#.....#",
        "#.....#",
        "##...##",
        ".#####.",
    ),
    "boat": (  # boat-v6
        "..##.....",
        "..##.....",
        "####.....",
        "...#.....",
        "#########",
        "#########",
    ),
    "umbrella": (  # umbrella-v7
        "...##..",
        "#######",
        "#######",
        "....#..",
        "....#..",
        "..#.#..",
        "..#.#..",
        "..#.#..",
        "..###..",
    ),
    "a": (  # a-v3
        "..##..",
        ".###..",
        ".#.#..",
        "##.##.",
        "#####.",
        "##..#.",
        "##..##",
        "##..##",
    ),
}

_ALIASES = {
    "bolt": "lightning",
    "lightning-bolt": "lightning",
    "cross": "plus",
    "+": "plus",
    "letter-h": "h",
    "letter-t": "t",
    "letter-n": "n",
    "note": "music-note",
    "music": "music-note",
    "question": "question-mark",
    "?": "question-mark",
    "smile": "smiley",
    "letter-c": "c",
    "letter-j": "j",
    "letter-m": "m",
    "wave": "square-wave",
    "signal": "square-wave",
    "letter-w": "w",
    "cup": "mug",
    "two": "2",
    "digit-2": "2",
    "five": "5",
    "digit-5": "5",
    "letter-k": "k",
    "letter-s": "s",
    "check": "checkmark",
    "tick": "checkmark",
    "stairs": "staircase",
    "letter-i": "i",
    "three": "3",
    "digit-3": "3",
    "letter-v": "v",
    "barbell": "dumbbell",
    "four": "4",
    "digit-4": "4",
    "eight": "8",
    "digit-8": "8",
    "letter-l": "l",
    "one": "1",
    "digit-1": "1",
    "seven": "7",
    "digit-7": "7",
    "zero": "0",
    "digit-0": "0",
    "letter-u": "u",
    "letter-e": "e",
    "box": "square",
    "letter-y": "y",
    "six": "6",
    "digit-6": "6",
    "nine": "9",
    "digit-9": "9",
    "letter-f": "f",
    "o": "ring",
    "circle": "ring",
    "ship": "boat",
    "letter-a": "a",
}



def read_library_mask(path: Path) -> tuple[tuple[str, ...], dict[str, str]]:
    """Return ``(rows, headers)`` for a library mask file.

    Header lines are ``// key: value``; ``aliases`` is comma-separated.  Rows
    follow the candidate-file convention (``#`` filled, ``.`` empty, top first).
    """

    rows: list[str] = []
    headers: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//"):
            key, _, value = line[2:].partition(":")
            if value:
                headers[key.strip().lower()] = value.strip()
            continue
        rows.append(line.replace(" ", ""))
    if not rows:
        raise ValueError(f"{path}: empty mask")
    return tuple(rows), headers


def load_library(root: Path = LIBRARY_ROOT) -> tuple[dict[str, tuple[str, ...]], dict[str, str], dict[str, str]]:
    """Read ``<root>/<category>/<name>.txt`` into ``(patterns, aliases, categories)``.

    Sorted by category then name so the registry order is stable across
    machines.  Duplicate names or aliases (including against an existing
    pattern name) are errors: an alias must resolve to exactly one drawing.
    """

    patterns: dict[str, tuple[str, ...]] = {}
    aliases: dict[str, str] = {}
    categories: dict[str, str] = {}
    if not root.is_dir():
        return patterns, aliases, categories
    for path in sorted(root.glob("*/*.txt")):
        name = path.stem
        rows, headers = read_library_mask(path)
        if name in patterns:
            raise ValueError(f"duplicate library shape {name!r} at {path}")
        patterns[name] = rows
        categories[name] = path.parent.name
        for alias in headers.get("aliases", "").split(","):
            alias = alias.strip().lower().replace("_", "-").replace(" ", "-")
            if not alias or alias == name:
                continue
            if alias in aliases and aliases[alias] != name:
                raise ValueError(f"library alias {alias!r} claimed by both {aliases[alias]!r} and {name!r}")
            aliases[alias] = name
    return patterns, aliases, categories


_LIBRARY_PATTERNS, _LIBRARY_ALIASES, LIBRARY_CATEGORIES = load_library()
for _name in _LIBRARY_PATTERNS:
    if _name in _PATTERNS:
        raise ValueError(f"library shape {_name!r} shadows a hand-registered pattern")
for _alias, _name in _LIBRARY_ALIASES.items():
    if _alias in _PATTERNS or (_alias in _ALIASES and _ALIASES[_alias] != _name):
        raise ValueError(f"library alias {_alias!r} for {_name!r} collides with an existing registry name")
_PATTERNS.update(_LIBRARY_PATTERNS)
_ALIASES.update(_LIBRARY_ALIASES)
LIBRARY_NAMES = tuple(_LIBRARY_PATTERNS)

ICON_NAMES = tuple(_PATTERNS)
DEMO_NAMES = ("heart", "arrow", "lightning", "plus", "h", "t", "n")
REJECTED_NAMES = ("house", "fish", "star", "music-note", "key", "question-mark", "smiley")
# Registered by the 2026-09-19 exploration; every entry is an exact 27-cell
# shipped-roll target with a complete loose-passing plan (see docs/EXPLORATION-20260919.md).
EXPLORED_NAMES = tuple(name for name in ICON_NAMES if name not in DEMO_NAMES + REJECTED_NAMES)


def get_icon(name: str) -> PixelTarget:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    normalized = _ALIASES.get(normalized, normalized)
    try:
        rows = _PATTERNS[normalized]
    except KeyError as error:
        raise KeyError(f"unknown icon {name!r}; choose from {', '.join(ICON_NAMES)}") from error
    source = (
        "demo-family-certified"
        if normalized in {"arrow", "plus"}
        else "demo-curated-certified"
        if normalized == "lightning"
        else "parametric"
    )
    return PixelTarget(
        grid=parse_grid(rows),
        concept=normalized,
        caption=f"A flat pixel drawing of {normalized.replace('-', ' ')}",
        source=source,
    )


def icons() -> list[PixelTarget]:
    return [get_icon(name) for name in ICON_NAMES]
