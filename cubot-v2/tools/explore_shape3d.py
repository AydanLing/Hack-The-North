#!/usr/bin/env python3
"""Gate, thread, and fold layered (3D, one-deep shell) 27-cell masks.

The flat driver ``tools/explore_shape.py`` is bound to the planar
:class:`PixelTarget`.  This sibling takes layered ASCII masks (z-slices, top
layer first, ``---`` between slices — :func:`cubot.shapes.parse_layers`) and
runs the same discipline in 3D: structural screen, exact shipped-roll threading,
then fold search on *exact threadings of the drawing only*.

Two acceptance tiers are tried in order (``docs/CUBE_FEASIBILITY.md`` §4):

* tier 1 — the route passes the ``loose`` profile on a flat table;
* tier 2 — the route passes ``platform`` (``loose`` with the table removed: the
  robot folds on a raised platform, so moving modules may dip below the base
  plane).  Both verdicts are recorded; a tier-2 pass never hides the loose one.

Approaches per threading:

* ``forward`` (default) — :func:`cubot.folder.fold` from the straight chain,
  ``loose`` first with 40 % of the budget, then ``platform`` with the rest.
* ``--backward`` — fold from the goal back to the straight chain (CAD is
  time-symmetric, gravity is not), reverse the moves and replay them forward
  from the tracked straight pose; the forward :func:`cubot.folder.replay` under
  each profile is the certificate.  Chooses the finishing orientation by
  construction.
* ``--probe`` — before folding, count the goal's legal outgoing moves (rest
  overlap + CAD sweep under ``platform``) and rank threadings by it; a goal
  with zero escapes cannot be entered by any single-detent move.

One JSON line per mask goes to ``<out>/results.jsonl`` with the flat driver's
keys plus the 3D fields, so ``tools/explore_summary.py`` merges both.

Usage (from ``cubot-v2/``)::

    uv run python tools/explore_shape3d.py --name tray data/candidates/volumetric/tray-v*.txt --gate-only
    uv run python tools/explore_shape3d.py --name tray data/candidates/volumetric/tray-v1.txt \\
        --out out/explore3d-20260919/w1 --time-budget 180 -k 2 --probe
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402
from cubot.folder import (  # noqa: E402
    _rest_report,
    check_move,
    fold,
    lattice_span,
    replay,
    replay_tracked,
)
from cubot.lattice import ORIENTS, apply_detent, pose_cells  # noqa: E402
from cubot.pipeline import _raw_plan, _report_payload, _representative_ranking, _strict_replays  # noqa: E402
from cubot.records import Move, PlanCandidate, Pose, ShapeRecord, dump_json  # noqa: E402
from cubot.runtime import run_meta  # noqa: E402
from cubot.shapes import canonical_3d, dense_cell_count, has_2x2x2_block, parse_layers, screen, to_layers  # noqa: E402
from cubot.solver import solve  # noqa: E402
from cubot.viz import contact_sheet, render_iso, render_silhouette, render_top  # noqa: E402

AXIS_NAMES = {(1, 0, 0): "+x", (-1, 0, 0): "-x", (0, 1, 0): "+y", (0, -1, 0): "-y", (0, 0, 1): "+z", (0, 0, -1): "-z"}


def read_layers(path: Path) -> tuple[list[str], tuple]:
    text = path.read_text()
    rows = [line.rstrip("\n").replace(" ", "") for line in text.splitlines()]
    rows = [row for row in rows if row and not row.startswith("//")]
    return rows, parse_layers(text)


def variant_label(path: Path) -> str:
    return path.stem


def spans(cells) -> list[int]:
    arr = np.asarray(cells, dtype=int)
    return (arr.max(axis=0) - arr.min(axis=0)).tolist()


def source_hash(name: str, rows: list[str]) -> str:
    return hashlib.sha256(json.dumps({"concept": name, "layers": rows, "source": "explore3d"}).encode()).hexdigest()


def escape_count(goal: Pose, machine, profile, *, cap: int = 4, checker=check_move) -> int:
    """Legal single-detent moves *out of* the goal (CAD + rest overlap); a cheap necessary condition."""

    count = 0
    for joint in range(machine.joints):
        for delta in (-1, 1):
            try:
                apply_detent(goal.states, joint, delta)
            except ValueError:
                continue
            for side in ("in", "out"):
                move = Move(joint, delta, side)
                after = replay_tracked(goal, [move])
                if not _rest_report(after).hard_ok:
                    continue
                report = checker(goal, move, machine, profile)
                if report.hard_ok:
                    count += 1
                    if count >= cap:
                        return count
                break  # the CAD sweep of the two sides is the same geometry; rest check differs only by base
    return count


def orientation_report(goal: Pose, final: Pose) -> dict:
    rotation = ORIENTS[final.base] @ ORIENTS[goal.base].T
    up = tuple(int(v) for v in np.rint(rotation @ np.array([0, 0, 1])))
    return {
        "final_upright": up == (0, 0, 1),
        "final_up_axis": AXIS_NAMES.get(up, str(up)),
        "final_span": list(lattice_span(final)),
    }


def max_ground(candidate: PlanCandidate) -> float:
    depth = 0.0
    for move in candidate.moves:
        for key, value in move.checks.measurements.items():
            if key.startswith("max_ground_depth_mm") and isinstance(value, (int, float)):
                depth = max(depth, float(value))
    return depth


def passing(candidates) -> list[PlanCandidate]:
    return [c for c in candidates if c.complete and c.hard_ok]


def fold_forward(start: Pose, goal: Pose, *, machine, profile, time_budget_s, max_candidates, detour_budget, checker):
    return fold(
        start,
        goal,
        machine=machine,
        profile=profile,
        checker=checker,
        time_budget_s=time_budget_s,
        detour_budget=detour_budget,
        max_candidates=max_candidates,
    )


def backward_route(goal: Pose, *, machine, profile, time_budget_s, max_candidates, detour_budget, checker):
    """Fold goal -> straight, then certify the reversed moves forward from the tracked straight pose."""

    straight = Pose((0,) * machine.joints, machine.roll, base=goal.base, lying=None)
    result = fold(
        goal,
        straight,
        machine=machine,
        profile=profile,
        checker=checker,
        time_budget_s=time_budget_s,
        detour_budget=detour_budget,
        max_candidates=max_candidates,
        search_lying_faces=False,
    )
    certified: list[PlanCandidate] = []
    for candidate in result.candidates:
        if not candidate.complete:
            continue
        end = replay_tracked(goal, candidate.moves)
        start = Pose((0,) * machine.joints, machine.roll, base=end.base, lying=0)
        if lattice_span(start)[2] != 0:
            continue  # the straight chain must lie on the table at the start
        reversed_moves = [Move(m.joint, -m.delta, m.side, m.duration_s) for m in reversed(candidate.moves)]
        certified.append(
            replay(
                start,
                reversed_moves,
                goal=goal,
                machine=machine,
                profile=profile,
                checker=checker,
                notes=("backward search, forward replay certificate",),
            )
        )
    return result, certified


def explore_one(
    name: str,
    mask_path: Path,
    out_root: Path,
    *,
    time_budget_s: float,
    k: int,
    max_candidates: int,
    detour_budget: int | None,
    probe: bool,
    backward: bool,
    seed: int,
    checker=check_move,
) -> dict:
    machine = load_machine()
    loose = load_profile("loose")
    platform = load_profile("platform")
    strict = load_profile("strict")
    rows, cells = read_layers(mask_path)
    variant = variant_label(mask_path)
    layers = to_layers(cells) if cells else []
    box = [s + 1 for s in spans(cells)] if cells else [0, 0, 0]
    row: dict = {
        "name": name,
        "variant": variant,
        "mask": str(mask_path),
        "mask_rows": rows,
        "box": box,
        "layers": len(layers),
        "volumetric": all(s > 0 for s in spans(cells)) if cells else False,
        "two_thick": has_2x2x2_block(cells),
        "dense_cells": dense_cell_count(cells),
        "cells": len(set(cells)),
        "screen_ok": False,
        "screen_stage": None,
        "screen_reason": None,
        "threadings": 0,
        "thread_status": None,
        "escape_counts": [],
        "complete": None,
        "hard_ok": None,
        "tier": None,
        "approach": None,
        "fold_profile": None,
        "loose_hard_ok": None,
        "platform_hard_ok": None,
        "strict_hard_ok": None,
        "violations": [],
        "moves": None,
        "worst_soft": None,
        "scores": {},
        "max_ground_mm": None,
        "ends_flat": None,
        "final_upright": None,
        "final_up_axis": None,
        "final_span": None,
        "goal_is_mask": None,
        "goal_is_target": None,
        "top_png": None,
        "iso_png": None,
        "record_json": None,
        "fold_statuses": [],
        "elapsed_s": 0.0,
    }
    started = time.monotonic()

    report = screen(cells, 27)
    row["screen_ok"] = report.ok and not row["two_thick"]
    row["screen_stage"] = "two_thick" if row["two_thick"] else report.stage
    row["screen_reason"] = "contains a filled 2x2x2 block" if row["two_thick"] else report.reason
    if not row["screen_ok"]:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row

    threaded = solve(cells, machine.roll, all_solutions=True, max_solutions=64)
    row["thread_status"] = threaded.status.value
    row["threadings"] = len(threaded.solutions)
    if not threaded.found:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row

    # Distinct physical state words only (several threadings may share one).
    poses: list[Pose] = []
    seen_words: set[tuple[int, ...]] = set()
    for pose in threaded.poses:
        if pose.states in seen_words:
            continue
        seen_words.add(pose.states)
        poses.append(pose)
    if probe:
        scored = []
        for pose in poses:
            count = escape_count(pose, machine, platform, checker=checker)
            scored.append((count, pose))
        row["escape_counts"] = [count for count, _ in scored]
        poses = [pose for count, pose in sorted(scored, key=lambda item: -item[0]) if count > 0]
        if not poses:
            row["fold_statuses"] = ["NO_ESCAPE"]
            row["elapsed_s"] = round(time.monotonic() - started, 2)
            return row
    poses = poses[:k]

    start = Pose((0,) * machine.joints, machine.roll, base=0, lying=None)
    fold_results = []
    accepted: list[PlanCandidate] = []
    fallback: list[PlanCandidate] = []
    tier = None
    approach = None
    fold_profile = None
    fold_started = time.monotonic()
    per_pose = time_budget_s / max(1, len(poses))
    for pose in poses:
        remaining = time_budget_s - (time.monotonic() - fold_started)
        if remaining <= 5:
            break
        slice_budget = min(per_pose, remaining)
        if backward:
            result, certified = backward_route(
                pose,
                machine=machine,
                profile=platform,
                time_budget_s=slice_budget,
                max_candidates=max_candidates,
                detour_budget=detour_budget,
                checker=checker,
            )
            fold_results.append(result)
            fallback.extend(certified)
            loose_certified = _strict_replays(passing(certified), machine=machine, profile=loose, checker=checker)
            if passing(loose_certified):
                accepted, tier, approach, fold_profile = passing(loose_certified), 1, "backward", "loose"
                break
            if passing(certified):
                accepted, tier, approach, fold_profile = passing(certified), 2, "backward", "platform"
                break
            continue
        loose_result = fold_forward(
            start,
            pose,
            machine=machine,
            profile=loose,
            time_budget_s=slice_budget * 0.4,
            max_candidates=max_candidates,
            detour_budget=detour_budget,
            checker=checker,
        )
        fold_results.append(loose_result)
        fallback.extend(loose_result.candidates)
        if passing(loose_result.candidates):
            accepted, tier, approach, fold_profile = passing(loose_result.candidates), 1, "forward", "loose"
            break
        remaining = time_budget_s - (time.monotonic() - fold_started)
        platform_result = fold_forward(
            start,
            pose,
            machine=machine,
            profile=platform,
            time_budget_s=max(10.0, min(slice_budget * 0.6, remaining)),
            max_candidates=max_candidates,
            detour_budget=detour_budget,
            checker=checker,
        )
        fold_results.append(platform_result)
        fallback.extend(platform_result.candidates)
        if passing(platform_result.candidates):
            accepted, tier, approach, fold_profile = passing(platform_result.candidates), 2, "forward", "platform"
            break

    row["fold_statuses"] = [result.status.value for result in fold_results]
    if not accepted and not fallback:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row

    accept_profile = platform if fold_profile == "platform" else loose
    ranked = _representative_ranking(accepted or fallback, max_candidates)
    if not accepted:
        approach = "backward" if backward else "forward"
        fold_profile = accept_profile.name
    primary = ranked[0]

    loose_replays = _strict_replays(ranked, machine=machine, profile=loose, checker=checker)
    platform_replays = _strict_replays(ranked, machine=machine, profile=platform, checker=checker)
    strict_replays = _strict_replays(ranked, machine=machine, profile=strict, checker=checker)

    run_dir = out_root / "runs" / variant / name
    render_dir = run_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    goal_cells = tuple(pose_cells(primary.goal))
    top_path = render_silhouette(goal_cells, render_dir / "top.png")
    engineering_path = render_top(goal_cells, render_dir / "engineering.png", numbered=True)
    iso_path = render_iso(goal_cells, render_dir / "iso.png")
    rotated = tuple((-y, x, z) for x, y, z in goal_cells)
    iso2_path = render_iso(rotated, render_dir / "iso-90.png")
    contact_path = contact_sheet(
        [(f"{name} iso", iso_path), (f"{name} iso 90", iso2_path), (f"{name} top", top_path)],
        run_dir / "contact-sheet.png",
        show_labels=False,
    )

    hashed = source_hash(name, rows)
    for profile, replays, filename in (
        (loose, loose_replays, "loose-report.json"),
        (platform, platform_replays, "platform-report.json"),
        (strict, strict_replays, "strict-report.json"),
    ):
        dump_json(
            _report_payload(
                profile,
                replays,
                machine=machine,
                seed=seed,
                source_hash=hashed,
                fold_results=fold_results if profile is accept_profile else (),
            ),
            run_dir / filename,
        )
    raw = _raw_plan(
        primary,
        strict_replays[0],
        machine=machine,
        loose=accept_profile,
        strict=strict,
        seed=seed,
        source_hash=hashed,
    )
    raw["tier"] = tier
    raw["approach"] = approach
    raw["profile_reports"]["loose"] = {
        "hard_ok": loose_replays[0].hard_ok,
        "scores": loose_replays[0].scores,
        "violations": loose_replays[0].violations,
    }
    raw["profile_reports"]["platform"] = {
        "hard_ok": platform_replays[0].hard_ok,
        "scores": platform_replays[0].scores,
        "violations": platform_replays[0].violations,
    }
    dump_json(raw, run_dir / "checked-plan.json")

    final = replay_tracked(primary.start, primary.moves)
    orientation = orientation_report(primary.goal, final)
    layered_rows: list[str] = []
    for index, layer in enumerate(layers):
        if index:
            layered_rows.append("---")
        layered_rows.extend(layer)
    record = ShapeRecord(
        name=name,
        aliases=[],
        target=layered_rows,
        cells=list(goal_cells),
        pose=primary.goal,
        plans=ranked,
        renders={
            "top": str(top_path),
            "engineering": str(engineering_path),
            "iso": str(iso_path),
            "iso_90": str(iso2_path),
            "contact_sheet": str(contact_path),
        },
        human_pick=None,
        source="explore3d",
        status="checked" if primary.complete else "planned",
        meta=run_meta(machine, accept_profile, seed=seed, source_hash=hashed),
        notes=[
            f"accepted under {accept_profile.name} (tier {tier})" if tier else "no passing route in budget",
            f"approach {approach}",
            "3D target: top.png is a projection; judge from iso.png",
            f"finishes with drawn +z pointing {orientation['final_up_axis']}",
        ],
    )
    record_path = run_dir / "record.json"
    dump_json(record, record_path)

    row["record_json"] = str(record_path)
    row["top_png"] = str(top_path)
    row["iso_png"] = str(iso_path)
    row["complete"] = bool(primary.complete)
    row["hard_ok"] = bool(primary.hard_ok)
    row["tier"] = tier
    row["approach"] = approach
    row["fold_profile"] = fold_profile
    row["loose_hard_ok"] = bool(loose_replays[0].complete and loose_replays[0].hard_ok)
    row["platform_hard_ok"] = bool(platform_replays[0].complete and platform_replays[0].hard_ok)
    row["strict_hard_ok"] = bool(strict_replays[0].complete and strict_replays[0].hard_ok)
    row["violations"] = list(primary.violations)
    row["moves"] = len(primary.moves)
    row["scores"] = {key: round(float(value), 3) for key, value in primary.scores.items()}
    row["worst_soft"] = round(min(primary.scores.values()), 3) if primary.scores else None
    row["max_ground_mm"] = round(max_ground(primary), 2)
    row.update(orientation)
    row["ends_flat"] = orientation["final_span"][2] == 0
    row["goal_is_target"] = canonical_3d(goal_cells) == canonical_3d(cells)
    row["goal_is_mask"] = row["goal_is_target"]
    row["elapsed_s"] = round(time.monotonic() - started, 2)
    return row


def summary_line(row: dict) -> str:
    tag = f"{row['name']}/{row['variant']}"
    if not row["screen_ok"]:
        return f"{tag}: STRUCTURAL FAIL at {row['screen_stage']} — {row['screen_reason']}"
    if not row["threadings"]:
        return f"{tag}: roll-{row['thread_status']} (0 threadings)"
    if row["complete"] is None:
        return f"{tag}: {row['threadings']} threadings, fold produced no plan ({row['fold_statuses']}, escapes {row['escape_counts']})"
    if row["complete"] and row["hard_ok"]:
        verdict = f"PASS tier {row['tier']} ({row['fold_profile']}, {row['approach']})"
    elif row["complete"]:
        verdict = f"complete but violating under {row['fold_profile']}"
    else:
        verdict = "partial"
    return (
        f"{tag}: {row['threadings']} threadings, {verdict}, {row['moves']} moves, worst soft {row['worst_soft']}, "
        f"up {row['final_up_axis']}, dip {row['max_ground_mm']} mm, loose={row['loose_hard_ok']} platform={row['platform_hard_ok']}"
        + (f", violations={row['violations'][:3]}" if row["violations"] else "")
        + ("" if row["goal_is_target"] else " [GOAL != TARGET]")
        + f" ({row['elapsed_s']} s) -> {row['iso_png']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("masks", nargs="+", type=Path, help="layered ASCII mask files (top layer first)")
    parser.add_argument("--name", required=True, help="concept name, e.g. 'tray'")
    parser.add_argument("--out", type=Path, default=Path("out/explore3d-20260919"))
    parser.add_argument("--time-budget", type=float, default=180.0, help="total fold-search seconds per mask")
    parser.add_argument("-k", type=int, default=2, help="distinct threadings to try")
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--detour-budget", type=int, default=None)
    parser.add_argument("--probe", action="store_true", help="rank threadings by goal-side escape count first")
    parser.add_argument("--backward", action="store_true", help="fold goal->straight and certify the reversed route")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--gate-only", action="store_true", help="screen + thread only; never fold")
    args = parser.parse_args()

    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    results_path = out_root / "results.jsonl"
    machine = load_machine()

    exit_code = 2
    for mask_path in args.masks:
        if args.gate_only:
            _, cells = read_layers(mask_path)
            label = f"{args.name}/{variant_label(mask_path)}"
            if has_2x2x2_block(cells):
                print(f"{label}: REJECT two-thick (contains a 2x2x2 block)")
                continue
            report = screen(cells, 27)
            if not report.ok:
                print(f"{label}: STRUCTURAL FAIL at {report.stage} — {report.reason}")
                continue
            threaded = solve(cells, machine.roll, all_solutions=True, max_solutions=64)
            vol = "volumetric" if all(s > 0 for s in spans(cells)) else "PLANAR"
            print(f"{label}: {threaded.status.value}, {len(threaded.solutions)} threadings, dense {dense_cell_count(cells)}, {vol}")
            if threaded.found:
                exit_code = 0
            continue
        row = explore_one(
            args.name,
            mask_path,
            out_root,
            time_budget_s=args.time_budget,
            k=args.k,
            max_candidates=args.max_candidates,
            detour_budget=args.detour_budget,
            probe=args.probe,
            backward=args.backward,
            seed=args.seed,
        )
        with results_path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        print(summary_line(row), flush=True)
        if row["complete"] and row["hard_ok"]:
            exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
