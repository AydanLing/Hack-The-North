"""Deterministic, offline target drawings for the icon-first phase."""

from __future__ import annotations

from .base import PixelTarget, parse_grid


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
}

ICON_NAMES = tuple(_PATTERNS)
DEMO_NAMES = ("heart", "arrow", "lightning", "plus", "h", "t", "n")


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
