#!/usr/bin/env python3
"""Gate, probe, and fold 27-cell *three-dimensional* targets.

``tools/explore_shape.py`` drives flat masks.  This is the same mask-first
loop for layered targets (bent plates, tubes, helices, box frames): draw the
cells, prove a shipped-roll threading in milliseconds, run a goal-side CAD
escape probe on each distinct threading (a cheap necessary condition — see
``docs/CUBE_FEASIBILITY.md``), and spend fold-search time only on threadings
with clean escapes.  One JSON line per mask is appended to
``<out>/results.jsonl``; ``--summary`` turns those into ``summary.md``, voxel
contact sheets and a ``cubot.handoff.manifest.v1`` file that
``tools/export_handoff.py --manifest`` accepts unchanged.

Mask files are z-layers, bottom layer first, separated by blank lines.  Each
layer is written like a flat mask: rows top-first (``#`` filled, ``.`` empty),
so the top row of a layer is the largest ``y``.  ``//`` lines are comments.

Usage (from ``cubot-v2/``)::

    uv run python tools/explore_3d.py --name tunnel data/candidates/3d/tunnel-v*.txt --gate-only
    uv run python tools/explore_3d.py --name tunnel data/candidates/3d/tunnel-v*.txt --probe-only
    uv run python tools/explore_3d.py --name tunnel data/candidates/3d/tunnel-v2.txt \
        --out out/explore3d-<date> --time-budget 150 -k 2
    uv run python tools/explore_3d.py --summary --out out/explore3d-<date>
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import itertools
import json
from multiprocessing import Pool
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402
from cubot.folder import _default_side_selector, _rest_report, check_move, fold, merge_reports, next_pose, replay  # noqa: E402
from cubot.generate.base import PixelTarget  # noqa: E402
from cubot.geometry import sweep  # noqa: E402
from cubot.lattice import ORIENTS, apply_detent, fk, lying_variants, pose_cells  # noqa: E402
from cubot.match import MatchResult  # noqa: E402
from cubot.pipeline import run_pipeline  # noqa: E402
from cubot.pipeline import _raw_plan, _strict_replays  # noqa: E402
from cubot.records import CheckReport, Move, PlanCandidate, Pose, _jsonable, dump_json  # noqa: E402
from cubot.shapes import screen  # noqa: E402
from cubot.solver import solve  # noqa: E402
from cubot.viz import contact_sheet  # noqa: E402

Cell = tuple[int, int, int]
MANIFEST_SCHEMA = "cubot.handoff.manifest.v1"


# --------------------------------------------------------------------------- masks


def read_layers(path: Path) -> list[list[str]]:
    """Layers bottom-first, each a list of rows top-first."""

    layers: list[list[str]] = []
    current: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip().replace(" ", "")
        if line.startswith("//"):
            continue
        if not line:
            if current:
                layers.append(current)
                current = []
            continue
        current.append(line)
    if current:
        layers.append(current)
    if not layers:
        raise ValueError(f"{path}: empty mask")
    return layers


def layer_cells(layers: list[list[str]]) -> tuple[Cell, ...]:
    cells: list[Cell] = []
    for z, rows in enumerate(layers):
        height = len(rows)
        for r, row in enumerate(rows):
            for x, char in enumerate(row):
                if char == "#":
                    cells.append((x, height - 1 - r, z))
                elif char != ".":
                    raise ValueError(f"layer {z} row {r}: unexpected {char!r}")
    return tuple(cells)


def cells_to_layers(cells: list[Cell] | tuple[Cell, ...]) -> list[str]:
    """Inverse of :func:`layer_cells`, normalised to the origin; blank rows separate layers."""

    arr = np.asarray(cells, dtype=int)
    arr = arr - arr.min(axis=0)
    span = arr.max(axis=0) + 1
    occupied = {tuple(c) for c in arr.tolist()}
    rows: list[str] = []
    for z in range(span[2]):
        if z:
            rows.append("")
        for y in range(span[1] - 1, -1, -1):
            rows.append("".join("#" if (x, y, z) in occupied else "." for x in range(span[0])))
    return rows


def canonical_3d(cells) -> tuple[Cell, ...]:
    """Cells up to the 24 lattice rotations and translation (the goal may be re-based)."""

    arr = np.asarray(sorted(cells), dtype=int)
    best: tuple[Cell, ...] | None = None
    for rotation in ORIENTS:
        rotated = arr @ np.asarray(rotation, dtype=int).T
        rotated = rotated - rotated.min(axis=0)
        key = tuple(sorted(tuple(int(v) for v in c) for c in rotated.tolist()))
        if best is None or key < best:
            best = key
    assert best is not None
    return best


def has_2x2x2_block(cells) -> bool:
    occupied = set(cells)
    return any(
        all((x + dx, y + dy, z + dz) in occupied for dx in (0, 1) for dy in (0, 1) for dz in (0, 1))
        for x, y, z in occupied
    )


def dims(cells) -> list[int]:
    arr = np.asarray(cells, dtype=int)
    return (arr.max(axis=0) - arr.min(axis=0) + 1).tolist()


# --------------------------------------------------------------------------- probe


def escape_probe(states: tuple[int, ...], base: int, machine, profile, *, hard_mm: float) -> dict:
    """Sweep every rest-overlap-free outgoing move from the goal (CAD only, one side).

    CAD penetration is symmetric in time, so a goal with no clean outgoing move
    has no clean closing move and can be discarded before any fold search.
    Gravity and the table are directional and are deliberately not measured here.
    """

    pose = Pose(states, machine.roll, base=base, lying=0)
    clean = 0
    tested = 0
    best = float("inf")
    for joint in range(machine.joints):
        for delta in (-1, 1):
            try:
                apply_detent(states, joint, delta)
            except ValueError:
                continue
            move = Move(joint, delta, "out")
            if not _rest_report(next_pose(pose, move), machine).hard_ok:
                continue
            tested += 1
            depth = sweep(pose, move, machine, profile).max_depth_mm
            best = min(best, depth)
            if depth <= hard_mm + 1e-6:
                clean += 1
    return {"tested": tested, "clean": clean, "min_penetration_mm": None if best == float("inf") else round(best, 3)}


# --------------------------------------------------------------------------- backward certificate


def cad_only(pose: Pose, move: Move, machine, profile) -> CheckReport:
    """Rest overlap + sampled CAD sweep only.  Time-symmetric, so usable from the goal side."""

    try:
        apply_detent(pose.states, move.joint, move.delta)
    except ValueError as exc:
        return CheckReport(hard={"winding": (False, str(exc))})
    rest = _rest_report(next_pose(pose, move), machine)
    if not rest.hard_ok:
        return rest
    report = sweep(pose, move, machine, profile)
    ok = report.max_depth_mm <= profile.hard_penetration_mm + 1e-6
    return merge_reports(
        rest,
        CheckReport(
            hard={"cad_penetration": (ok, f"max CAD penetration {report.max_depth_mm:.3f} mm (limit {profile.hard_penetration_mm:.3f} mm)")},
            measurements={"max_penetration_mm": report.max_depth_mm},
        ),
    )


def backward_certificate(goal: Pose, machine, loose, *, time_budget_s: float, max_candidates: int = 6) -> PlanCandidate | None:
    """Unfold the goal to straight under CAD-only checks, then replay the reversed moves forward.

    Gravity, the table and the moving side are directional, so the backward
    search is only a route generator; the forward replay with the full loose
    checker (sides chosen greedily by the gravity selector, other side tried
    when the first fails a hard check) is the certificate.
    """

    straight = Pose((0,) * machine.joints, machine.roll, base=goal.base)
    result = fold(
        replace(goal, lying=0),
        straight,
        machine=machine,
        profile=loose,
        checker=cad_only,
        search_lying_faces=False,
        time_budget_s=time_budget_s,
        detour_budget=loose.detour_budget,
        max_candidates=max_candidates,
    )
    routes = [c for c in result.ranked() if c.complete and c.hard_ok]
    best: PlanCandidate | None = None
    for route in routes:
        reversed_moves = [(m.joint, -m.delta) for m in reversed(route.moves)]
        for start in lying_variants(Pose((0,) * machine.joints, machine.roll, base=0)):
            pose = start
            chosen: list[Move] = []
            for joint, delta in reversed_moves:
                sides = _default_side_selector(pose, joint, machine, loose)
                if len(sides) == 1:
                    sides = (sides[0], "out" if sides[0] == "in" else "in")
                picked = None
                for side in sides:
                    move = Move(joint, delta, side, machine.move_time_s)
                    report = check_move(pose, move, machine, loose)
                    if report.hard_ok:
                        picked = move
                        break
                    if picked is None:
                        picked = move
                chosen.append(picked)
                pose = next_pose(pose, picked)
            candidate = replay(
                start,
                chosen,
                goal=goal,
                machine=machine,
                profile=loose,
                notes=("backward CAD-only search from the goal, forward replay certificate",),
            )
            if candidate.complete and candidate.hard_ok:
                return candidate
            if best is None or candidate.rank_key < best.rank_key:
                best = candidate
    return best


def install_certificate(run_dir: Path, candidate: PlanCandidate, machine, loose, strict, *, seed: int) -> None:
    """Put a forward-certified plan at rank 0 of the run's record and reports."""

    strict_candidate = _strict_replays([candidate], machine=machine, profile=strict, checker=check_move)[0]
    record_path = run_dir / "record.json"
    record = json.loads(record_path.read_text())
    record["plans"].insert(0, _jsonable(candidate))
    record["status"] = "checked"
    record["pose"] = _jsonable(candidate.goal)
    record["cells"] = [list(c) for c in pose_cells(candidate.goal)]
    record.setdefault("notes", []).append("rank-0 plan certified by backward search + forward replay (tools/explore_3d.py)")
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    for name, cand in (("loose", candidate), ("strict", strict_candidate)):
        path = run_dir / f"{name}-report.json"
        report = json.loads(path.read_text())
        entry = _jsonable(cand)
        report["ranked"].insert(0, entry)
        bucket = "passing" if (cand.complete and cand.hard_ok) else "violating" if cand.complete else "partial"
        report[bucket].insert(0, entry)
        report["summary"] = {
            "candidates": len(report["ranked"]),
            "complete_passing": len(report["passing"]),
            "complete_violating": len(report["violating"]),
            "partial": len(report["partial"]),
            "hard_ok": bool(report["passing"]),
        }
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    source_hash = record["meta"]["source_hash"]
    dump_json(
        _raw_plan(candidate, strict_candidate, machine=machine, loose=loose, strict=strict, seed=seed, source_hash=source_hash),
        run_dir / "checked-plan.json",
    )


# --------------------------------------------------------------------------- render


def render_voxels(
    cells,
    out_path: Path,
    *,
    scale: int = 30,
    margin: int = 40,
    color: tuple[int, int, int] = (56, 96, 150),
    shadow: bool = True,
) -> Path:
    """Isometric painter's-algorithm render of solid unit cubes (z up, gravity down).

    ``cubot.viz.render_iso`` draws exploded small cubes for flat icons; solid
    3-D targets read better as touching cubes with per-face shading.
    """

    arr = np.asarray(cells, dtype=int)
    arr = arr - arr.min(axis=0)
    ax, ay, az = scale * 0.866, scale * 0.5, scale * 1.0

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return ((x - y) * ax, (x + y) * ay - z * az)

    corners = [project(*c) for c in itertools.product(*[(0, s + 1) for s in arr.max(axis=0)])]
    min_x = min(c[0] for c in corners)
    min_y = min(c[1] for c in corners)
    width = int(max(c[0] for c in corners) - min_x + 2 * margin)
    height = int(max(c[1] for c in corners) - min_y + 2 * margin)
    image = Image.new("RGB", (width, height), (248, 247, 243))
    draw = ImageDraw.Draw(image)

    def screen_pt(x: float, y: float, z: float) -> tuple[float, float]:
        px, py = project(x, y, z)
        return (px - min_x + margin, py - min_y + margin)

    if shadow:
        footprint = {(int(x), int(y)) for x, y, _ in arr.tolist()}
        for x, y in footprint:
            draw.polygon(
                [screen_pt(x, y, 0), screen_pt(x + 1, y, 0), screen_pt(x + 1, y + 1, 0), screen_pt(x, y + 1, 0)],
                fill=(214, 212, 205),
            )

    shade = {
        "top": color,
        "x": tuple(max(0, c - 40) for c in color),
        "y": tuple(max(0, c - 70) for c in color),
    }
    occupied = {tuple(c) for c in arr.tolist()}
    order = sorted(occupied, key=lambda c: (c[0] + c[1] + c[2], c[2]))
    outline = (30, 34, 40)
    for x, y, z in order:
        if (x, y, z + 1) not in occupied:
            draw.polygon(
                [screen_pt(x, y, z + 1), screen_pt(x + 1, y, z + 1), screen_pt(x + 1, y + 1, z + 1), screen_pt(x, y + 1, z + 1)],
                fill=shade["top"],
                outline=outline,
            )
        if (x + 1, y, z) not in occupied:
            draw.polygon(
                [screen_pt(x + 1, y, z), screen_pt(x + 1, y + 1, z), screen_pt(x + 1, y + 1, z + 1), screen_pt(x + 1, y, z + 1)],
                fill=shade["x"],
                outline=outline,
            )
        if (x, y + 1, z) not in occupied:
            draw.polygon(
                [screen_pt(x, y + 1, z), screen_pt(x + 1, y + 1, z), screen_pt(x + 1, y + 1, z + 1), screen_pt(x, y + 1, z + 1)],
                fill=shade["y"],
                outline=outline,
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


# --------------------------------------------------------------------------- explore


def tracked_final(plan: dict) -> Pose | None:
    if not plan.get("complete"):
        return None
    raw = plan["start"]
    pose = Pose(tuple(int(s) for s in raw["states"]), raw["roll"], int(raw["base"]), raw.get("lying"))
    for move in plan["moves"]:
        pose = next_pose(pose, Move(int(move["joint"]), int(move["delta"]), move["side"], float(move["duration_s"])))
    return pose


def gate(name: str, mask_path: Path, machine) -> tuple[dict, list[tuple[tuple[int, ...], int]]]:
    layers = read_layers(mask_path)
    cells = layer_cells(layers)
    row: dict = {
        "name": name,
        "variant": mask_path.stem,
        "mask": str(mask_path),
        "mask_layers": ["\n".join(layer) for layer in layers],
        "dims": dims(cells) if cells else [0, 0, 0],
        "cells": len(cells),
        "screen_ok": False,
        "screen_stage": None,
        "screen_reason": None,
        "threadings": 0,
        "words": 0,
        "thread_status": None,
        "probe": [],
        "complete": None,
        "hard_ok": None,
        "violations": [],
        "moves": None,
        "worst_soft": None,
        "scores": {},
        "goal_is_mask": None,
        "final_dims": None,
        "final_balance_margin_mm": None,
        "peak_demand_nm": None,
        "voxel_png": None,
        "record_json": None,
        "run_dir": None,
        "fold_statuses": [],
        "elapsed_s": 0.0,
    }
    report = screen(cells, 27)
    row["screen_ok"] = report.ok
    row["screen_stage"] = report.stage
    row["screen_reason"] = report.reason
    if report.ok and has_2x2x2_block(cells):
        # A filled 2x2x2 block is a solid in disguise: its closing move measures
        # the 22 mm hinge-corner sweep of docs/CUBE_FEASIBILITY.md every time.
        row["screen_ok"] = False
        row["screen_stage"] = "two-thick"
        row["screen_reason"] = "contains a filled 2x2x2 block; only one-thick shells close"
    if not row["screen_ok"]:
        return row, []
    threaded = solve(cells, machine.roll, all_solutions=True, max_solutions=64, tether=machine.has_tether)
    row["thread_status"] = threaded.status.value
    row["threadings"] = len(threaded.solutions)
    words: dict[tuple[int, ...], int] = {}
    for threading in threaded.solutions:
        words.setdefault(threading.states, threading.base)
    row["words"] = len(words)
    return row, list(words.items())


def probe_words(row: dict, words, machine, *, limit: int, hard_mm: float) -> list[dict]:
    probe_profile = load_profile("report")  # 8-degree sampling, no thresholds: depths only
    probed = []
    for states, base in words[:limit]:
        result = escape_probe(states, base, machine, probe_profile, hard_mm=hard_mm)
        probed.append({"states": list(states), "base": base, **result})
    probed.sort(key=lambda item: (-item["clean"], item["min_penetration_mm"] or 0.0))
    row["probe"] = probed
    return probed


def explore_one(job: dict) -> dict:
    name = job["name"]
    mask_path = Path(job["mask"])
    out_root = Path(job["out"])
    started = time.monotonic()
    machine = load_machine()
    row, words = gate(name, mask_path, machine)
    if not words:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row
    probed = probe_words(row, words, machine, limit=job["probe_words"], hard_mm=job["hard_mm"])
    if job["gate_only"] or job["probe_only"]:
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row
    survivors = [item for item in probed if item["clean"] > 0][: job["k"]]
    if not survivors:
        row["fold_statuses"] = ["skipped: no CAD-clean escape move from any probed threading"]
        row["elapsed_s"] = round(time.monotonic() - started, 2)
        return row

    layers = read_layers(mask_path)
    cells = layer_cells(layers)
    # ``run_pipeline`` wants a pixel target for its records and 2-D renders; the
    # projection stands in for it and the record is annotated with the layers.
    arr = np.asarray(cells, dtype=int)
    spans = arr.max(axis=0) - arr.min(axis=0)
    axes = sorted(range(3), key=lambda axis: (-int(spans[axis]), axis))[:2]
    grid = np.zeros((int(spans[axes[1]]) + 1, int(spans[axes[0]]) + 1), dtype=bool)
    for cell in arr - arr.min(axis=0):
        grid[int(spans[axes[1]]) - int(cell[axes[1]]), int(cell[axes[0]])] = True
    target = PixelTarget(grid=grid, concept=name, caption=f"A three-dimensional lattice model of {name.replace('-', ' ')}", source="explore-3d")

    exact: list[MatchResult] = []
    for item in survivors:
        pose = Pose(tuple(item["states"]), machine.roll, base=int(item["base"]))
        exact.append(MatchResult(pose, tuple(fk(pose.states, machine.roll, base=pose.base)[0]), 0.0, "exact-3d", "identity"))

    run_dir = out_root / "runs" / mask_path.stem
    run = run_pipeline(
        target,
        run_dir,
        machine=machine,
        profile=job["profile"],
        family=None,
        match_results=exact,
        seed=job["seed"],
        k=len(exact),
        time_budget_s=job["time_budget"],
        max_candidates=job["max_candidates"],
        include_heart_certificate=False,
    )
    record_path = run.record_path
    record = json.loads(record_path.read_text())
    plans = record.get("plans", [])
    row["fold_statuses"] = list(run.fold_statuses)
    if job["backward"] and not (plans and plans[0]["complete"] and plans[0]["hard_ok"]):
        loose = load_profile(job["profile"])
        strict = load_profile("strict")
        certified = None
        for item in survivors:
            goal = Pose(tuple(item["states"]), machine.roll, base=int(item["base"]))
            certified = backward_certificate(goal, machine, loose, time_budget_s=job["backward_budget"])
            if certified is not None and certified.complete and certified.hard_ok:
                break
        if certified is not None and certified.complete and certified.hard_ok:
            install_certificate(record_path.parent, certified, machine, loose, strict, seed=job["seed"])
            record = json.loads(record_path.read_text())
            row["fold_statuses"].append("backward certificate: PASS")
        else:
            row["fold_statuses"].append(
                "backward certificate: none"
                if certified is None
                else f"backward certificate: best forward replay {'complete' if certified.complete else 'partial'}, violations {certified.violations[:2]}"
            )
    record["target"] = cells_to_layers(cells)
    record.setdefault("notes", []).append(
        "3-D target: 'target' rows are z-layers bottom-first separated by blank rows (tools/explore_3d.py)"
    )
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    row["record_json"] = str(record_path)
    row["run_dir"] = str(record_path.parent)
    row["profile"] = job["profile"]
    plans = record.get("plans", [])
    if plans:
        best = plans[0]  # rank-ordered; rank 0 is the shipped path
        row["complete"] = bool(best["complete"])
        row["hard_ok"] = bool(best["hard_ok"])
        row["violations"] = list(best.get("violations", []))
        row["moves"] = len(best["moves"])
        row["scores"] = {key: round(float(value), 3) for key, value in best.get("scores", {}).items()}
        row["worst_soft"] = round(min(best["scores"].values()), 3) if best.get("scores") else None
        goal = best["goal"]
        goal_cells = fk(tuple(goal["states"]), goal["roll"], int(goal["base"]))[0]
        row["goal_is_mask"] = canonical_3d(goal_cells) == canonical_3d(cells)
        if best["moves"]:
            measurements = best["moves"][-1]["checks"].get("measurements", {})
            row["final_balance_margin_mm"] = measurements.get("balance_margin_mm")
            row["peak_demand_nm"] = max(
                float(m["checks"].get("measurements", {}).get("peak_demand_nm", 0.0)) for m in best["moves"]
            )
        final = tracked_final(best)
        shown = final if final is not None else Pose(tuple(goal["states"]), goal["roll"], int(goal["base"]))
        final_cells = fk(shown.states, shown.roll, shown.base)[0]
        row["final_dims"] = dims(final_cells)
        row["voxel_png"] = str(render_voxels(final_cells, record_path.parent / "renders" / "voxels.png"))
    row["elapsed_s"] = round(time.monotonic() - started, 2)
    return row


def summary_line(row: dict) -> str:
    tag = f"{row['name']}/{row['variant']}"
    if not row["screen_ok"]:
        return f"{tag}: STRUCTURAL FAIL at {row['screen_stage']} — {row['screen_reason']}"
    if not row["threadings"]:
        return f"{tag}: roll-{row['thread_status']} (0 threadings)"
    probe = ", ".join(f"{p['clean']}/{p['tested']}" for p in row["probe"][:4])
    head = f"{tag}: {row['threadings']} threadings / {row['words']} words, clean escapes [{probe}]"
    if row["complete"] is None:
        return head + (f" — {row['fold_statuses']}" if row["fold_statuses"] else "")
    verdict = "PASS" if (row["complete"] and row["hard_ok"]) else ("complete but violating" if row["complete"] else "partial")
    return (
        f"{head}; {verdict}, {row['moves']} moves, worst soft {row['worst_soft']}, "
        f"final dims {row['final_dims']}, balance {row['final_balance_margin_mm']}, peak {row['peak_demand_nm']} Nm"
        + (f", violations={row['violations'][:3]}" if row["violations"] else "")
        + ("" if row["goal_is_mask"] else " [GOAL != MASK]")
        + f" ({row['elapsed_s']} s) -> {row['voxel_png']}"
    )


# --------------------------------------------------------------------------- summary


def rank_key(row: dict) -> tuple:
    """Lower is better: passing < complete-violating < partial < threadable-no-plan < UNSAT < structural."""

    if not row["screen_ok"]:
        return (5, 0, 0, 0)
    if not row["threadings"]:
        return (4, 0, 0, 0)
    if row["complete"] is None:
        return (3, -max((p["clean"] for p in row["probe"]), default=0), 0, 0)
    if row["complete"] and row["hard_ok"]:
        klass = 0 if row.get("profile", "loose") == "loose" else 1
    elif row["complete"]:
        klass = 2
    else:
        klass = 3
    return (klass, -(row["worst_soft"] or 0.0), row["moves"] or 999, 0)


def verdict(row: dict) -> str:
    if not row["screen_ok"]:
        return f"structural: {row['screen_stage']}"
    if not row["threadings"]:
        return f"roll-{row['thread_status']}"
    if row["complete"] is None:
        return "threadable, no plan" if not row["fold_statuses"] else "threadable, " + ("no clean escape" if "skipped" in row["fold_statuses"][0] else "no plan")
    if row["complete"] and row["hard_ok"]:
        return "PASS"
    if row["complete"]:
        return "complete, violating"
    return "partial"


def write_summary(out_root: Path, only: set[str] | None) -> None:
    rows: list[dict] = []
    for path in sorted(out_root.rglob("results.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"no results under {out_root}")
    best: dict[str, dict] = {}
    for row in rows:
        if row["name"] not in best or rank_key(row) < rank_key(best[row["name"]]):
            best[row["name"]] = row
    ordered = sorted(best.values(), key=rank_key)

    lines = [
        f"# 3-D exploration — {out_root.name}",
        "",
        f"{len(rows)} mask runs, {len(best)} concepts.  Best variant per concept; ``PASS`` = complete, loose hard checks OK, goal is the mask.",
        "",
        "| # | concept | variant | profile | dims | verdict | moves | worst soft | balance mm | peak Nm | clean escapes | violations |",
        "|---|---------|---------|---------|------|---------|------:|-----------:|-----------:|--------:|---------------|------------|",
    ]
    entries: list[tuple[str, Path]] = []
    manifest: list[dict] = []
    number = 0
    for row in ordered:
        clean = ", ".join(str(p["clean"]) for p in row["probe"][:4]) or "-"
        balance = row["final_balance_margin_mm"]
        lines.append(
            f"| {len(lines) - 5} | {row['name']} | {row['variant']} | {row.get('profile', 'loose')} | {'x'.join(map(str, row['final_dims'] or row['dims']))} | "
            f"{verdict(row)} | {row['moves'] or ''} | {row['worst_soft'] if row['worst_soft'] is not None else ''} | "
            f"{'' if balance is None else round(float(balance), 1)} | {'' if row['peak_demand_nm'] is None else round(float(row['peak_demand_nm']), 2)} | "
            f"{clean} | {'; '.join(row['violations'][:2])} |"
        )
        if row["complete"] and row["hard_ok"] and row["goal_is_mask"] and row["voxel_png"]:
            if only is not None and row["name"] not in only:
                continue
            if row.get("profile", "loose") != "loose":
                continue  # platform-tier passes are reported, never handed off as loose
            number += 1
            entries.append((row["name"], Path(row["voxel_png"])))
            run_dir = Path(row["run_dir"])
            manifest.append({"name": row["name"], "run": str(run_dir.resolve().relative_to(out_root.resolve())), "variant": row["variant"]})
    (out_root / "summary.md").write_text("\n".join(lines) + "\n")
    if entries:
        contact_sheet(entries, out_root / "contact-sheet-blind.png", show_labels=False, tile=(360, 380))
        contact_sheet(entries, out_root / "contact-sheet-labeled.png", show_labels=True, tile=(360, 380))
    (out_root / "handoff-manifest.json").write_text(
        json.dumps({"schema": MANIFEST_SCHEMA, "generated_by": "tools/explore_3d.py --summary", "shapes": manifest}, indent=2) + "\n"
    )
    print(f"{len(rows)} rows, {len(best)} concepts, {len(manifest)} loose-passing exact 3-D shapes -> {out_root / 'summary.md'}")


# --------------------------------------------------------------------------- cli


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("masks", nargs="*", type=Path, help="layered mask files (bottom layer first)")
    parser.add_argument("--name", help="concept name; defaults to the mask stem before '-v'")
    parser.add_argument("--out", type=Path, default=Path("out/explore3d"))
    parser.add_argument("--time-budget", type=float, default=150.0, help="total fold-search seconds per mask")
    parser.add_argument("-k", type=int, default=2, help="threadings folded per mask (best escape probes first)")
    parser.add_argument("--probe-words", type=int, default=8, help="distinct state words to escape-probe per mask")
    parser.add_argument("--hard-mm", type=float, default=None, help="escape-probe penetration limit (default: loose)")
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1, help="parallel masks (keep <= 3 for folds)")
    parser.add_argument("--profile", default="loose", help="working check profile (loose; 'platform' removes the table)")
    parser.add_argument("--backward", action="store_true", help="on a non-passing fold, try goal-side CAD-only search + forward replay")
    parser.add_argument("--backward-budget", type=float, default=150.0, help="seconds for the backward search per threading")
    parser.add_argument("--gate-only", action="store_true", help="screen + thread + probe; never fold")
    parser.add_argument("--probe-only", action="store_true", help="alias of --gate-only")
    parser.add_argument("--summary", action="store_true", help="summarize <out> instead of exploring")
    parser.add_argument("--only", nargs="*", help="with --summary: restrict the manifest to these names")
    args = parser.parse_args()

    if args.summary:
        write_summary(args.out, None if args.only is None else set(args.only))
        return 0
    if not args.masks:
        parser.error("no masks given")
    hard_mm = args.hard_mm if args.hard_mm is not None else load_profile("loose").hard_penetration_mm
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = [
        {
            "name": args.name or mask.stem.split("-v")[0],
            "mask": str(mask),
            "out": str(args.out),
            "probe_words": args.probe_words,
            "hard_mm": hard_mm,
            "gate_only": args.gate_only,
            "probe_only": args.probe_only,
            "k": args.k,
            "time_budget": args.time_budget,
            "max_candidates": args.max_candidates,
            "seed": args.seed,
            "backward": args.backward,
            "profile": args.profile,
            "backward_budget": args.backward_budget,
        }
        for mask in args.masks
    ]
    results_path = args.out / "results.jsonl"
    exit_code = 2
    if args.workers > 1:
        with Pool(args.workers) as pool:
            iterator = pool.imap_unordered(explore_one, jobs)
            rows = list(_consume(iterator, results_path, args.gate_only or args.probe_only))
    else:
        rows = list(_consume(map(explore_one, jobs), results_path, args.gate_only or args.probe_only))
    if any(row["complete"] and row["hard_ok"] for row in rows) or (
        (args.gate_only or args.probe_only) and any(row["threadings"] for row in rows)
    ):
        exit_code = 0
    return exit_code


def _consume(rows, results_path: Path, dry: bool):
    for row in rows:
        if not dry:
            with results_path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
        print(summary_line(row), flush=True)
        yield row


if __name__ == "__main__":
    raise SystemExit(main())
