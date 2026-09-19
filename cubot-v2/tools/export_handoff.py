#!/usr/bin/env python3
"""Export the finalized demo paths into the self-contained ``handoff/`` folder.

The pipeline writes its results under ``out/`` which is git-ignored and full of
search debris.  This script reads the seven finalized ``record.json`` files,
re-verifies each path with the current kinematics, and writes one flat,
documented JSON per shape (schema ``cubot.handoff.v1``) plus CSV move lists,
renders, and an index.  Nothing in ``handoff/`` depends on this package: the
sim side reads JSON and, if it wants a second opinion, runs the dependency-free
``handoff/tools/replay.py``.

Usage (from ``cubot-v2/``)::

    uv run python tools/export_handoff.py                 # default run dir
    uv run python tools/export_handoff.py --runs out/demo-20260919/runs

Shapes found by the mask-first exploration method (``docs/METHOD.md``) are
appended after the demo seven through a manifest written by
``tools/explore_summary.py``, or one at a time with ``--shape NAME=RUN_DIR``::

    uv run python tools/export_handoff.py --manifest out/explore-20260919/handoff-manifest.json
    uv run python tools/export_handoff.py --shape rocket=out/explore-20260919/verify/icons/runs/rocket-v4/rocket

A manifest is JSON ``{"schema": "cubot.handoff.manifest.v1", "shapes": [{"name", "run", "variant"?}]}``;
``run`` is the directory holding ``record.json`` and is resolved relative to the
manifest's own directory when it is not absolute.  ``--no-demo`` exports only the
manifest/``--shape`` entries.  Every entry goes through the same replay and
consistency checks as the demo seven; numbering continues after them.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402
from cubot.folder import ends_flat_on_table, lattice_span, next_pose  # noqa: E402
from cubot.geometry import pose_frames  # noqa: E402
from cubot.lattice import ORIENTS, fk  # noqa: E402
from cubot.records import Move, Pose  # noqa: E402

SCHEMA = "cubot.handoff.v1"
MANIFEST_SCHEMA = "cubot.handoff.manifest.v1"
DETENT_DEG = 120.0

# Demo order and numbering are part of the review contract (contact sheets are
# numbered this way), so they are fixed here rather than sorted.
SHAPES = ("heart", "arrow", "lightning", "plus", "h", "t", "n")

# cubot-v2 chain frame (chain along +x) -> snake_pipeline chain frame (chain
# along +z).  Verified on all seven goals: cell_sp = M @ cell_v2.
V2_TO_SNAKE_PIPELINE = np.array(((0, 1, 0), (0, 0, 1), (1, 0, 0)), dtype=int)


def load_manifest(path: Path) -> list[dict]:
    """Read a ``cubot.handoff.manifest.v1`` file into ``[{name, run, variant}]`` with absolute run dirs."""

    raw = json.loads(path.read_text())
    if raw.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"{path}: expected schema {MANIFEST_SCHEMA!r}, got {raw.get('schema')!r}")
    entries = []
    for item in raw.get("shapes", []):
        if "name" not in item or "run" not in item:
            raise ValueError(f"{path}: every manifest shape needs 'name' and 'run'")
        run = Path(item["run"])
        if not run.is_absolute():
            run = (path.parent / run).resolve()
        entries.append({"name": str(item["name"]), "run": run, "variant": item.get("variant")})
    return entries


def parse_shape_arg(spec: str) -> dict:
    """``NAME=RUN_DIR`` from the command line, run dir resolved against the cwd."""

    name, sep, run = spec.partition("=")
    if not sep or not name or not run:
        raise ValueError(f"--shape expects NAME=RUN_DIR, got {spec!r}")
    return {"name": name.strip(), "run": Path(run).resolve(), "variant": None}


def plan_exports(demo: list[dict], extra: list[dict]) -> list[dict]:
    """Number the demo seven first, then every extra entry; names must be unique."""

    ordered = list(demo) + list(extra)
    seen: dict[str, int] = {}
    for number, entry in enumerate(ordered, start=1):
        if entry["name"] in seen:
            raise ValueError(f"duplicate handoff shape name {entry['name']!r} (#{seen[entry['name']]} and #{number})")
        seen[entry["name"]] = number
        entry["number"] = number
    return ordered


def _pose(raw: dict) -> Pose:
    return Pose(tuple(int(s) for s in raw["states"]), raw["roll"], int(raw["base"]), raw.get("lying"))


def _pose_json(pose: Pose) -> dict:
    cells, orients = fk(pose.states, pose.roll, pose.base)
    return {
        "states": list(pose.states),
        "states_mod3": [s % 3 for s in pose.states],
        "angles_deg": [s * DETENT_DEG for s in pose.states],
        "base": pose.base,
        "base_matrix": ORIENTS[pose.base].astype(int).tolist(),
        "lying": pose.lying,
        "cells": [list(c) for c in cells],
        "module_orientation_matrices": [ORIENTS[o].astype(int).tolist() for o in orients],
    }


def _world_frames(pose: Pose, machine) -> dict:
    centres, rotations = pose_frames(pose, machine)
    return {
        "note": "Continuous FK of the rest pose, settled so the lowest hull point sits on the table plane z=0. "
        "Metres would be these values / 1000.",
        "table_plane": "z = 0, gravity -z",
        "centres_mm": np.round(centres, 6).tolist(),
        "rotations": np.round(rotations, 12).tolist(),
    }


def _silhouette(cells: list[tuple[int, int, int]]) -> list[str]:
    """Top-down ASCII of a flat drawing: which two axes vary is detected per shape."""

    arr = np.asarray(cells, dtype=int)
    spans = arr.max(axis=0) - arr.min(axis=0)
    axes = [i for i in range(3) if spans[i] > 0]
    if len(axes) != 2:
        return []
    a, b = axes
    occupied = {(int(x[a]), int(x[b])) for x in arr}
    rows = []
    for j in range(int(arr[:, b].max()), int(arr[:, b].min()) - 1, -1):
        rows.append("".join("#" if (i, j) in occupied else "." for i in range(int(arr[:, a].min()), int(arr[:, a].max()) + 1)))
    return rows


def _move_rows(start: Pose, plan_moves: list[dict], machine) -> tuple[list[dict], Pose]:
    pose = start
    rows: list[dict] = []
    for index, raw in enumerate(plan_moves, start=1):
        move = Move(int(raw["joint"]), int(raw["delta"]), raw["side"], float(raw["duration_s"]))
        before = pose.states[move.joint]
        pose = next_pose(pose, move)
        after = pose.states[move.joint]
        checks = raw["checks"]
        rows.append(
            {
                "step": index,
                "joint": move.joint,
                "delta": move.delta,
                "side": move.side,
                "moving_side_snake_pipeline": "parent" if move.side == "in" else "child",
                "duration_s": move.duration_s,
                "state_before": before,
                "state_after": after,
                "angle_after_deg": after * DETENT_DEG,
                "states_after": list(pose.states),
                "base_after": pose.base,
                "cells_after": [list(c) for c in fk(pose.states, pose.roll, pose.base)[0]],
                "hard_ok": all(ok for ok, _ in checks["hard"].values()),
                "checks": checks,
            }
        )
    return rows, pose


def _plan_summary(plan: dict) -> dict:
    return {
        "moves": len(plan["moves"]),
        "complete": plan["complete"],
        "hard_ok": plan["hard_ok"],
        "violations": plan["violations"],
        "scores": plan["scores"],
        "notes": plan["notes"],
    }


def export_shape(name: str, number: int, run_dir: Path, out_dir: Path, machine, profiles: dict, variant: str | None = None) -> dict:
    record = json.loads((run_dir / "record.json").read_text())
    reports = {
        p: json.loads((run_dir / f"{p}-report.json").read_text())
        for p in ("loose", "strict")
        if (run_dir / f"{p}-report.json").is_file()
    }
    plans = record["plans"]
    primary_index = 0  # records are stored rank-ordered; rank 0 is the shipped path
    plan = plans[primary_index]
    if not plan["complete"]:
        raise ValueError(f"{name}: primary plan is not complete")

    start = _pose(plan["start"])
    goal = _pose(plan["goal"])
    machine = replace(machine, roll=start.roll)

    moves, replayed = _move_rows(start, plan["moves"], machine)
    if replayed.states != goal.states:
        raise ValueError(f"{name}: replaying the moves does not reach the recorded goal states")
    # The record's goal.base is the *nominal* design orientation from threading.
    # ``replayed.base`` is the orientation the checks actually tracked: every
    # ``in`` move rotates the base side while the tail stays put, so the world
    # orientation of the finished shape is a consequence of the move sides.
    # Both are exported; the sim should expect the tracked one.
    goal_cells = fk(goal.states, goal.roll, goal.base)[0]
    tracked_span = list(lattice_span(replayed))
    ends_flat = ends_flat_on_table(replayed)
    if [list(c) for c in goal_cells] != [list(c) for c in record["cells"]]:
        raise ValueError(f"{name}: goal FK cells differ from the record's cells")
    if len(set(goal_cells)) != 27:
        raise ValueError(f"{name}: goal is not self-avoiding")

    # Find this exact move sequence in each profile report so the strict verdict
    # refers to the shipped path and not merely to the best strict candidate.
    signature = [(m["joint"], m["delta"], m["side"]) for m in plan["moves"]]
    report_summary: dict = {}
    for profile_name, report in reports.items():
        match = next(
            (c for c in report.get("ranked", []) if [(m["joint"], m["delta"], m["side"]) for m in c["moves"]] == signature),
            None,
        )
        report_summary[profile_name] = {
            "profile": profile_name,
            "config_hash": report["meta"]["config_hash"],
            "candidates_summary": report["summary"],
            "this_path": None if match is None else {
                "hard_ok": match["hard_ok"],
                "violations": match["violations"],
                "scores": match["scores"],
                "notes": match["notes"],
            },
        }
    strict_match = report_summary.get("strict", {}).get("this_path")
    strict_hard_ok = None if strict_match is None else bool(strict_match["hard_ok"])

    alternates = [
        {"plan_index": i, **_plan_summary(p), "moves_compact": [[m["joint"], m["delta"], m["side"], m["duration_s"]] for m in p["moves"]]}
        for i, p in enumerate(plans)
        if i != primary_index and p["complete"] and p["hard_ok"]
    ]

    goal_json = _pose_json(goal)
    snake_cells = (V2_TO_SNAKE_PIPELINE @ np.asarray(goal_cells, dtype=int).T).T

    shape_dir = out_dir / "shapes" / f"{number:02d}-{name}"
    shape_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema": SCHEMA,
        "name": name,
        "demo_number": number,
        "aliases": record.get("aliases", []),
        "status": {
            "complete": plan["complete"],
            "loose_hard_ok": plan["hard_ok"],
            "strict_hard_ok": strict_hard_ok,
            "loose_violations": plan["violations"],
            "human_pick": record.get("human_pick"),
            "library_status": record.get("status"),
            "plan_notes": plan["notes"],
            "record_notes": record.get("notes", []),
        },
        "summary": {
            "moves": len(moves),
            "ends_flat_on_table": ends_flat,
            "total_time_s": sum(m["duration_s"] for m in moves),
            "in_moves": sum(1 for m in moves if m["side"] == "in"),
            "out_moves": sum(1 for m in moves if m["side"] == "out"),
            "peak_demand_nm": max(m["checks"]["measurements"].get("peak_demand_nm", 0.0) for m in moves),
            "max_cad_penetration_mm": max(m["checks"]["measurements"].get("max_penetration_mm", 0.0) for m in moves),
            "max_ground_depth_mm": max(m["checks"]["measurements"].get("max_ground_depth_mm", 0.0) for m in moves),
            "scores": plan["scores"],
        },
        "machine": {
            "modules": machine.modules,
            "joints": machine.joints,
            "side_mm": machine.side_mm,
            "gap_mm": machine.gap_mm,
            "pitch_mm": machine.pitch_mm,
            "chamfer_mm": machine.chamfer_mm,
            "mass_kg_per_module": machine.mass_kg,
            "stall_torque_nm": machine.stall_torque_nm,
            "move_time_s": machine.move_time_s,
            "joint_angle_deg": machine.joint_angle_deg,
            "joint_positions": [-1, 0, 1],
            "joint_angles_deg": [-DETENT_DEG, 0.0, DETENT_DEG],
            "roll": start.roll,
            "module_solid": "../../module_solid.json",
        },
        "conventions": "See ../../README.md (section 'Conventions'). Short form: 26 joints for 27 modules; joint i is "
        "the hinge inside module i (0-based) on its (1,1,1) body diagonal; states -1/0/+1 = -120/0/+120 deg; a "
        "move is one detent; side 'out' = tail modules (i+1..26 plus the moving half of i) swing, side 'in' = base "
        "modules (0..i-1 plus the still half of i) swing while the tail stays put.",
        "start": _pose_json(start),
        "goal": {
            "note": "Nominal goal in the design orientation the threading produced (this is what the renders show). "
            "Joint states are the contract; 'base' here is NOT the orientation the shape ends up in on the table.",
            **goal_json,
            "silhouette": _silhouette(goal_cells),
            "authored_target": record["target"],
        },
        "final_tracked": {
            "note": "Pose after replaying every move with the held side pinned (the orientation the pre-sim checks "
            "used). Same joint states as 'goal'; 'base' is the predicted world orientation of the finished shape.",
            **_pose_json(replayed),
            "lattice_span": tracked_span,
            "ends_flat_on_table": ends_flat,
            "final_balance_margin_mm": moves[-1]["checks"]["measurements"].get("balance_margin_mm"),
        },
        "world_frames": {
            "start": _world_frames(start, machine),
            "final_tracked": _world_frames(replayed, machine),
            "goal_nominal": _world_frames(goal, machine),
        },
        "moves": moves,
        "alternates": alternates,
        "snake_pipeline": {
            "note": "Same path expressed in snake_pipeline conventions (chain frame along +z, 27 servo entries, "
            "states 0/1/2 = 0/120/240 deg, cube 1 at the origin with the identity frame). Verified: "
            "mechanism.lattice_walk(states) on the shipped assembly returns exactly cells_chain_frame.",
            "assembly": start.roll,
            "goal_states_mod3_27": goal_json["states_mod3"] + [0],
            "goal_angles_rad_27": [float(np.deg2rad(120.0 * s)) for s in goal_json["states_mod3"]] + [0.0],
            "cells_chain_frame": snake_cells.tolist(),
            "axis_map_v2_to_snake_pipeline": V2_TO_SNAKE_PIPELINE.tolist(),
            "moving_side_map": {"in": "parent", "out": "child"},
            "pitch_warning": "cubot-v2 checks ran at pitch 82 mm (80 + 2); snake_pipeline constants.PITCH is 0.084 m.",
        },
        "profiles": profiles,
        "reports": report_summary,
        "provenance": {
            "source_record": str(run_dir / "record.json"),
            "plan_index": primary_index,
            "record_source": record.get("source"),
            "created": record["meta"]["created"],
            "git_sha": record["meta"]["git_sha"],
            "config_hash": record["meta"]["config_hash"],
            "source_hash": record["meta"]["source_hash"],
            "profile": record["meta"]["profile"],
            "seed": record["meta"]["seed"],
            "mask_variant": variant,
            "exporter": "tools/export_handoff.py",
        },
    }
    (shape_dir / "path.json").write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")

    with (shape_dir / "moves.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["step", "joint", "delta", "side", "duration_s", "state_before", "state_after", "angle_after_deg", "hard_ok", "peak_demand_nm", "max_penetration_mm", "max_ground_depth_mm"])
        for m in moves:
            meas = m["checks"]["measurements"]
            writer.writerow([
                m["step"], m["joint"], m["delta"], m["side"], m["duration_s"], m["state_before"], m["state_after"],
                m["angle_after_deg"], m["hard_ok"], round(meas.get("peak_demand_nm", 0.0), 4),
                round(meas.get("max_penetration_mm", 0.0), 4), round(meas.get("max_ground_depth_mm", 0.0), 4),
            ])

    (shape_dir / "silhouette.txt").write_text("\n".join(_silhouette(goal_cells)) + "\n")

    for render in ("top", "iso", "engineering"):
        src = run_dir / "renders" / f"{render}.png"
        if src.is_file():
            shutil.copyfile(src, shape_dir / f"{render}.png")

    return {
        "number": number,
        "name": name,
        "dir": f"shapes/{number:02d}-{name}",
        "moves": len(moves),
        "complete": plan["complete"],
        "loose_hard_ok": plan["hard_ok"],
        "strict_hard_ok": strict_hard_ok,
        "loose_violations": len(plan["violations"]),
        "alternate_passing_routes": len(alternates),
        "human_pick": record.get("human_pick"),
        "ends_flat_on_table": ends_flat,
        "start_base": start.base,
        "goal_base_nominal": goal.base,
        "final_base_tracked": replayed.base,
        "goal_states": list(goal.states),
        "created": record["meta"]["created"],
        "mask_variant": variant,
    }


def _paths_markdown(entries: list[dict], out_dir: Path) -> str:
    """Human-readable digest of every shipped path, generated so nothing is transcribed by hand."""

    lines = [
        "# Finalized paths — digest",
        "",
        "Generated by `tools/export_handoff.py`; do not edit.  `path.json` in each shape folder is the",
        "source of truth, this page is for reading.  Move tuples are `(joint, delta, side)`; joints are",
        "0-based, `delta` is one detent (+1 = +120°, -1 = -120°), `side` says which half swings",
        "(`out` = tail modules after the joint, `in` = base modules before it).  See `README.md`.",
        "",
        "| # | shape | moves | loose hard checks | strict | finishes | alternates | notes |",
        "|---|-------|------:|-------------------|--------|----------|-----------:|-------|",
    ]
    for e in entries:
        payload = json.loads((out_dir / e["dir"] / "path.json").read_text())
        notes = []
        if e["loose_violations"]:
            notes.append(f"{e['loose_violations']} loose violations (see below)")
        for note in payload["status"]["plan_notes"]:
            if note not in ("final forward recheck",):
                notes.append(note)
        lines.append(
            f"| {e['number']} | {e['name']} | {e['moves']} | {'pass' if e['loose_hard_ok'] else 'FAIL'} | "
            f"{'pass' if e['strict_hard_ok'] else 'fail'} | {'flat on table' if e['ends_flat_on_table'] else 'STANDING'} | "
            f"{e['alternate_passing_routes']} | {'; '.join(notes)} |"
        )
    lines.append("")
    for e in entries:
        payload = json.loads((out_dir / e["dir"] / "path.json").read_text())
        moves = payload["moves"]
        lines += [
            f"## {e['number']}. {e['name']}  (`{e['dir']}/`)",
            "",
            "```",
            *payload["goal"]["silhouette"],
            "```",
            "",
            f"- start: straight chain, base orientation {payload['start']['base']}"
            + (f" (lying {payload['start']['lying']})" if payload["start"]["lying"] is not None else ""),
            f"- goal states: `{payload['goal']['states']}`",
            f"- {len(moves)} moves, {payload['summary']['total_time_s']:.0f} s at {payload['machine']['move_time_s']} s per detent; "
            f"{payload['summary']['in_moves']} `in` / {payload['summary']['out_moves']} `out`",
            f"- peak torque demand {payload['summary']['peak_demand_nm']:.2f} N·m, max CAD penetration "
            f"{payload['summary']['max_cad_penetration_mm']:.3f} mm, max table incursion {payload['summary']['max_ground_depth_mm']:.1f} mm",
            f"- predicted final orientation: base {payload['final_tracked']['base']}, lattice span {payload['final_tracked']['lattice_span']}, "
            f"{'flat on the table' if payload['final_tracked']['ends_flat_on_table'] else 'STANDING on edge (drawing plane vertical)'}",
        ]
        if payload["status"]["loose_violations"]:
            lines.append("- loose hard-check violations:")
            lines += [f"  - {v}" for v in payload["status"]["loose_violations"]]
        for note in payload["status"]["plan_notes"]:
            if note != "final forward recheck":
                lines.append(f"- note: {note}")
        lines += ["", "```python", "moves = ["]
        for m in moves:
            lines.append(f"    ({m['joint']:2d}, {m['delta']:+d}, {m['side']!r}),  # step {m['step']:2d}: joint {m['joint']} {m['state_before']:+d} -> {m['state_after']:+d}")
        lines += ["]", "```", ""]
        if payload["alternates"]:
            lines.append(f"Alternate loose-passing routes to the same goal ({len(payload['alternates'])}, in `path.json` → `alternates`):")
            for alt in payload["alternates"]:
                lines.append(f"- plan {alt['plan_index']}: {alt['moves']} moves — `{[(j, d, s) for j, d, s, _ in alt['moves_compact']]}`")
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=Path, default=ROOT / "out" / "demo-20260919" / "runs")
    parser.add_argument("--out", type=Path, default=ROOT / "handoff")
    parser.add_argument("--contact-sheets", type=Path, default=ROOT / "out" / "demo-20260919")
    parser.add_argument("--manifest", type=Path, action="append", default=[],
                        help="cubot.handoff.manifest.v1 file(s); shapes are appended after the demo seven")
    parser.add_argument("--shape", action="append", default=[], metavar="NAME=RUN_DIR",
                        help="append one shape from a pipeline run directory holding record.json")
    parser.add_argument("--no-demo", action="store_true", help="export only --manifest/--shape entries")
    args = parser.parse_args()

    machine = load_machine()
    profiles = {}
    for name in ("loose", "strict"):
        profile = load_profile(name)
        profiles[name] = {k: getattr(profile, k) for k in profile.__dataclass_fields__ if k != "name"}  # type: ignore[attr-defined]

    args.out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "data" / "solids" / "module.json", args.out / "module_solid.json")
    machine_raw = tomllib.loads((ROOT / "config" / "machine.toml").read_text())["machine"]
    (args.out / "machine.json").write_text(json.dumps({
        "schema": "cubot.handoff.machine.v1",
        **machine_raw,
        "pitch_mm": machine.pitch_mm,
        "joints": machine.joints,
        "joint_positions": [-1, 0, 1],
        "joint_angles_deg": [-DETENT_DEG, 0.0, DETENT_DEG],
        "module_solid": "module_solid.json",
        "check_profiles": profiles,
    }, indent=2) + "\n")

    demo = [] if args.no_demo else [{"name": name, "run": args.runs / name, "variant": None} for name in SHAPES]
    try:
        extra = [entry for manifest in args.manifest for entry in load_manifest(manifest)]
        extra += [parse_shape_arg(spec) for spec in args.shape]
        planned_all = plan_exports(demo, extra)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if not planned_all:
        raise SystemExit("nothing to export: --no-demo given without --manifest or --shape")

    entries = []
    for planned in planned_all:
        run_dir = planned["run"]
        if not (run_dir / "record.json").is_file():
            raise SystemExit(f"missing record.json in run directory {run_dir}")
        entries.append(export_shape(planned["name"], planned["number"], run_dir, args.out, machine, profiles, variant=planned["variant"]))
        e = entries[-1]
        print(f"exported {e['number']}. {e['name']}: {e['moves']} moves, loose_hard_ok={e['loose_hard_ok']}, ends_flat={e['ends_flat_on_table']}")

    for sheet in ("contact-sheet-labeled.png", "contact-sheet-blind.png"):
        src = args.contact_sheets / sheet
        if src.is_file():
            shutil.copyfile(src, args.out / sheet)

    (args.out / "PATHS.md").write_text(_paths_markdown(entries, args.out))
    (args.out / "index.json").write_text(json.dumps({
        "schema": "cubot.handoff.index.v1",
        "roll": machine.roll,
        "pitch_mm": machine.pitch_mm,
        "source_runs": str(args.runs),
        "shapes": entries,
    }, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
