#!/usr/bin/env python3
"""Name the shapes the chain can actually make, instead of hoping a mask fits.

``enumerate_flat_shapes.py`` produces every flat footprint the 17-module chain
can be.  This scores that feasible set against ideal glyph templates and reports
the best real footprint for each concept, with an overlap number attached.

That number is the point.  The shipped n17 library was named aspirationally --
its "zigzag" turns once and its "triangle" has no sloped sides -- because
nothing ever compared the folded shape to the idea.  Here a concept only earns
its name if some reachable footprint actually scores well against it.

Overlap is intersection-over-union, maximised over the 8 rotations/mirrors of
the footprint and over small translations, so orientation and framing do not
matter.  Templates do not need the same cell count as the chain: IoU handles the
size difference, and a template that no 17-cell footprint can cover simply
scores low, which is the honest answer.

    python tools/match_glyphs.py out/n17-enum/footprints.jsonl
    python tools/match_glyphs.py out/n17-enum/footprints.jsonl --only heart plus --top 3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Ideal glyphs, drawn as they should look. Cell counts vary on purpose; IoU
# compares them fairly against the chain's fixed 17 cells.
TEMPLATES: dict[str, str] = {
    "heart": """
.##.##.
#######
#######
.#####.
..###..
...#...
""",
    "plus": """
..#..
..#..
#####
..#..
..#..
""",
    "cross-x": """
#...#
.#.#.
..#..
.#.#.
#...#
""",
    "T": """
#####
..#..
..#..
..#..
..#..
""",
    "L": """
#....
#....
#....
#....
#####
""",
    "U": """
#...#
#...#
#...#
#...#
#####
""",
    "C": """
#####
#....
#....
#....
#####
""",
    "O-ring": """
#####
#...#
#...#
#...#
#####
""",
    "H": """
#...#
#...#
#####
#...#
#...#
""",
    "E": """
#####
#....
####.
#....
#####
""",
    "S": """
#####
#....
#####
....#
#####
""",
    "Z-zigzag": """
#####
...#.
..#..
.#...
#####
""",
    "arrow-up": """
..#..
.###.
#####
..#..
..#..
""",
    "diamond": """
..#..
.###.
#####
.###.
..#..
""",
    "triangle": """
....#....
...###...
..#####..
.#######.
#########
""",
    "square-ring": """
####
#..#
#..#
####
""",
    "F": """
#####
#....
####.
#....
#....
""",
    "I-bar": """
#####
..#..
..#..
..#..
#####
""",
    "stairs": """
....##
...##.
..##..
.##...
##....
""",
    "smiley": """
#.....#
.......
#.....#
.......
#.....#
.#####.
""",
    # The chain is a 17-cell snake, so it draws outlines rather than solid
    # glyphs. These are stroke-form letters and digits: one cell thick, which is
    # the only way a single closed path can render them.
    "A": """
.###.
#...#
#####
#...#
#...#
""",
    "B": """
####.
#...#
####.
#...#
####.
""",
    "D": """
####.
#...#
#...#
#...#
####.
""",
    "G": """
#####
#....
#..##
#...#
#####
""",
    "J": """
..###
....#
....#
#...#
.###.
""",
    "N": """
#...#
##..#
#.#.#
#..##
#...#
""",
    "P": """
####.
#...#
####.
#....
#....
""",
    "V": """
#...#
#...#
#...#
.#.#.
..#..
""",
    "Y": """
#...#
.#.#.
..#..
..#..
..#..
""",
    "0": """
.###.
#...#
#...#
#...#
.###.
""",
    "2": """
####.
....#
.###.
#....
#####
""",
    "3": """
####.
....#
.###.
....#
####.
""",
    "4": """
#..#.
#..#.
#####
...#.
...#.
""",
    "7": """
#####
....#
...#.
..#..
.#...
""",
    "step": """
..###
..#..
###..
#....
""",
    "hook": """
#####
....#
....#
.####
""",
    "spiral": """
#####
....#
.##.#
.#..#
.####
""",
    "bracket": """
###
#..
#..
#..
###
""",
}

CANVAS = 24


def parse_rows(block: str) -> list[str]:
    return [r for r in (line.strip() for line in block.strip().splitlines()) if r]


def cells_of(rows: list[str]) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"}


def transforms(cells: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """The 8 dihedral variants, each normalised so its bounding box starts at 0."""
    out = []
    cur = set(cells)
    for _ in range(4):
        cur = {(y, -x) for x, y in cur}          # rotate 90
        for variant in (cur, {(-x, y) for x, y in cur}):   # and its mirror
            xs = [p[0] for p in variant]
            ys = [p[1] for p in variant]
            out.append({(x - min(xs), y - min(ys)) for x, y in variant})
    # Deduplicate: symmetric shapes collapse to fewer than 8 distinct variants.
    unique, seen = [], set()
    for v in out:
        key = frozenset(v)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def mask_of(cells: set[tuple[int, int]], dx: int = 0, dy: int = 0) -> int:
    m = 0
    for x, y in cells:
        m |= 1 << ((y + dy) * CANVAS + (x + dx))
    return m


def dims(cells: set[tuple[int, int]]) -> tuple[int, int]:
    xs = [p[0] for p in cells]
    ys = [p[1] for p in cells]
    return max(xs) + 1, max(ys) + 1


GRID = 12


def rescale(cells: set[tuple[int, int]], n: int = GRID) -> set[tuple[int, int]]:
    """Resample a footprint onto an n x n grid, so size stops mattering.

    A chain of 17 modules draws strokes: its "Z" is 8 wide and 3 tall, while an
    ideal Z template is drawn square.  Comparing those directly scores a correct
    shape as a mismatch, because the penalty is aspect ratio rather than form.
    Normalising both to the same grid asks the question we actually care about --
    is this the same figure -- and leaves scale out of it.
    """
    xs = [p[0] for p in cells]
    ys = [p[1] for p in cells]
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    out = set()
    for x, y in cells:
        fx = (x - min(xs)) / w
        fy = (y - min(ys)) / h
        # Paint the whole cell's extent so thin strokes survive upsampling.
        for gx in range(int(fx * n), max(int(fx * n) + 1, int((x - min(xs) + 1) / w * n))):
            for gy in range(int(fy * n), max(int(fy * n) + 1, int((y - min(ys) + 1) / h * n))):
                if 0 <= gx < n and 0 <= gy < n:
                    out.add((gx, gy))
    return out


def aspect(cells: set[tuple[int, int]]) -> float:
    xs = [p[0] for p in cells]
    ys = [p[1] for p in cells]
    return (max(xs) - min(xs) + 1) / (max(ys) - min(ys) + 1)


def scaled_iou(footprint: set[tuple[int, int]], template: set[tuple[int, int]]) -> float:
    """Scale-tolerant IoU over the 8 dihedral variants, discounted by distortion.

    Normalising to a common grid alone is too forgiving: a straight 1x17 line
    stretches into a solid block and then matches almost anything.  So each
    variant's overlap is discounted by how much the aspect ratio had to be
    distorted to get there, which keeps a squashed-but-real Z scoring well while
    rejecting degenerate lines.
    """
    t = rescale(template)
    ta = aspect(template)
    best = 0.0
    for variant in transforms(footprint):
        v = rescale(variant)
        inter = len(v & t)
        if not inter:
            continue
        iou = inter / len(v | t)
        va = aspect(variant)
        distortion = max(va / ta, ta / va)
        best = max(best, iou / distortion ** 0.5)
    return best


def best_iou(footprint: set[tuple[int, int]], tmpl_mask: int, tmpl_dims: tuple[int, int],
             slack: int = 2) -> float:
    """Best IoU over the footprint's 8 variants and small translations."""
    tw, th = tmpl_dims
    best = 0.0
    for variant in transforms(footprint):
        vw, vh = dims(variant)
        # Skip variants whose framing cannot line up with the template at all.
        if abs(vw - tw) > slack + 2 or abs(vh - th) > slack + 2:
            continue
        for dx in range(-slack, slack + 1):
            for dy in range(-slack, slack + 1):
                if dx < 0 or dy < 0:
                    # Negative offsets would wrap on the bit canvas; shift the
                    # template instead by offsetting the variant positively.
                    continue
                vm = mask_of(variant, dx, dy)
                inter = (vm & tmpl_mask).bit_count()
                if not inter:
                    continue
                union = (vm | tmpl_mask).bit_count()
                best = max(best, inter / union)
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("footprints", type=Path)
    ap.add_argument("--only", nargs="*", default=None, help="limit to these concepts")
    ap.add_argument("--top", type=int, default=1, help="best N footprints per concept")
    ap.add_argument("--out", type=Path, default=None,
                    help="write winners as <out>/<concept>-enum.txt")
    args = ap.parse_args()

    pool = []
    with args.footprints.open() as fh:
        for line in fh:
            rows = json.loads(line)["rows"]
            pool.append(rows)
    print(f"{len(pool):,} reachable footprints loaded from {args.footprints}")

    names = args.only or list(TEMPLATES)
    prepared = {}
    for name in names:
        t = cells_of(parse_rows(TEMPLATES[name]))
        # Normalise the template to the canvas with a small margin so the
        # footprint can be nudged around it without wrapping.
        t = {(x + 2, y + 2) for x, y in t}
        prepared[name] = (mask_of(t), dims(t), len(t))

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    print(f"\n{'concept':12} {'IoU':>5}  best reachable footprint")
    print("-" * 64)
    results = {}
    for name in names:
        tmpl_mask, tmpl_dims, tmpl_n = prepared[name]
        scored = []
        for rows in pool:
            fp = cells_of(rows)
            iou = best_iou(fp, tmpl_mask, tmpl_dims)
            if iou > 0:
                scored.append((iou, rows))
        scored.sort(key=lambda e: -e[0])
        results[name] = scored[:args.top]
        if not scored:
            print(f"{name:12} {'—':>5}  no reachable footprint lines up")
            continue
        for rank, (iou, rows) in enumerate(scored[:args.top]):
            tag = name if rank == 0 else ""
            print(f"{tag:12} {iou:5.2f}  {rows[0]}")
            for r in rows[1:]:
                print(f"{'':12} {'':5}  {r}")
            print()
            if args.out and rank == 0:
                (args.out / f"{name}-enum.txt").write_text("\n".join(rows) + "\n")
    if args.out:
        print(f"wrote winners to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
