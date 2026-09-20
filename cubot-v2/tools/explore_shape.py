#!/usr/bin/env python3
"""Gate, thread, and fold ad-hoc 27-cell masks that are not in the icon registry.

``cubot pipeline`` only accepts registered icon names, but the underlying
:func:`cubot.pipeline.run_pipeline` takes any :class:`PixelTarget`.  This
driver runs the cheap gates first (structural screens, exact roll threading)
and only spends fold-search time on masks that thread.  One JSON line per mask
is appended to ``<out>/results.jsonl`` so a batch of independent runs can be
summarized later by ``tools/explore_summary.py``.

Usage (from ``cubot-v2/``)::

    python tools/explore_shape.py --name l data/candidates/letters/l-v1.txt
    python tools/explore_shape.py --name l data/candidates/letters/l-v*.txt --time-budget 90
    python tools/explore_shape.py --name checkmark data/candidates/geometric/checkmark-v1.txt \\
        --profile gentle --yaw-expand

Mask files are top-first ASCII rows using ``#`` for filled and ``.`` for empty.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine  # noqa: E402
from cubot.folder import next_pose  # noqa: E402
from cubot.generate.base import PixelTarget, parse_grid  # noqa: E402
from cubot.lattice import fk  # noqa: E402
from cubot.match import MatchResult, recognition_distance  # noqa: E402
from cubot.pipeline import run_pipeline  # noqa: E402
from cubot.records import Move, Pose  # noqa: E402
from cubot.shapes import canonical_planar, planar_views, screen  # noqa: E402
from cubot.solver import solve  # noqa: E402


def read_mask(path: Path) -> list[str]:
    rows = [line.rstrip("\n").replace(" ", "") for line in path.read_text().splitlines()]
    rows = [row for row in rows if row and not row.startswith("//")]
    if not rows:
        raise ValueError(f"{path}: empty mask")
    return rows


def variant_label(path: Path) -> str:
    return path.stem


def ends_flat(plan: dict) -> bool | None:
    """Replay the plan's moves and report whether the tracked pose lies flat.

    Mirrors ``tools/export_handoff.py``: ``in`` moves rotate the base side, so
    the world orientation of the finished shape follows from the move sides,
    not from the nominal ``goal.base``.
    """

    if not plan.get("complete"):
        return None
    raw = plan["start"]
    pose = Pose(tuple(int(s) for s in raw["states"]), raw["roll"], int(raw["base"]), raw.get("lying"))
    for move in plan["moves"]:
        pose = next_pose(pose, Move(int(move["joint"]), int(move["delta"]), move["side"], float(move["duration_s"])))
    cells = np.asarray(fk(pose.states, pose.roll, pose.base)[0])
    span = (cells.max(axis=0) - cells.min(axis=0)).tolist()
    return span[2] == 0


def planar_view_to_grid(view: tuple[tuple[int, int], ...]) -> np.ndarray:
    """Rebuild a top-first boolean grid from a normalized planar view."""

    if not view:
        raise ValueError("empty planar view")
    max_x = max(x for x, _ in view)
    max_y = max(y for _, y in view)
    height = max_y + 1
    width = max_x + 1
    grid = np.zeros((height, width), dtype=bool)
    for x, y in view:
        # PixelTarget.cells uses (x, height-1-row, 0) from np.argwhere rows.
        grid[height - 1 - y, x] = True
    return grid


def cells_to_grid(cells: tuple[tuple[int, int, int], ...]) -> np.ndarray:
    max_x = max(c[0] for c in cells)
    max_y = max(c[1] for c in cells)
    height = max_y + 1
    width = max_x + 1
    grid = np.zeros((height, width), dtype=bool)
    for x, y, _z in cells:
        grid[height - 1 - y, x] = True
    return grid


def yaw_expanded_targets(name: str, cells: tuple[tuple[int, int, int], ...], caption: str) -> list[PixelTarget]:
    """Distinct planar yaw/mirror views of ``cells`` as PixelTargets."""

    concept_key = canonical_planar(cells)
    seen: set[tuple[tuple[int, int], ...]] = set()
    targets: list[PixelTarget] = []
    for view in planar_views(cells, reflect=True):
        if view in seen:
            continue
        seen.add(view)
        grid = planar_view_to_grid(view)
        target = PixelTarget(grid=grid, concept=name, caption=caption, source="explore-yaw")
        if canonical_planar(target.cells) != concept_key:
            continue
        targets.append(target)
    return targets or [
        PixelTarget(grid=cells_to_grid(cells), concept=name, caption=caption, source="explore")
    ]


def _threading_l1(pose: Pose) -> int:
    return int(sum(abs(int(s)) for s in pose.states))


def collect_yaw_threadings(
    name: str,
    cells: tuple[tuple[int, int, int], ...],
    caption: str,
    machine,
    *,
    yaw_expand: bool,
    max_solutions: int = 64,
) -> tuple[list[MatchResult], int, str | None]:
    """Thread the mask (and optional yaw views); return MatchResults sorted by L1."""

    concept_key = canonical_planar(cells)
    if yaw_expand:
        targets = yaw_expanded_targets(name, cells, caption)
    else:
        targets = [
            PixelTarget(grid=cells_to_grid(cells), concept=name, caption=caption, source="explore")
        ]

    exact: list[MatchResult] = []
    seen_states: set[tuple[int, ...]] = set()
    thread_status: str | None = None
    total_threadings = 0
    for target in targets:
        threaded = solve(
            tuple(target.cells),
            machine.roll,
            all_solutions=True,
            max_solutions=max_solutions,
            tether=machine.has_tether,
        )
        thread_status = threaded.status.value
        if not threaded.found:
            continue
        total_threadings += len(threaded.solutions)
        for pose in threaded.poses:
            pose_cells, _ = fk(pose.states, machine.roll, base=pose.base)
            if canonical_planar(pose_cells) != concept_key:
                continue
            key = tuple(int(s) for s in pose.states)
            if key in seen_states:
                continue
            seen_states.add(key)
            distance, transform = recognition_distance(pose_cells, target)
            exact.append(MatchResult(pose, tuple(pose_cells), distance, "exact", transform))

    exact.sort(key=lambda m: (_threading_l1(m.pose), m.distance))
    return exact, total_threadings, thread_status


def explore_one(
    name: str,
    mask_path: Path,
    out_root: Path,
    *,
    family: Path | None,
    time_budget_s: float,
    k: int,
    max_candidates: int,
    seed: int,
    profile: str = "gentle",
    yaw_expand: bool = True,
    machine_path: Path | None = None,
) -> dict:
    machine = load_machine(machine_path)
    rows = read_mask(mask_path)
    variant = variant_label(mask_path)
    target = PixelTarget(
        grid=parse_grid(rows),
        concept=name,
        caption=f"A flat pixel drawing of {name.replace('-', ' ')}",
        source="explore",
    )
    cells = tuple(target.cells)
    row: dict = {
        "name": name,
        "variant": variant,
        "mask": str(mask_path),
        "mask_rows": target.rows,
        "box": [len(rows[0]), len(rows)],
        "cells": len(cells),
        "screen_ok": False,
        "screen_stage": None,
        "screen_reason": None,
        "threadings": 0,
        "thread_status": None,
        "yaw_expand": yaw_expand,
        "profile": profile,
        "complete": None,
        "hard_ok": None,
        "violations": [],
        "moves": None,
        "worst_soft": None,
        "scores": {},
        "ends_flat": None,
        "goal_is_mask": None,
        "top_png": None,
        "record_json": None,
        "fold_statuses": [],
        "elapsed_s": 0.0,
    }
    started = time.monotonic()

    report = screen(cells, machine.modules)
    row["screen_ok"] = report.ok
    row["screen_stage"] = report.stage
    row["screen_reason"] = report.reason
    if not report.ok:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row

    exact, total_threadings, thread_status = collect_yaw_threadings(
        name,
        cells,
        target.caption,
        machine,
        yaw_expand=yaw_expand,
    )
    row["thread_status"] = thread_status
    row["threadings"] = total_threadings
    if not exact:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row

    # Fold only exact threadings (incl. yaw views). Prefer low-L1 goals first.
    match_results = exact[: max(k, 1)]

    run_dir = out_root / "runs" / variant
    run = run_pipeline(
        target,
        run_dir,
        machine=machine,
        family=family,
        match_results=match_results,
        seed=seed,
        k=k,
        time_budget_s=time_budget_s,
        max_candidates=max_candidates,
        include_heart_certificate=False,
        profile=profile,
    )
    record = json.loads(run.record_path.read_text())
    row["record_json"] = str(run.record_path)
    row["top_png"] = str(run.top_path)
    row["fold_statuses"] = list(run.fold_statuses)
    plans = record.get("plans", [])
    if plans:
        best = plans[0]  # records are rank-ordered; rank 0 is the shipped path
        row["complete"] = bool(best["complete"])
        row["hard_ok"] = bool(best["hard_ok"])
        row["violations"] = list(best.get("violations", []))
        row["moves"] = len(best["moves"])
        row["scores"] = {key: round(float(value), 3) for key, value in best.get("scores", {}).items()}
        row["worst_soft"] = round(min(best["scores"].values()), 3) if best.get("scores") else None
        row["ends_flat"] = ends_flat(best)
        goal = best["goal"]
        goal_cells = fk(tuple(goal["states"]), goal["roll"], int(goal["base"]))[0]
        # The pipeline may re-base the goal into another lattice plane, so
        # compare drawings up to planar symmetry rather than cell-for-cell.
        row["goal_is_mask"] = canonical_planar(goal_cells) == canonical_planar(cells)
    row["elapsed_s"] = round(time.monotonic() - started, 2)
    return row


def summary_line(row: dict) -> str:
    if not row["screen_ok"]:
        return f"{row['name']}/{row['variant']}: STRUCTURAL FAIL at {row['screen_stage']} — {row['screen_reason']}"
    if not row["threadings"]:
        return f"{row['name']}/{row['variant']}: roll-{row['thread_status']} (0 threadings)"
    if row["complete"] is None:
        return f"{row['name']}/{row['variant']}: {row['threadings']} threadings, fold produced no plan ({row['fold_statuses']})"
    verdict = "PASS" if (row["complete"] and row["hard_ok"]) else ("complete but violating" if row["complete"] else "partial")
    finish = {True: "flat", False: "STANDING", None: "?"}[row["ends_flat"]]
    return (
        f"{row['name']}/{row['variant']}: {row['threadings']} threadings, {verdict}, "
        f"{row['moves']} moves, worst soft {row['worst_soft']}, finishes {finish}"
        + (f", violations={row['violations']}" if row["violations"] else "")
        + ("" if row["goal_is_mask"] else " [GOAL != MASK]")
        + f" ({row['elapsed_s']} s) -> {row['top_png']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("masks", nargs="+", type=Path, help="ASCII mask files (top row first)")
    parser.add_argument("--name", required=True, help="concept name, e.g. 'l' or 'umbrella'")
    parser.add_argument("--out", type=Path, default=Path("out/explore-gentle"))
    parser.add_argument("--family", type=Path, default=Path("data/family/shipped-8x8.npz"))
    parser.add_argument("--time-budget", type=float, default=90.0, help="total fold-search seconds per mask")
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--profile", default="gentle", help="fold acceptance profile (default: gentle)")
    parser.add_argument(
        "--yaw-expand",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="also thread planar yaw/mirror views of the mask (default: on)",
    )
    parser.add_argument("--gate-only", action="store_true", help="screen + thread only; never fold")
    parser.add_argument("--machine", type=Path, default=None,
                        help="machine TOML (default: $CUBOT_MACHINE or config/machine.toml); masks need machine.modules cells")
    args = parser.parse_args()

    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    family = args.family if args.family and args.family.is_file() else None
    results_path = out_root / "results.jsonl"

    exit_code = 2
    for mask_path in args.masks:
        if args.gate_only:
            machine = load_machine(args.machine)
            rows = read_mask(mask_path)
            cells = tuple(PixelTarget(parse_grid(rows), args.name, "").cells)
            report = screen(cells, machine.modules)
            if not report.ok:
                print(f"{args.name}/{variant_label(mask_path)}: STRUCTURAL FAIL at {report.stage} — {report.reason}")
                continue
            threaded = solve(cells, machine.roll, all_solutions=True, max_solutions=64, tether=machine.has_tether)
            print(f"{args.name}/{variant_label(mask_path)}: {threaded.status.value}, {len(threaded.solutions)} threadings")
            if threaded.found:
                exit_code = 0
            continue
        row = explore_one(
            args.name,
            mask_path,
            out_root,
            family=family,
            time_budget_s=args.time_budget,
            k=args.k,
            max_candidates=args.max_candidates,
            seed=args.seed,
            profile=args.profile,
            yaw_expand=args.yaw_expand,
            machine_path=args.machine,
        )
        with results_path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        print(summary_line(row))
        if row["complete"] and row["hard_ok"]:
            exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
