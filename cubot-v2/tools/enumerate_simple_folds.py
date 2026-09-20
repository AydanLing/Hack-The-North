#!/usr/bin/env python3
"""Enumerate the shapes reachable in only a few folds, cheapest first.

A booth demo wants shapes that are quick and legible, not shapes that happen to
be drawable.  A goal whose joints are off-zero in ``k`` places needs at least
``k`` detents, so "few folds" is literally "few non-zero joints" -- a space
small enough to enumerate exhaustively rather than search.

For each fold budget k this walks every choice of which k joints move and which
way, runs the real forward kinematics (``lattice.fk``), and keeps the
configurations that are physically sensible: flat, so the silhouette reads from
above, and self-avoiding, so no two modules want the same cell.  Footprints are
deduplicated up to rotation and mirror, and each distinct shape is reported at
the smallest k that achieves it.

Nothing here is certified: reachability still has to come from the fold search.
But every entry is a real chain configuration, which is more than a hand-drawn
mask can claim.

    python tools/enumerate_simple_folds.py --machine config/machine-17.toml --max-folds 5
    python tools/enumerate_simple_folds.py --machine config/machine-17.toml --max-folds 6 \
        --out data/candidates/n17-simple
"""
from __future__ import annotations

import argparse
from itertools import combinations, product
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine  # noqa: E402
from cubot.lattice import fk  # noqa: E402
from cubot.shapes import canonical_planar  # noqa: E402


def flat_axis(cells) -> int | None:
    """Return the axis (0,1,2) that is constant, or None when the shape is 3D."""
    for axis in (2, 1, 0):
        if len({c[axis] for c in cells}) == 1:
            return axis
    return None


def rows_of(cells, flat: int) -> list[str]:
    """Render the footprint as top-first ASCII, dropping the constant axis."""
    keep = [a for a in (0, 1, 2) if a != flat]
    pts = {(c[keep[0]], c[keep[1]]) for c in cells}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    grid = [["." for _ in range(max(xs) - min(xs) + 1)]
            for _ in range(max(ys) - min(ys) + 1)]
    for x, y in pts:
        grid[max(ys) - y][x - min(xs)] = "#"
    return ["".join(r) for r in grid]


def interest(rows: list[str]) -> float:
    """Favour compact, well-filled, symmetric footprints over wandering lines."""
    filled = {(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c == "#"}
    h, w = len(rows), len(rows[0])
    fill = len(filled) / (w * h)
    aspect = min(w, h) / max(w, h)
    mv = sum((w - 1 - x, y) in filled for x, y in filled) / len(filled)
    mh = sum((x, h - 1 - y) in filled for x, y in filled) / len(filled)
    return 0.45 * fill + 0.25 * aspect + 0.30 * max(mv, mh)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--machine", default="config/machine-17.toml")
    ap.add_argument("--max-folds", type=int, default=5)
    ap.add_argument("--min-fill", type=float, default=0.0,
                   help="drop footprints sparser than this (1.0 = solid box)")
    ap.add_argument("--per-k", type=int, default=12, help="how many to show per fold count")
    ap.add_argument("--out", type=Path, default=None,
                   help="write masks as <out>/k<K>-NN.txt")
    args = ap.parse_args()

    machine = load_machine(args.machine)
    n_joints = machine.joints
    print(f"{machine.modules} modules, {n_joints} joints, roll {machine.roll}")

    seen: dict[tuple, int] = {}          # canonical footprint -> fold count
    by_k: dict[int, list[tuple[float, list[str], tuple[int, ...]]]] = {}

    for k in range(1, args.max_folds + 1):
        hits = []
        for joints in combinations(range(n_joints), k):
            for signs in product((-1, 1), repeat=k):
                states = [0] * n_joints
                for j, s in zip(joints, signs):
                    states[j] = s
                cells, _ = fk(states, machine.roll)
                if len(set(map(tuple, cells))) != len(cells):
                    continue                      # self-intersecting
                flat = flat_axis(cells)
                if flat is None:
                    continue                      # not a flat shape
                key = canonical_planar(tuple(sorted(map(tuple, cells))))
                if key in seen:
                    continue                      # already reachable in fewer folds
                seen[key] = k
                rows = rows_of(cells, flat)
                filled = sum(r.count("#") for r in rows)
                if filled / (len(rows) * len(rows[0])) < args.min_fill:
                    continue
                hits.append((interest(rows), rows, tuple(states)))
        hits.sort(key=lambda e: -e[0])
        by_k[k] = hits
        print(f"  k={k}: {len(hits):,} new distinct flat shapes")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    for k in sorted(by_k):
        if not by_k[k]:
            continue
        print(f"\n{'='*58}\n{k} fold{'s' if k != 1 else ''} — top {min(args.per_k, len(by_k[k]))}")
        for i, (sc, rows, states) in enumerate(by_k[k][:args.per_k]):
            w, h = len(rows[0]), len(rows)
            print(f"\n  [{k}.{i:02d}] {w}x{h}  score {sc:.2f}")
            for r in rows:
                print(f"        {r}")
            if args.out:
                (args.out / f"k{k}-{i:02d}.txt").write_text("\n".join(rows) + "\n")
    if args.out:
        print(f"\nwrote masks to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
