"""Glyph atlas: a vocabulary of flat concepts and count-aware mask generators.

Discovery needs *many* exact-27-cell masks per concept, because exact
shipped-roll threadability is rare and fixed bitmaps almost never land on 27
cells.  Every concept therefore carries several deterministic generators:

* **strokes** — polylines in the unit square rasterised at several box sizes
  with direction-aware thickness (a vertical stroke widens sideways, a
  horizontal one downwards), the way the shipped H and T are drawn;
* **bitmaps** — hand-authored seeds walked through a row/column size ladder;
* **runs** — compass-run templates for path-native shapes (zigzag, staircase,
  spiral); a self-avoiding 26-step run is automatically a 27-cell chain;
* **boundary perturbation** — every near-27 base mask is nudged to exactly 27
  by adding exterior cells with at least two neighbours or removing
  low-degree cells that are not articulation points.

The module is pure: numpy only, no I/O, no solver.  Determinism is by seed
and by ``sha256`` (never Python ``hash``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import itertools
import math
import random
from typing import Literal

import numpy as np

from ..shapes import articulation_components, canonical_planar, components, runs_to_cells, screen

Cell2 = tuple[int, int]
Category = Literal["letter", "digit", "symbol", "icon"]

DEFAULT_BOXES: tuple[tuple[int, int], ...] = (
    (5, 7), (6, 7), (7, 7), (6, 8), (7, 8), (8, 8), (5, 8), (5, 9), (6, 9), (7, 9), (4, 9), (8, 6),
)
MIN_BASE_CELLS = 23
MAX_BASE_CELLS = 31
TARGET_CELLS = 27


@dataclass(frozen=True, slots=True)
class Stroke:
    """A polyline in the unit square (x right, y up)."""

    points: tuple[tuple[float, float], ...]
    widths: tuple[int, ...] = (1, 2)
    optional: bool = False


@dataclass(frozen=True, slots=True)
class RunTemplate:
    """A compass-run template such as ``"E{a} N{b} W{a}"`` with integer ranges."""

    template: str
    ranges: Mapping[str, Sequence[int]]


@dataclass(frozen=True, slots=True)
class Glyph:
    concept: str
    aliases: tuple[str, ...]
    category: Category
    strokes: tuple[Stroke, ...] = ()
    bitmaps: tuple[tuple[str, ...], ...] = ()
    runs: tuple[RunTemplate, ...] = ()
    boxes: tuple[tuple[int, int], ...] = DEFAULT_BOXES
    filled: bool = False
    prefers_thick: bool = True
    holes: int | None = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Variant:
    """One exact-27-cell candidate mask for a concept."""

    concept: str
    rows: tuple[str, ...]
    ideal_rows: tuple[str, ...]
    generator: str
    mask_key: tuple[Cell2, ...]
    mask_hash: str

    @property
    def cells(self) -> tuple[tuple[int, int, int], ...]:
        return rows_to_cells(self.rows)


# --------------------------------------------------------------------------
# grid helpers


def rows_to_cells(rows: Sequence[str]) -> tuple[tuple[int, int, int], ...]:
    """Top-first rows to ``(x, y, 0)`` cells with y up (matches PixelTarget)."""

    height = len(rows)
    return tuple(
        (x, height - 1 - y, 0)
        for y, row in enumerate(rows)
        for x, char in enumerate(row)
        if char == "#"
    )


def cells_to_rows(cells: Iterable[Sequence[int]]) -> tuple[str, ...]:
    points = {(int(c[0]), int(c[1])) for c in cells}
    if not points:
        return ()
    min_x = min(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_x = max(x for x, _ in points)
    max_y = max(y for _, y in points)
    rows: list[str] = []
    for y in range(max_y, min_y - 1, -1):
        rows.append("".join("#" if (x, y) in points else "." for x in range(min_x, max_x + 1)))
    return tuple(rows)


def _neighbours(cell: Cell2) -> tuple[Cell2, Cell2, Cell2, Cell2]:
    x, y = cell
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def count_holes(points: Iterable[Cell2]) -> int:
    """Number of enclosed empty regions (4-connected background components)."""

    occupied = set(points)
    if not occupied:
        return 0
    min_x = min(x for x, _ in occupied) - 1
    max_x = max(x for x, _ in occupied) + 1
    min_y = min(y for _, y in occupied) - 1
    max_y = max(y for _, y in occupied) + 1
    seen: set[Cell2] = set()
    stack = [(min_x, min_y)]
    seen.add((min_x, min_y))
    while stack:
        x, y = stack.pop()
        for nxt in _neighbours((x, y)):
            if not (min_x <= nxt[0] <= max_x and min_y <= nxt[1] <= max_y):
                continue
            if nxt in occupied or nxt in seen:
                continue
            seen.add(nxt)
            stack.append(nxt)
    holes = 0
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            cell = (x, y)
            if cell in occupied or cell in seen:
                continue
            holes += 1
            stack = [cell]
            seen.add(cell)
            while stack:
                cx, cy = stack.pop()
                for nxt in _neighbours((cx, cy)):
                    if nxt in occupied or nxt in seen:
                        continue
                    if not (min_x <= nxt[0] <= max_x and min_y <= nxt[1] <= max_y):
                        continue
                    seen.add(nxt)
                    stack.append(nxt)
    return holes


def fill_holes(points: Iterable[Cell2]) -> set[Cell2]:
    occupied = set(points)
    if not occupied:
        return occupied
    min_x = min(x for x, _ in occupied) - 1
    max_x = max(x for x, _ in occupied) + 1
    min_y = min(y for _, y in occupied) - 1
    max_y = max(y for _, y in occupied) + 1
    outside: set[Cell2] = {(min_x, min_y)}
    stack = [(min_x, min_y)]
    while stack:
        x, y = stack.pop()
        for nxt in _neighbours((x, y)):
            if not (min_x <= nxt[0] <= max_x and min_y <= nxt[1] <= max_y):
                continue
            if nxt in occupied or nxt in outside:
                continue
            outside.add(nxt)
            stack.append(nxt)
    return {
        (x, y)
        for x in range(min_x + 1, max_x)
        for y in range(min_y + 1, max_y)
        if (x, y) not in outside
    }


def _connected(points: set[Cell2]) -> bool:
    return len(components([(x, y, 0) for x, y in points])) == 1


def mask_hash(key: tuple[Cell2, ...]) -> str:
    return hashlib.sha256(repr(key).encode()).hexdigest()[:24]


def canonical_key(points: Iterable[Cell2]) -> tuple[Cell2, ...]:
    return tuple(canonical_planar([(x, y, 0) for x, y in points]))


# --------------------------------------------------------------------------
# stroke rasterisation


def line_cells(start: Cell2, end: Cell2) -> list[Cell2]:
    """4-connected staircase line from ``start`` to ``end`` (inclusive)."""

    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    cells = [(x0, y0)]
    x, y = x0, y0
    err = dx - dy
    while (x, y) != (x1, y1):
        doubled = 2 * err
        moved_x = moved_y = False
        if doubled > -dy:
            err -= dy
            x += sx
            moved_x = True
        if doubled < dx:
            err += dx
            y += sy
            moved_y = True
        if moved_x and moved_y:
            # Insert the intermediate cell so the line stays face-connected.
            cells.append((x - sx, y))
        cells.append((x, y))
    return cells


def _segment_kind(start: Cell2, end: Cell2) -> str:
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dx > dy:
        return "horizontal"
    if dy > dx:
        return "vertical"
    return "diagonal"


def _thicken(cells: Sequence[Cell2], kind: str, width: int, box: tuple[int, int]) -> set[Cell2]:
    result = set(cells)
    if width <= 1:
        return result
    w, h = box
    for x, y in cells:
        if kind == "horizontal":
            extra = [(x, y - 1)] if y - 1 >= 0 else [(x, y + 1)]
        elif kind == "vertical":
            extra = [(x + 1, y)] if x + 1 < w else [(x - 1, y)]
        else:
            extra = [(x + 1, y) if x + 1 < w else (x - 1, y), (x, y - 1) if y - 1 >= 0 else (x, y + 1)]
        result.update(e for e in extra if 0 <= e[0] < w and 0 <= e[1] < h)
    return result


WIDTH_SCHEMES: dict[str, dict[str, int]] = {
    "thin": {"horizontal": 1, "vertical": 1, "diagonal": 1},
    "thick": {"horizontal": 2, "vertical": 2, "diagonal": 2},
    "v2": {"horizontal": 1, "vertical": 2, "diagonal": 1},
    "h2": {"horizontal": 2, "vertical": 1, "diagonal": 1},
    "hv2": {"horizontal": 2, "vertical": 2, "diagonal": 1},
}


def render_strokes(
    strokes: Sequence[Stroke],
    box: tuple[int, int],
    scheme: str,
    *,
    filled: bool = False,
) -> set[Cell2]:
    """Rasterise strokes into a ``box``-sized grid under a width scheme."""

    w, h = box
    widths = WIDTH_SCHEMES[scheme]
    result: set[Cell2] = set()
    for stroke in strokes:
        grid_points = [
            (int(round(px * (w - 1))), int(round(py * (h - 1)))) for px, py in stroke.points
        ]
        for start, end in zip(grid_points, grid_points[1:]):
            kind = _segment_kind(start, end)
            width = widths[kind]
            if width not in stroke.widths:
                width = max(v for v in stroke.widths if v <= width) if any(v <= width for v in stroke.widths) else min(stroke.widths)
            result.update(_thicken(line_cells(start, end), kind, width, box))
        if len(grid_points) == 1:
            result.add(grid_points[0])
    if filled:
        result = fill_holes(result)
    return result


# --------------------------------------------------------------------------
# base masks


def _bitmap_points(rows: Sequence[str]) -> set[Cell2]:
    return {(x, y) for x, y, _ in rows_to_cells(rows)}


def bitmap_ladder(rows: Sequence[str]) -> Iterator[tuple[str, tuple[str, ...]]]:
    """The seed plus every single row/column duplication or deletion."""

    grid = [list(row) for row in rows]
    height = len(grid)
    width = len(grid[0]) if grid else 0
    yield "seed", tuple("".join(row) for row in grid)
    for i in range(height):
        dup = grid[: i + 1] + [list(grid[i])] + grid[i + 1 :]
        yield f"row+{i}", tuple("".join(row) for row in dup)
        if height > 2:
            cut = grid[:i] + grid[i + 1 :]
            yield f"row-{i}", tuple("".join(row) for row in cut)
    for j in range(width):
        dup = [row[: j + 1] + [row[j]] + row[j + 1 :] for row in grid]
        yield f"col+{j}", tuple("".join(row) for row in dup)
        if width > 2:
            cut = [row[:j] + row[j + 1 :] for row in grid]
            yield f"col-{j}", tuple("".join(row) for row in cut)


def _expand_runs(template: RunTemplate) -> Iterator[tuple[str, set[Cell2]]]:
    names = list(template.ranges)
    for values in itertools.product(*(template.ranges[name] for name in names)):
        runs = template.template.format(**dict(zip(names, values)))
        try:
            cells = runs_to_cells(runs)
        except ValueError:
            continue
        if len(cells) != TARGET_CELLS or len(set(cells)) != TARGET_CELLS:
            continue
        yield runs, {(x, y) for x, y, _ in cells}


def base_masks(glyph: Glyph) -> Iterator[tuple[str, set[Cell2]]]:
    """Every base mask of a glyph with its generator tag (unfiltered by count)."""

    optional = [index for index, stroke in enumerate(glyph.strokes) if stroke.optional]
    for box in glyph.boxes:
        for scheme in WIDTH_SCHEMES:
            for dropped in range(len(optional) + 1):
                for drop in itertools.combinations(optional, dropped):
                    strokes = [s for i, s in enumerate(glyph.strokes) if i not in drop]
                    if not strokes:
                        continue
                    tag = f"strokes:{box[0]}x{box[1]}:{scheme}"
                    if drop:
                        tag += ":drop" + "".join(str(i) for i in drop)
                    yield tag, render_strokes(strokes, box, scheme, filled=glyph.filled)
    for index, rows in enumerate(glyph.bitmaps):
        for step, ladder_rows in bitmap_ladder(rows):
            yield f"bitmap{index}:{step}", _bitmap_points(ladder_rows)
    for template in glyph.runs:
        for runs, points in _expand_runs(template):
            yield f"runs:{runs}", points


# --------------------------------------------------------------------------
# perturbation to exactly 27 cells


def _degree(cell: Cell2, occupied: set[Cell2]) -> int:
    return sum(n in occupied for n in _neighbours(cell))


def _addable(occupied: set[Cell2], *, min_neighbours: int) -> list[Cell2]:
    exterior: set[Cell2] = set()
    for cell in occupied:
        exterior.update(n for n in _neighbours(cell) if n not in occupied)
    return sorted(c for c in exterior if _degree(c, occupied) >= min_neighbours)


def _removable(occupied: set[Cell2]) -> list[Cell2]:
    articulation = articulation_components([(x, y, 0) for x, y in occupied])
    return sorted(
        c for c in occupied if _degree(c, occupied) <= 2 and (c[0], c[1], 0) not in articulation
    )


def _sample_combinations(
    pool: Sequence[Cell2], size: int, cap: int, rng: random.Random
) -> Iterator[tuple[Cell2, ...]]:
    if size == 0:
        yield ()
        return
    if size > len(pool):
        return
    total = math.comb(len(pool), size)
    if total <= cap:
        yield from itertools.combinations(pool, size)
        return
    seen: set[tuple[Cell2, ...]] = set()
    attempts = 0
    while len(seen) < cap and attempts < cap * 20:
        attempts += 1
        combo = tuple(sorted(rng.sample(pool, size)))
        if combo in seen:
            continue
        seen.add(combo)
        yield combo


def perturb_to_target(
    occupied: set[Cell2],
    *,
    rng: random.Random,
    cap: int,
    expected_holes: int | None,
    allow_swaps: bool = True,
) -> Iterator[tuple[str, set[Cell2]]]:
    """Yield exact-27 masks near ``occupied`` that stay connected and legible."""

    delta = TARGET_CELLS - len(occupied)
    swaps = (0, 1) if abs(delta) <= 1 and allow_swaps else (0,)
    for extra in swaps:
        n_add = max(delta, 0) + extra
        n_remove = max(-delta, 0) + extra
        add_pool = _addable(occupied, min_neighbours=2)
        if n_add and math.comb(len(add_pool), n_add) < 4:
            add_pool = _addable(occupied, min_neighbours=1)
        remove_pool = _removable(occupied)
        budget = cap
        for removed in _sample_combinations(remove_pool, n_remove, cap, rng):
            after_remove = occupied - set(removed)
            if n_remove and not _connected(after_remove):
                continue
            if n_add:
                pool = [c for c in add_pool if c not in removed]
            else:
                pool = []
            for added in _sample_combinations(pool, n_add, max(1, budget), rng):
                variant = after_remove | set(added)
                if len(variant) != TARGET_CELLS or not _connected(variant):
                    continue
                if expected_holes is not None and count_holes(variant) != expected_holes:
                    continue
                # Cheap chain screens (checkerboard parity, endpoint count,
                # articulation) reject most random nudges; apply them here so
                # the thread cache only ever holds plausible chains.
                if not screen([(x, y, 0) for x, y in variant], TARGET_CELLS, include_hamiltonian=False).ok:
                    continue
                tag = f"{'+' if delta >= 0 else ''}{delta}"
                if extra:
                    tag += f"~{extra}"
                yield tag, variant
                budget -= 1
                if budget <= 0:
                    return


def _seed_for(concept: str, tag: str, seed: int) -> random.Random:
    digest = hashlib.sha256(f"{concept}|{tag}|{seed}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def variants(glyph: Glyph, *, seed: int = 0, max_per_base: int = 2000) -> Iterator[Variant]:
    """All exact-27 candidate masks of a glyph, deduplicated per concept."""

    seen: set[str] = set()
    for tag, points in base_masks(glyph):
        if not (MIN_BASE_CELLS <= len(points) <= MAX_BASE_CELLS) or not _connected(points):
            continue
        ideal_rows = cells_to_rows([(x, y, 0) for x, y in points])
        rng = _seed_for(glyph.concept, tag, seed)
        for delta_tag, variant in perturb_to_target(
            points,
            rng=rng,
            cap=max_per_base,
            expected_holes=glyph.holes,
            allow_swaps=not tag.startswith("runs:"),
        ):
            key = canonical_key(variant)
            digest = mask_hash(key)
            if digest in seen:
                continue
            seen.add(digest)
            yield Variant(
                concept=glyph.concept,
                rows=cells_to_rows([(x, y, 0) for x, y in variant]),
                ideal_rows=ideal_rows,
                generator=f"{tag}:{delta_tag}",
                mask_key=key,
                mask_hash=digest,
            )


# --------------------------------------------------------------------------
# the vocabulary


def _s(*points: tuple[float, float], widths: tuple[int, ...] = (1, 2), optional: bool = False) -> Stroke:
    return Stroke(tuple(points), widths, optional)


def _g(
    concept: str,
    category: Category,
    *strokes: Stroke,
    aliases: tuple[str, ...] = (),
    bitmaps: tuple[tuple[str, ...], ...] = (),
    runs: tuple[RunTemplate, ...] = (),
    boxes: tuple[tuple[int, int], ...] = DEFAULT_BOXES,
    filled: bool = False,
    prefers_thick: bool = True,
    holes: int | None = 0,
    notes: tuple[str, ...] = (),
) -> Glyph:
    return Glyph(
        concept=concept,
        aliases=tuple(dict.fromkeys((concept, *aliases))),
        category=category,
        strokes=tuple(strokes),
        bitmaps=bitmaps,
        runs=runs,
        boxes=boxes,
        filled=filled,
        prefers_thick=prefers_thick,
        holes=holes,
        notes=notes,
    )


_R = range
_STAIR = RunTemplate("E{a} N{b} E{a} N{b} E{a} N{b} E{c}", {"a": _R(1, 7), "b": _R(1, 7), "c": _R(1, 9)})
_STAIR4 = RunTemplate("E{a} N{b} E{a} N{b} E{a} N{b} E{a} N{c}", {"a": _R(1, 6), "b": _R(1, 6), "c": _R(1, 7)})
_STAIR5 = RunTemplate("N{a} E{b} N{a} E{b} N{a} E{b} N{a} E{b} N{a} E{c}", {"a": _R(1, 5), "b": _R(1, 5), "c": _R(1, 6)})
_ZIGZAG = RunTemplate("N{a} E{b} S{a} E{b} N{a} E{b} S{c}", {"a": _R(2, 9), "b": _R(1, 5), "c": _R(1, 9)})
_ZIGZAG5 = RunTemplate("N{a} E{b} S{a} E{b} N{a} E{b} S{a} E{b} N{c}", {"a": _R(2, 7), "b": _R(1, 4), "c": _R(1, 8)})
_SQUAREWAVE = RunTemplate("E{b} N{a} E{b} S{a} E{b} N{a} E{b} S{a} E{c}", {"a": _R(2, 8), "b": _R(1, 5), "c": _R(1, 6)})
_SPIRAL = RunTemplate("E{a} N{b} W{c} S{d} E{e} N{f} W{g}", {
    "a": _R(4, 9), "b": _R(3, 8), "c": _R(3, 8), "d": _R(2, 7), "e": _R(1, 6), "f": _R(1, 5), "g": _R(1, 4),
})
_SPIRAL6 = RunTemplate("E{a} N{b} W{c} S{d} E{e} N{f}", {
    "a": _R(4, 9), "b": _R(3, 8), "c": _R(3, 8), "d": _R(2, 7), "e": _R(1, 6), "f": _R(1, 5),
})
_HOOK = RunTemplate("N{a} E{b} S{c} W{d}", {"a": _R(6, 14), "b": _R(3, 9), "c": _R(3, 12), "d": _R(1, 6)})
_S_RUN = RunTemplate("W{a} S{b} E{a} S{b} W{a}", {"a": _R(4, 9), "b": _R(2, 6)})
_Z_RUN = RunTemplate("E{a} S{b} W{c} S{b} E{a}", {"a": _R(4, 9), "b": _R(1, 5), "c": _R(1, 9)})
_LIGHTNING = RunTemplate("S{a} W{b} S{c} E{d} S{e} W{f}", {
    "a": _R(3, 8), "b": _R(1, 4), "c": _R(2, 7), "d": _R(1, 5), "e": _R(2, 8), "f": _R(1, 4),
})

_SHIPPED_H = ("##....", "###.##", "###..#", "######", "##..##", "##..##", "##....")
_SHIPPED_T = (
    "##########", "##########", "......#...", "......#...", "......#...", "......#...",
    "......#...", "......#...", "......#...",
)
_SHIPPED_N = ("###..#", "#.##.#", "#..#.#", "#..#.#", "#..#.#", "#..#.#", "#..#.#", "#..###")
_SHIPPED_PLUS = ("...##...", ".######.", ".#######", "########", "...##...", "...##...")

GLYPHS: dict[str, Glyph] = {}


def _register(glyph: Glyph) -> None:
    if glyph.concept in GLYPHS:
        raise ValueError(f"duplicate glyph {glyph.concept!r}")
    GLYPHS[glyph.concept] = glyph


# letters -------------------------------------------------------------------
_register(_g("a", "letter", _s((0, 0), (0, 1), (1, 1), (1, 0)), _s((0, 0.45), (1, 0.45)), aliases=("letter a",), holes=1))
_register(_g("b", "letter", _s((0, 0), (0, 1), (0.85, 1), (0.85, 0.5), (0, 0.5)), _s((0.85, 0.5), (1, 0.5), (1, 0), (0, 0)), aliases=("letter b",), holes=2))
_register(_g("c", "letter", _s((1, 1), (0, 1), (0, 0), (1, 0)), aliases=("letter c", "bracket", "u")))
_register(_g("d", "letter", _s((0, 0), (0, 1), (0.7, 1), (1, 0.7), (1, 0.3), (0.7, 0), (0, 0)), aliases=("letter d",), holes=1))
_register(_g("e", "letter", _s((1, 1), (0, 1), (0, 0), (1, 0)), _s((0, 0.5), (0.7, 0.5)), aliases=("letter e",)))
_register(_g("f", "letter", _s((1, 1), (0, 1), (0, 0)), _s((0, 0.5), (0.75, 0.5)), aliases=("letter f",)))
_register(_g("g", "letter", _s((1, 1), (0, 1), (0, 0), (1, 0), (1, 0.45), (0.55, 0.45)), aliases=("letter g",)))
_register(_g("h", "letter", _s((0, 0), (0, 1)), _s((1, 0), (1, 1)), _s((0, 0.5), (1, 0.5)), aliases=("letter h",), bitmaps=(_SHIPPED_H,)))
_register(_g("i", "letter", _s((0, 1), (1, 1)), _s((0.5, 1), (0.5, 0)), _s((0, 0), (1, 0)), aliases=("letter i", "capital i", "beam")))
_register(_g("j", "letter", _s((0.2, 1), (1, 1)), _s((0.7, 1), (0.7, 0), (0, 0), (0, 0.35)), aliases=("letter j",)))
_register(_g("k", "letter", _s((0, 0), (0, 1)), _s((1, 1), (0, 0.5), (1, 0)), aliases=("letter k",)))
_register(_g("l", "letter", _s((0, 1), (0, 0), (1, 0)), aliases=("letter l", "corner", "right angle")))
_register(_g("m", "letter", _s((0, 0), (0, 1), (0.5, 0.5), (1, 1), (1, 0)), aliases=("letter m",)))
_register(_g("n", "letter", _s((0, 0), (0, 1), (1, 0), (1, 1)), aliases=("letter n",), bitmaps=(_SHIPPED_N,)))
_register(_g("o", "letter", _s((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)), aliases=("letter o", "ring", "square", "frame", "zero", "0", "circle", "loop", "rectangle"), holes=1))
_register(_g("p", "letter", _s((0, 0), (0, 1), (1, 1), (1, 0.5), (0, 0.5)), aliases=("letter p",), holes=1))
_register(_g("q", "letter", _s((0, 0.2), (0, 1), (1, 1), (1, 0.2), (0, 0.2)), _s((0.6, 0.45), (1, 0)), aliases=("letter q",), holes=1))
_register(_g("r", "letter", _s((0, 0), (0, 1), (1, 1), (1, 0.5), (0, 0.5)), _s((0.4, 0.5), (1, 0)), aliases=("letter r",), holes=1))
_register(_g("s", "letter", _s((1, 1), (0, 1), (0, 0.5), (1, 0.5), (1, 0), (0, 0)), aliases=("letter s", "5", "five"), runs=(_S_RUN,)))
_register(_g("t", "letter", _s((0, 1), (1, 1)), _s((0.5, 1), (0.5, 0)), aliases=("letter t", "cross"), bitmaps=(_SHIPPED_T,)))
_register(_g("u", "letter", _s((0, 1), (0, 0), (1, 0), (1, 1)), aliases=("letter u", "cup", "magnet", "horseshoe")))
_register(_g("v", "letter", _s((0, 1), (0.5, 0), (1, 1)), aliases=("letter v", "check", "tick")))
_register(_g("w", "letter", _s((0, 1), (0.25, 0), (0.5, 0.6), (0.75, 0), (1, 1)), aliases=("letter w",)))
_register(_g("x", "letter", _s((0, 1), (1, 0)), _s((0, 0), (1, 1)), aliases=("letter x", "cross", "x mark", "times", "multiply")))
_register(_g("y", "letter", _s((0, 1), (0.5, 0.5), (1, 1)), _s((0.5, 0.5), (0.5, 0)), aliases=("letter y", "fork", "slingshot")))
_register(_g("z", "letter", _s((0, 1), (1, 1), (0, 0), (1, 0)), aliases=("letter z", "zigzag", "2", "two"), runs=(_Z_RUN,)))

# digits --------------------------------------------------------------------
_register(_g("1", "digit", _s((0.15, 0.75), (0.5, 1), (0.5, 0)), _s((0.1, 0), (0.9, 0), optional=True), aliases=("one", "number one", "digit 1")))
_register(_g("2", "digit", _s((0, 1), (1, 1), (1, 0.5), (0, 0.5), (0, 0), (1, 0)), aliases=("two", "number two", "digit 2", "z")))
_register(_g("3", "digit", _s((0, 1), (1, 1), (1, 0), (0, 0)), _s((0.3, 0.5), (1, 0.5)), aliases=("three", "number three", "digit 3")))
_register(_g("4", "digit", _s((0, 1), (0, 0.45), (1, 0.45)), _s((0.7, 1), (0.7, 0)), aliases=("four", "number four", "digit 4")))
_register(_g("5", "digit", _s((1, 1), (0, 1), (0, 0.5), (1, 0.5), (1, 0), (0, 0)), aliases=("five", "number five", "digit 5", "s")))
_register(_g("6", "digit", _s((1, 1), (0, 1), (0, 0), (1, 0), (1, 0.5), (0, 0.5)), aliases=("six", "number six", "digit 6"), holes=1))
_register(_g("7", "digit", _s((0, 1), (1, 1), (0.4, 0)), aliases=("seven", "number seven", "digit 7")))
_register(_g("8", "digit", _s((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)), _s((0, 0.5), (1, 0.5)), aliases=("eight", "number eight", "digit 8"), holes=2))
_register(_g("9", "digit", _s((0, 0), (1, 0), (1, 1), (0, 1), (0, 0.5), (1, 0.5)), aliases=("nine", "number nine", "digit 9"), holes=1))

# symbols -------------------------------------------------------------------
_register(_g("plus", "symbol", _s((0.5, 0), (0.5, 1)), _s((0, 0.5), (1, 0.5)), aliases=("cross", "plus sign", "add", "medical cross", "first aid", "t", "x"), bitmaps=(_SHIPPED_PLUS,)))
_register(_g("heart", "icon", bitmaps=(
    (".##..##", "#######", "#######", "..####.", "..###..", "...##.."),
    (".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."),
    ("##..##", "######", "######", ".####.", "..##..", "..##.."),
), aliases=("love", "heart shape", "valentine"), holes=None))
_register(_g("hash", "symbol", _s((0.3, 0), (0.3, 1)), _s((0.7, 0), (0.7, 1)), _s((0, 0.3), (1, 0.3)), _s((0, 0.7), (1, 0.7)), aliases=("pound sign", "number sign", "grid", "hashtag", "tic tac toe"), holes=1, prefers_thick=False))
_register(_g("arrow-up", "symbol", _s((0.5, 0), (0.5, 1)), _s((0, 0.6), (0.5, 1), (1, 0.6)), aliases=("arrow", "up arrow", "arrow up", "arrow pointing up")))
_register(_g("arrow-down", "symbol", _s((0.5, 1), (0.5, 0)), _s((0, 0.4), (0.5, 0), (1, 0.4)), aliases=("arrow", "down arrow", "arrow down", "arrow pointing down")))
_register(_g("arrow-left", "symbol", _s((1, 0.5), (0, 0.5)), _s((0.4, 1), (0, 0.5), (0.4, 0)), aliases=("arrow", "left arrow", "arrow left", "arrow pointing left")))
_register(_g("check", "symbol", _s((0, 0.45), (0.35, 0), (1, 1)), aliases=("check mark", "tick", "checkmark", "v"), prefers_thick=False))
_register(_g("staircase", "symbol", runs=(_STAIR, _STAIR4, _STAIR5), aliases=("stairs", "steps", "stair", "step"), prefers_thick=False))
_register(_g("zigzag", "symbol", runs=(_ZIGZAG, _ZIGZAG5), aliases=("zig zag", "wave", "m", "w", "saw", "sawtooth", "lightning"), prefers_thick=False))
_register(_g("square-wave", "symbol", runs=(_SQUAREWAVE,), aliases=("wave", "square wave", "pulse", "battlements", "castle wall", "crenellation"), prefers_thick=False))
_register(_g("spiral", "symbol", runs=(_SPIRAL, _SPIRAL6), aliases=("swirl", "maze", "coil", "snail", "labyrinth"), prefers_thick=False))
_register(_g("hook", "symbol", runs=(_HOOK,), aliases=("j", "cane", "walking stick", "umbrella handle", "question mark"), prefers_thick=False))
_register(_g("diamond", "symbol", _s((0.5, 0), (0, 0.5), (0.5, 1), (1, 0.5), (0.5, 0)), aliases=("rhombus", "gem", "kite", "square"), holes=1))
_register(_g("triangle", "symbol", _s((0, 0), (1, 0), (0.5, 1), (0, 0)), aliases=("pyramid", "mountain", "delta", "warning sign"), holes=1))
_register(_g("pi", "symbol", _s((0, 1), (1, 1)), _s((0.2, 1), (0.2, 0)), _s((0.8, 1), (0.8, 0)), aliases=("pi symbol", "greek pi", "table", "gate", "torii", "goalpost", "n")))
_register(_g("omega", "symbol", _s((0, 0), (0.25, 0), (0.25, 0.3), (0, 0.65), (0.5, 1), (1, 0.65), (0.75, 0.3), (0.75, 0), (1, 0)), aliases=("ohm", "horseshoe", "greek omega", "magnet")))
_register(_g("infinity", "symbol", _s((0.5, 0.5), (0.25, 1), (0, 0.5), (0.25, 0), (0.5, 0.5), (0.75, 1), (1, 0.5), (0.75, 0), (0.5, 0.5)), aliases=("infinity sign", "figure eight", "8", "eight", "glasses", "bow", "bowtie"), holes=2, boxes=((7, 4), (8, 4), (9, 4), (9, 5), (8, 5), (10, 5), (11, 5))))
_register(_g("hourglass", "symbol", _s((0, 1), (1, 1), (0, 0), (1, 0), (0, 1)), aliases=("bowtie", "bow tie", "timer", "x", "sand timer"), holes=2))
_register(_g("flag", "symbol", _s((0, 0), (0, 1), (1, 1), (0.7, 0.7), (1, 0.4), (0, 0.4)), aliases=("banner", "pennant"), filled=True, holes=0))
_register(_g("ladder", "symbol", _s((0, 0), (0, 1)), _s((1, 0), (1, 1)), _s((0, 0.25), (1, 0.25)), _s((0, 0.5), (1, 0.5)), _s((0, 0.75), (1, 0.75)), aliases=("rungs", "railway", "train track", "track", "fence"), holes=2, prefers_thick=False))
_register(_g("house", "icon", bitmaps=(
    ("...#...", "..###..", ".#####.", "#######", "##...##", "##...##", "##...##"),
    ("...##...", "..####..", ".######.", "########", "##....##", "##....##", "##....##"),
    ("...#...", "..#.#..", ".#...#.", "#######", "#.....#", "#..#..#", "#######"),
), aliases=("home", "hut", "cabin", "building"), holes=None))
_register(_g("umbrella", "icon", bitmaps=(
    ("...#...", ".#####.", "#######", "#######", "...#...", "...#...", "..##..."),
    ("....#....", "..#####..", ".#######.", "#########", "....#....", "....#....", "....#....", "...##...."),
), aliases=("parasol", "brolly", "mushroom"), holes=None))
_register(_g("mushroom", "icon", bitmaps=(
    ("..####..", ".######.", "########", "########", "...##...", "...##...", "...##...", "...##..."),
    (".#####.", "#######", "#######", "..###..", "..###..", "..###.."),
), aliases=("toadstool", "umbrella", "tree"), holes=None))
_register(_g("chair", "icon", bitmaps=(
    ("##....", "##....", "##....", "######", "######", "#....#", "#....#", "#....#"),
    ("##.....", "##.....", "##.....", "#######", "#######", "##...##", "##...##"),
), aliases=("seat", "bench", "stool"), holes=None))
_register(_g("table", "icon", bitmaps=(
    ("#########", "#########", "##.....##", "##.....##", "##.....##", "##.....##"),
    ("##########", "##########", "##......##", "##......##", "##......##", "##......##"),
), aliases=("desk", "bench", "bridge", "gate", "pi", "n"), holes=None))
_register(_g("tree", "icon", bitmaps=(
    ("...#...", "..###..", ".#####.", "#######", "...#...", "...#...", "...#..."),
    ("...#...", "..###..", ".#####.", "..###..", ".#####.", "#######", "...#...", "...#..."),
    ("...##...", "..####..", ".######.", "########", "...##...", "...##...", "...##..."),
), aliases=("pine", "pine tree", "christmas tree", "fir", "arrow"), holes=None))
_register(_g("rocket", "icon", bitmaps=(
    ("...#...", "..###..", "..###..", "..###..", "..###..", ".#####.", "#..#..#", "...#..."),
    ("..#..", ".###.", ".###.", ".###.", ".###.", "#####", "#.#.#", "..#.."),
), aliases=("missile", "spaceship", "space shuttle", "pencil", "arrow"), holes=None))
_register(_g("boat", "icon", bitmaps=(
    ("....#....", "....##...", "....###..", "....####.", "....#....", "#########", ".#######."),
    ("...#....", "...##...", "...###..", "...####.", "########", ".######."),
), aliases=("ship", "sailboat", "sailing boat", "yacht"), holes=None))
_register(_g("plane", "icon", bitmaps=(
    ("....#....", "....#....", "....#....", "#########", "....#....", "....#....", "..#####.."),
    ("...##...", "...##...", "########", "########", "...##...", "..####.."),
), aliases=("airplane", "aeroplane", "aircraft", "jet", "cross", "dagger", "sword"), holes=None))
_register(_g("fish", "icon", bitmaps=(
    ("..####..#", ".#....#.#", "#......##", "#......##", ".#....#.#", "..####..#"),
    ("..###...#", ".#####.##", "#########", ".#####.##", "..###...#"),
    ("......#.", "..###..#", ".#...###", "#.....##", ".#...###", "..###..#", "......#."),
), aliases=("goldfish", "shark"), holes=None))
_register(_g("lightning", "icon", bitmaps=(
    ("......#", "......#", "....###", "....#..", "...##..", "..##...", "..#....", "..#####", "......#", "...####", "...#...", ".###...", "##....."),
    ("....##", "...##.", "..##..", ".#####", "....#.", "...#..", "..#...", ".#....", "#....."),
), runs=(_LIGHTNING,), aliases=("lightning bolt", "bolt", "thunderbolt", "flash", "zigzag"), holes=None, prefers_thick=False))
_register(_g("cat", "icon", bitmaps=(
    ("#.....#", "##...##", "#######", "#.#.#.#", "#######", "#.###.#", ".#####."),
    ("#....#", "##..##", "######", "#.##.#", "######", ".####."),
), aliases=("cat face", "kitten", "fox", "owl"), holes=None))
_register(_g("bird", "icon", bitmaps=(
    ("..##....", ".####...", "#..#####", "...####.", "...###..", "....#...", "...###.."),
    ("##.....", ".##....", "..##.##", "...###.", "..####.", ".#####.", "..###.."),
), aliases=("duck", "chick", "penguin", "dove"), holes=None))
_register(_g("thumbs-up", "icon", bitmaps=(
    ("....#..", "....#..", "...##..", "..###..", "#######", "#.#####", "#.#####", "#######"),
), aliases=("thumb", "like", "hand", "fist"), holes=None))
_register(_g("dog", "icon", bitmaps=(
    ("#......", "##.####", ".#####.", ".#####.", ".#...#.", ".#...#."),
    ("..#....", "..#####", ".######", "#.#####", "..#...#", "..#...#"),
), aliases=("puppy", "hound", "animal", "horse"), holes=None))
_register(_g("crown", "symbol", bitmaps=(
    ("#.#.#.#", "#######", "#######", "#######"),
    ("#..#..#", "##.#.##", "#######", "#######", "#######"),
    ("#..#..#", "#.###.#", "#######", "#######", "#######", ".#####."),
), aliases=("king", "tiara", "castle", "crown"), holes=None))
_register(_g("anchor", "icon", bitmaps=(
    ("..###..", "..#.#..", "..###..", "...#...", ".#####.", "...#...", "#..#..#", "##.#.##", ".#####."),
    ("..###..", "..#.#..", "..###..", "...#...", "...#...", "#..#..#", "##.#.##", ".#####."),
), aliases=("ship anchor", "boat anchor"), holes=None))
_register(_g("smiley", "icon", bitmaps=(
    ("#######", "##...##", "#.....#", "##...##", "#.###.#", "#######"),
    ("#######", "#.....#", "##...##", "#.....#", "##...##", "#.###.#", "#######"),
    (".#####.", "##...##", "##...##", "#.....#", "##...##", "#.###.#", ".#####."),
), aliases=("smiley face", "smile", "face", "happy face", "emoji"), holes=None))
_register(_g("star", "icon", bitmaps=(
    ("...#...", "...#...", "..###..", "#######", ".#####.", "..###..", ".##.##.", ".#...#."),
    ("...#...", "..###..", "#######", ".#####.", "..###..", ".##.##.", "##...##"),
), aliases=("five pointed star", "starfish", "sheriff badge"), holes=None))
_register(_g("music-note", "icon", bitmaps=(
    ("....###", "....###", "....#.#", "....#..", "....#..", "....#..", "..###..", ".####..", ".####..", "..##..."),
    ("...###", "...###", "...#..", "...#..", "...#..", "...#..", ".###..", "####..", "####..", ".##..."),
), aliases=("note", "music note", "musical note", "quaver", "eighth note"), holes=None))
_register(_g("key", "icon", bitmaps=(
    (".###......", "##.##.....", "##.#######", "##.##.#.##", ".###......"),
    (".###.....", "#...#....", "#...#####", "#...#.#.#", ".###....."),
), aliases=("door key", "house key"), holes=None))
_register(_g("mug", "icon", bitmaps=(
    ("######.", "#....##", "#....##", "#....##", "#....##", "######."),
    ("######.", "#....##", "#....##", "#....##", "#....#.", "######."),
    ("#####..", "#####.#", "#####.#", "#####.#", "######.", "#####.."),
), aliases=("cup", "coffee", "coffee cup", "beer", "tea", "jug", "pitcher", "d"), holes=None))
_register(_g("car", "icon", bitmaps=(
    ("..#####..", ".##...##.", "#########", "#########", ".##...##."),
    ("..####..", ".##..##.", "########", "########", ".##..##."),
    ("..####..", ".#....#.", "########", "########", "##....##"),
), aliases=("automobile", "vehicle", "truck", "bus", "van"), holes=None))


GLYPH_NAMES = tuple(GLYPHS)


def get_glyph(name: str) -> Glyph:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    try:
        return GLYPHS[normalized]
    except KeyError as error:
        raise KeyError(f"unknown glyph {name!r}; choose from {', '.join(GLYPH_NAMES)}") from error


def select_glyphs(
    names: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
) -> list[Glyph]:
    chosen = [get_glyph(n) for n in names] if names else list(GLYPHS.values())
    if categories:
        wanted = {c.lower() for c in categories}
        chosen = [g for g in chosen if g.category in wanted]
    return chosen


__all__ = [
    "DEFAULT_BOXES",
    "GLYPHS",
    "GLYPH_NAMES",
    "Glyph",
    "RunTemplate",
    "Stroke",
    "TARGET_CELLS",
    "Variant",
    "WIDTH_SCHEMES",
    "base_masks",
    "bitmap_ladder",
    "canonical_key",
    "cells_to_rows",
    "count_holes",
    "fill_holes",
    "get_glyph",
    "line_cells",
    "mask_hash",
    "perturb_to_target",
    "render_strokes",
    "rows_to_cells",
    "select_glyphs",
    "variants",
]
