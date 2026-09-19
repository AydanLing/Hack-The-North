"""Recognition-first demo targets with shipped-roll threading certificates.

These targets deliberately contain exactly 27 cells.  They are selected for
their silhouette rather than obtained by deforming a sparse reference drawing,
and each target has a checked integer-FK certificate for the shipped roll.
The certificates are geometric goals only; they still require fold planning
and mechanics checks before they can be presented as feasible plans.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import PixelTarget, parse_grid


@dataclass(frozen=True, slots=True)
class DemoIcon:
    """An exact demo silhouette and one shipped-roll threading certificate."""

    target: PixelTarget
    states: tuple[int, ...]
    base: int = 0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.target.cells) != 27:
            raise ValueError("demo targets must contain exactly 27 cells")
        if len(self.states) != 26 or any(state not in (-1, 0, 1) for state in self.states):
            raise ValueError("a demo certificate needs 26 physical states in {-1, 0, +1}")


# Recognition-first open right-arrow outline.  Two long shaft rails flow into
# a stepped chevron, keeping the point and negative space legible at cube
# resolution.  It was selected from 15,099 contour variants (68 exact shipped-
# roll threadings) and has a complete loose-passing fold route.
_ARROW_ROWS = (
    "....###...",
    "#####.####",
    ".........#",
    ".........#",
    ".......###",
    "#####.##..",
    "....###...",
)
_ARROW_STATES = (
    1, 0, 0, 0, 1, 1, 0, 1, -1, 0, 0, -1, 0,
    0, 1, 0, 1, -1, -1, -1, 0, -1, -1, 0, 0, 0,
)

# Clean thick cross selected by exhaustive review of the complete shipped-roll
# 8x8 and 7x9 flat families.  The mathematically perfect 8x8 cross-minus-one
# variants are roll-UNSAT; this target removes three boundary cells without an
# off-axis nub and has two independently found loose-passing fold orders.
_PLUS_ROWS = (
    "...##...",
    ".######.",
    ".#######",
    "########",
    "...##...",
    "...##...",
)
_PLUS_STATES = (
    0, 0, 0, 1, 0, 1, 1, 0, -1, 0, 0, -1, -1,
    1, 1, -1, -1, 0, 0, 0, -1, 1, 0, 0, -1, -1,
)

# Recognition-first classic bolt stroke.  This is an exact 27-cell simple path
# selected from 29,691 nearby zigzag silhouettes, not a deformed point-cloud
# match.  Its two sharp direction reversals remain legible at cube resolution.
_LIGHTNING_ROWS = (
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
)
_LIGHTNING_STATES = (
    1, 0, 1, 0, -1, 0, 1, -1, 1, 1, 0, -1, 0,
    0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 1,
)


DEMO_ICONS: dict[str, DemoIcon] = {
    "arrow": DemoIcon(
        PixelTarget(
            parse_grid(_ARROW_ROWS),
            concept="arrow",
            caption="An open flat right arrow with a long shaft and stepped chevron head",
            source="demo-family-certified",
        ),
        _ARROW_STATES,
        base=4,
        notes=(
            "recognition-first open-chevron outline",
            "15,099 contour variants searched; 68 exactly threadable",
            "complete loose-passing 23-move fold route",
            "render point-right",
        ),
    ),
    "lightning": DemoIcon(
        PixelTarget(
            parse_grid(_LIGHTNING_ROWS),
            concept="lightning",
            caption="A flat angular lightning bolt with alternating zigzag knees",
            source="demo-curated-certified",
        ),
        _LIGHTNING_STATES,
        base=6,
        notes=("recognition-first classic stroke", "29,691 silhouettes searched"),
    ),
    "plus": DemoIcon(
        PixelTarget(
            parse_grid(_PLUS_ROWS),
            concept="plus",
            caption="A bold flat plus sign with balanced thick arms",
            source="demo-family-certified",
        ),
        _PLUS_STATES,
        notes=(
            "recognition-first thick cross",
            "complete shipped-roll family search",
            "two loose-passing 22-move fold orders",
        ),
    ),
}

_ALIASES = {"bolt": "lightning", "lightning-bolt": "lightning"}
DEMO_ICON_NAMES = tuple(DEMO_ICONS)


def get_demo(name: str) -> DemoIcon:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    normalized = _ALIASES.get(normalized, normalized)
    try:
        return DEMO_ICONS[normalized]
    except KeyError as error:
        raise KeyError(
            f"unknown certified demo icon {name!r}; choose from {', '.join(DEMO_ICON_NAMES)}"
        ) from error


def get_demo_icon(name: str) -> PixelTarget:
    return get_demo(name).target


__all__ = ["DEMO_ICONS", "DEMO_ICON_NAMES", "DemoIcon", "get_demo", "get_demo_icon"]
