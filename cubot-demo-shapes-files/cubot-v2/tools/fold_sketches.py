"""Search a checked fold order for each fitted sketch target.

`sketch_fit.py` produces goal poses: shapes the chain can occupy.  It does not
produce plans.  Getting from one to the other is the step that killed lightning
-- a perfectly threadable shape whose fold sweeps six of its moves through the
table -- so a target is not demo-ready until this has run on it.

This turns each threadable mask into a Pose (via the exact roll solver) and
hands it to the same fold search the pipeline uses, under the named profile.

    uv run python tools/fold_sketches.py --profile loose

Writes one plan JSON per success into docs/sketches/plans/ and prints a table.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cubot.config import load_machine, load_profile
from cubot.folder import fold as search_fold
from cubot.records import Pose, dump_json
from cubot.solver import solve

from sketch_fit import cells_of, parse_blocks


def goal_pose(cells, roll: str) -> Pose | None:
    """The first exact threading of a mask, as a machine pose."""
    result = solve([(x, y, 0) for (x, y) in cells], roll, budget_nodes=2_000_000)
    if not result.solutions:
        return None
    threading = result.solutions[0]
    return Pose(tuple(threading.states), roll, base=threading.base, lying=None)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", type=Path,
                        default=root / "docs/sketches/threadable-targets.txt")
    parser.add_argument("--out", type=Path, default=root / "docs/sketches/plans")
    parser.add_argument("--profile", default="loose")
    parser.add_argument("--only", nargs="*", help="limit to these shape names")
    parser.add_argument("--time-budget", type=float, default=120.0,
                        help="seconds per shape")
    parser.add_argument("--beam-width", type=int, default=1200)
    parser.add_argument("--max-candidates", type=int, default=8)
    args = parser.parse_args()

    machine = load_machine()
    profile = load_profile(args.profile)
    args.out.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, str, str]] = []
    for heading, ascii_rows in parse_blocks(args.targets):
        name = heading.split()[0]
        if args.only and name not in args.only:
            continue
        goal = goal_pose(cells_of(ascii_rows), machine.roll)
        if goal is None:
            rows.append((name, "NO THREAD", "-", "-"))
            print(f"  {name}: does not thread -- skipped", file=sys.stderr)
            continue

        start = Pose((0,) * machine.joints, goal.roll, base=goal.base, lying=None)
        began = time.monotonic()
        result = search_fold(
            start, goal,
            machine=machine,
            profile=profile,
            time_budget_s=args.time_budget,
            max_candidates=args.max_candidates,
        )
        elapsed = time.monotonic() - began
        status = result.status.value
        moves = "-"
        if status == "FOUND":
            plan = result.candidates[0] if getattr(result, "candidates", None) else None
            moves = str(len(plan.moves)) if plan is not None else "?"
            dump_json(result, args.out / f"{name}-plan.json")
        rows.append((name, status, moves, f"{elapsed:.0f}s"))
        print(f"  {name}: {status} moves={moves} in {elapsed:.0f}s", file=sys.stderr)

    print()
    print(f"{'shape':16s} {'fold search':12s} {'moves':>6s} {'time':>7s}")
    print("-" * 44)
    for name, status, moves, elapsed in rows:
        print(f"{name:16s} {status:12s} {moves:>6s} {elapsed:>7s}")
    found = sum(1 for r in rows if r[1] == "FOUND")
    print(f"\n{found}/{len(rows)} have a fold order under the {args.profile} profile")
    return 0 if found else 2


if __name__ == "__main__":
    raise SystemExit(main())
