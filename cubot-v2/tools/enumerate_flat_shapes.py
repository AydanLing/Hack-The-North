#!/usr/bin/env python3
"""Enumerate every flat shape the chain can actually be, then rank them.

Mask-first discovery draws a shape and asks whether the chain can be it.  Most
hand-drawn masks lose, and they lose for reasons that have nothing to do with
search effort: disconnected regions, checkerboard parity, no Hamiltonian path,
or a footprint the roll word cannot thread.  The last n17 campaign converted
22 of 69 masks for exactly those reasons.

This goes the other way.  It walks the real chain -- ``lattice.DIRS`` for the
step and ``lattice.POST`` for the roll update, the same tables ``fk`` uses --
in-plane from every start orientation, and records the footprint it lands on.
Everything it emits is therefore threadable by construction, because the walk
*is* a threading.  The only question left is whether the fold search can reach
it, which is what ``explore_shape.py`` answers.

Footprints are deduplicated up to rotation, mirror and translation, then ranked
so the shapes a person would recognise float to the top: compact, well-filled
bounding boxes with some symmetry, rather than long wandering snakes.

    python tools/enumerate_flat_shapes.py --machine config/machine-17.toml --top 40
    python tools/enumerate_flat_shapes.py --machine config/machine-17.toml \
        --out data/candidates/n17-enum --top 60
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine  # noqa: E402
from cubot.lattice import DIRS, POST  # noqa: E402
from cubot.shapes import canonical_planar  # noqa: E402

Cell2 = tuple[int, int]


def to_cells3(cells: set[Cell2]) -> tuple[tuple[int, int, int], ...]:
    """Image coordinates (y down) to lattice coordinates (y up)."""
    height = max(y for _, y in cells) + 1
    return tuple((x, height - 1 - y, 0) for x, y in sorted(cells))


def enumerate_footprints(modules: int, roll: str, *, span: int,
                         node_cap: int, orientations: int) -> tuple[dict, int, bool]:
    """Walk the chain in-plane and collect distinct footprints.

    Returns ``(footprints, nodes, capped)`` where ``footprints`` maps a
    canonical key to one representative cell set.
    """
    roll_digits = [int(c) for c in roll]
    found: dict[tuple, frozenset] = {}
    nodes = 0
    capped = False
    # Keep the walk inside a box so the grid stays finite. A chain of N modules
    # cannot reach further than N cells from its start in any direction.
    lo, hi = -span, span

    sys.setrecursionlimit(10_000)

    def dfs(cell: Cell2, orientation: int, joint: int,
            visited: set[Cell2], path: list[Cell2]) -> None:
        nonlocal nodes, capped
        if capped:
            return
        nodes += 1
        if nodes > node_cap:
            capped = True
            return
        if len(path) == modules:
            found.setdefault(canonical_planar(to_cells3(set(path))), frozenset(path))
            return
        for state in (0, 1, 2):
            direction = DIRS[orientation, state]
            if direction[2] != 0:
                continue  # leaves the plane; this tool only wants flat shapes
            nxt = (cell[0] + int(direction[0]), cell[1] - int(direction[1]))
            if not (lo <= nxt[0] <= hi and lo <= nxt[1] <= hi):
                continue
            if nxt in visited:
                continue  # self-intersection: two modules cannot share a cell
            visited.add(nxt)
            path.append(nxt)
            dfs(nxt, int(POST[orientation, state, roll_digits[joint]]),
                joint + 1, visited, path)
            path.pop()
            visited.discard(nxt)
            if capped:
                return

    for orientation in range(orientations):
        start = (0, 0)
        dfs(start, orientation, 0, {start}, [start])
        if capped:
            break
    return found, nodes, capped


def normalise(cells: frozenset) -> tuple[list[str], int, int]:
    """Render a footprint as top-first ASCII rows, trimmed to its bounding box."""
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    grid = [["." for _ in range(w)] for _ in range(h)]
    for x, y in cells:
        grid[y - y0][x - x0] = "#"
    return ["".join(row) for row in grid], w, h


def score(cells: frozenset) -> dict:
    """Rank recognisability: compact, well-filled, symmetric shapes first.

    A 17-cell footprint that fills most of a squarish box reads as a *shape*;
    one that fills 17 cells of a 1x17 box reads as a line. Symmetry is what
    makes people name something, so it is worth real weight.
    """
    rows, w, h = normalise(cells)
    filled = {(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"}
    area = w * h
    fill = len(filled) / area
    aspect = min(w, h) / max(w, h)

    mirror_v = sum((w - 1 - x, y) in filled for x, y in filled) / len(filled)
    mirror_h = sum((x, h - 1 - y) in filled for x, y in filled) / len(filled)
    rot180 = sum((w - 1 - x, h - 1 - y) in filled for x, y in filled) / len(filled)
    symmetry = max(mirror_v, mirror_h, rot180)

    # Holes read as deliberate structure (rings, letters like A/O), so reward them.
    holes = enclosed_holes(filled, w, h)

    interest = (0.40 * fill + 0.25 * aspect + 0.25 * symmetry + 0.10 * min(holes, 2) / 2)
    return {"w": w, "h": h, "fill": fill, "aspect": aspect,
            "symmetry": symmetry, "holes": holes, "interest": interest}


def enclosed_holes(filled: set[Cell2], w: int, h: int) -> int:
    """Count empty regions fully enclosed by the footprint."""
    empty = {(x, y) for y in range(h) for x in range(w)} - filled
    seen: set[Cell2] = set()
    holes = 0
    for cell in empty:
        if cell in seen:
            continue
        stack, region, touches_edge = [cell], [], False
        seen.add(cell)
        while stack:
            cx, cy = stack.pop()
            region.append((cx, cy))
            if cx in (0, w - 1) or cy in (0, h - 1):
                touches_edge = True
            for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                if (nx, ny) in empty and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        if not touches_edge:
            holes += 1
    return holes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--machine", default="config/machine-17.toml")
    ap.add_argument("--span", type=int, default=9,
                    help="half-width of the walk box in cells")
    ap.add_argument("--node-cap", type=int, default=4_000_000)
    ap.add_argument("--orientations", type=int, default=24,
                    help="start orientations to walk (24 = all)")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--min-fill", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=None,
                    help="write ranked masks as <out>/enum-NNN.txt")
    ap.add_argument("--dump", type=Path, default=None,
                    help="write EVERY footprint as JSONL for later matching")
    args = ap.parse_args()

    machine = load_machine(args.machine)
    print(f"walking {machine.modules} modules, roll {machine.roll} "
          f"(box +-{args.span}, cap {args.node_cap:,} nodes)")

    found, nodes, capped = enumerate_footprints(
        machine.modules, machine.roll, span=args.span,
        node_cap=args.node_cap, orientations=args.orientations)
    print(f"  {nodes:,} nodes, {len(found):,} distinct flat footprints"
          + (" (NODE CAP HIT — results partial)" if capped else ""))
    if not found:
        return 1

    if args.dump:
        import json
        args.dump.parent.mkdir(parents=True, exist_ok=True)
        with args.dump.open("w") as fh:
            for cells in found.values():
                rows, w, h = normalise(cells)
                fh.write(json.dumps({"rows": rows, "w": w, "h": h}) + "\n")
        print(f"  dumped {len(found):,} footprints to {args.dump}")

    ranked = sorted(found.values(), key=lambda c: -score(c)["interest"])
    ranked = [c for c in ranked if score(c)["fill"] >= args.min_fill]

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    print(f"\ntop {min(args.top, len(ranked))} by recognisability:")
    for i, cells in enumerate(ranked[:args.top]):
        s = score(cells)
        rows, _, _ = normalise(cells)
        print(f"\n#{i:03d}  {s['w']}x{s['h']}  fill {s['fill']:.2f}  "
              f"aspect {s['aspect']:.2f}  sym {s['symmetry']:.2f}  "
              f"holes {s['holes']}  score {s['interest']:.3f}")
        for row in rows:
            print(f"      {row}")
        if args.out:
            dest = args.out / f"enum-{i:03d}.txt"
            dest.write_text("\n".join(rows) + "\n")
    if args.out:
        print(f"\nwrote {min(args.top, len(ranked))} masks to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
