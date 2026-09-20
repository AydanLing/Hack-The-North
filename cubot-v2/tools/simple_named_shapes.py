#!/usr/bin/env python3
"""Pick the cheapest fold that genuinely looks like each named concept.

Combines the two halves of the discovery problem.  ``enumerate_simple_folds``
knows every configuration the chain can reach within a fold budget;
``match_glyphs`` knows what the ideal letters and symbols look like.  This walks
the cheap configurations and, for every concept, keeps the one with the best
overlap -- reporting the fold count alongside, so a shape is only recommended
when it is both recognisable and quick.

The overlap score is what the old library lacked.  Its "zigzag" and "triangle"
were named by intent rather than by resemblance; here a name is only attached
when some reachable shape actually scores against the template.

    python tools/simple_named_shapes.py --max-folds 5
    python tools/simple_named_shapes.py --max-folds 6 --min-iou 0.6 --out data/candidates/n17-named
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enumerate_simple_folds import flat_axis, rows_of  # noqa: E402
from match_glyphs import TEMPLATES, best_iou, cells_of, dims, mask_of, parse_rows  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--machine", default="config/machine-17.toml")
    ap.add_argument("--max-folds", type=int, default=5)
    ap.add_argument("--min-iou", type=float, default=0.55)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    machine = load_machine(args.machine)
    n_joints = machine.joints
    names = args.only or list(TEMPLATES)
    prepared = {}
    for name in names:
        t = cells_of(parse_rows(TEMPLATES[name]))
        t = {(x + 2, y + 2) for x, y in t}
        prepared[name] = (mask_of(t), dims(t))

    # concept -> (iou, folds, rows, states)
    best: dict[str, tuple] = {}
    seen: set[tuple] = set()
    print(f"{machine.modules} modules, scanning fold budgets 1..{args.max_folds}")

    for k in range(1, args.max_folds + 1):
        checked = 0
        for joints in combinations(range(n_joints), k):
            for signs in product((-1, 1), repeat=k):
                states = [0] * n_joints
                for j, s in zip(joints, signs):
                    states[j] = s
                cells, _ = fk(states, machine.roll)
                if len(set(map(tuple, cells))) != len(cells):
                    continue
                flat = flat_axis(cells)
                if flat is None:
                    continue
                key = canonical_planar(tuple(sorted(map(tuple, cells))))
                if key in seen:
                    continue
                seen.add(key)
                checked += 1
                rows = rows_of(cells, flat)
                fp = cells_of(rows)
                for name in names:
                    tmpl_mask, tmpl_dims = prepared[name]
                    iou = best_iou(fp, tmpl_mask, tmpl_dims)
                    prev = best.get(name)
                    # Prefer a better match; on a tie prefer fewer folds.
                    if prev is None or iou > prev[0] + 1e-9:
                        best[name] = (iou, k, rows, tuple(states))
        print(f"  k={k}: {checked:,} new shapes")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    print(f"\n{'concept':12} {'IoU':>5} {'folds':>5}   shape")
    print("-" * 60)
    for name in sorted(best, key=lambda n: (-best[n][0], best[n][1])):
        iou, k, rows, states = best[name]
        verdict = "GOOD" if iou >= args.min_iou else "weak"
        print(f"\n{name:12} {iou:5.2f} {k:5}   [{verdict}]")
        for r in rows:
            print(f"                          {r}")
        if args.out and iou >= args.min_iou:
            (args.out / f"{name}.txt").write_text("\n".join(rows) + "\n")
    if args.out:
        good = sum(1 for v in best.values() if v[0] >= args.min_iou)
        print(f"\nwrote {good} masks scoring >= {args.min_iou} to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
