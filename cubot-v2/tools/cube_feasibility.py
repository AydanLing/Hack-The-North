#!/usr/bin/env python3
"""Measure why a packed 3x3x3 cannot be entered by a single-detent move.

Three independent measurements, all using the planner's own kinematics and
sampled CAD sweep:

``escape``
    Enumerate every shipped-roll threading of the 3x3x3, then sweep every
    outgoing single-detent move (both sides) from each threading and report
    the minimum CAD penetration among moves that do not end in a rest-cell
    overlap.  This is the goal-side escape measurement from
    ``CUBOT_V2_PLAN.md`` A.3 extended to all threadings and to millimetres.

``last-module``
    Roll-word-independent: place a hinge module in every cube cell with every
    one of the 24 orientations and swing one last module from outside into
    the cube.  Reports the minimum penetration over all 864 configurations
    and names the colliding pair, which is what makes the result explainable
    (hinge-half corners vs. the third face cell; the swung module's arc vs.
    the cells on the opposite side).

``lattice``
    Sanity check that the obstacle is continuous geometry and not lattice
    kinematics: run the folder with a rest-overlap-only checker and report
    that complete single-detent paths to the cube exist.

Usage (from ``cubot-v2/``)::

    uv run python tools/cube_feasibility.py last-module
    uv run python tools/cube_feasibility.py lattice
    uv run python tools/cube_feasibility.py escape --workers 8   # ~10 min
"""

from __future__ import annotations

import argparse
import itertools
import math
from multiprocessing import Pool
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402
from cubot.folder import _rest_report, fold, next_pose  # noqa: E402
from cubot.geometry import (  # noqa: E402
    DETENT_RAD,
    Transform,
    _overlap_prepared,
    _prepare,
    rotation_about_axis,
    sweep,
)
from cubot.lattice import DIRS, ORIENTS, POST, apply_detent, pose_cells  # noqa: E402
from cubot.records import Move, Pose  # noqa: E402
from cubot.solid import JOINT_AXIS, MODULE_SOLID  # noqa: E402
from cubot.solver import solve  # noqa: E402

CUBE = tuple(itertools.product(range(3), repeat=3))


def cube_threadings(roll: str) -> dict[tuple[int, ...], int]:
    """All distinct physical state words that thread the 3x3x3 under ``roll``."""

    result = solve(
        CUBE, roll, budget_nodes=50_000_000, deadline_s=600, all_solutions=True, max_solutions=100_000
    )
    words: dict[tuple[int, ...], int] = {}
    for threading in result.solutions:
        words.setdefault(threading.states, threading.base)
    return words


def _escape_one(job):
    states, base, joint, delta, side, profile_name = job
    machine = load_machine()
    profile = load_profile(profile_name)
    pose = Pose(states, machine.roll, base=base, lying=0)
    move = Move(joint, delta, side)
    cells = pose_cells(next_pose(pose, move))
    overlap = len(cells) - len(set(cells))
    report = sweep(pose, move, machine, profile)
    return joint, delta, side, overlap, report.max_depth_mm, report.max_pair


def run_escape(workers: int) -> None:
    machine = load_machine()
    words = cube_threadings(machine.roll)
    print(f"threadings under shipped roll: {len(words)}")
    jobs = []
    for states, base in words.items():
        for joint in range(machine.joints):
            for delta in (-1, 1):
                try:
                    apply_detent(states, joint, delta)
                except ValueError:
                    continue
                for side in ("in", "out"):
                    jobs.append((states, base, joint, delta, side, "loose"))
    started = time.time()
    with Pool(workers) as pool:
        rows = pool.map(_escape_one, jobs, chunksize=4)
    clean = sorted((row for row in rows if row[3] == 0), key=lambda row: row[4])
    print(f"{len(rows)} move evaluations in {time.time() - started:.0f}s; {len(clean)} without rest overlap")
    print(f"minimum CAD penetration over overlap-free moves: {clean[0][4]:.3f} mm (pair {clean[0][5]})")
    print(f"maximum: {clean[-1][4]:.3f} mm")


def run_last_module() -> None:
    machine = load_machine()
    pitch = machine.pitch_mm
    solid = MODULE_SOLID
    cube = set(CUBE)
    results = []
    for cell in cube:
        for orientation in range(24):
            rotation = ORIENTS[orientation].astype(float)
            axis = rotation @ JOINT_AXIS
            for state in range(3):
                for delta in (-1, 1):
                    next_state = (state + delta) % 3
                    start = tuple(int(cell[i] + DIRS[orientation, state][i]) for i in range(3))
                    end = tuple(int(cell[i] + DIRS[orientation, next_state][i]) for i in range(3))
                    if start in cube or end not in cube:
                        continue
                    static = {}
                    for other in cube:
                        if other in (cell, end):
                            continue
                        static[("full", other)] = _prepare(
                            solid.full, Transform(np.eye(3), np.asarray(other, float) * pitch)
                        )
                    static[("still", cell)] = _prepare(
                        solid.still, Transform(rotation, np.asarray(cell, float) * pitch)
                    )
                    pivot = np.asarray(cell, float) * pitch
                    moving_rest = rotation @ rotation_about_axis(JOINT_AXIS, state * DETENT_RAD)
                    last = ORIENTS[int(POST[orientation, state, 0])].astype(float)
                    centre = np.asarray(start, float) * pitch
                    worst: dict[tuple, tuple[float, float]] = {}
                    for angle in np.linspace(0.0, 120.0, 61):
                        world = rotation_about_axis(axis, math.radians(float(angle)) * delta)
                        movers = {
                            "hinge-half": _prepare(solid.moving, Transform(world @ moving_rest, pivot)),
                            "last-module": _prepare(
                                solid.full, Transform(world @ last, (centre - pivot) @ world.T + pivot)
                            ),
                        }
                        for mover_name, mover in movers.items():
                            for static_name, body in static.items():
                                depth = _overlap_prepared(body, mover)
                                key = (mover_name, static_name)
                                if depth > worst.get(key, (0.0, 0.0))[0]:
                                    worst[key] = (depth, float(angle))
                    peak = max((value[0] for value in worst.values()), default=0.0)
                    results.append((peak, cell, orientation, start, end, worst))
    results.sort(key=lambda item: item[0])
    print(f"configurations: {len(results)}")
    best = results[0]
    print(f"minimum peak penetration: {best[0]:.2f} mm (hinge {best[1]}, orientation {best[2]}, last module {best[3]} -> {best[4]})")
    for key, (depth, angle) in sorted(best[5].items(), key=lambda kv: -kv[1][0])[:4]:
        print(f"  {key[0]} vs {key[1]}: {depth:.2f} mm at {angle:.0f} deg")


def run_lattice() -> None:
    machine = load_machine()
    profile = load_profile("loose")
    words = cube_threadings(machine.roll)

    def rest_only(pose, move, machine, profile):
        return _rest_report(next_pose(pose, move))

    start = Pose((0,) * machine.joints, machine.roll, base=0, lying=None)
    for index, (states, base) in enumerate(words.items()):
        goal = Pose(states, machine.roll, base=base)
        result = fold(
            start,
            goal,
            machine=machine,
            profile=profile,
            checker=rest_only,
            node_budget=300_000,
            time_budget_s=120,
            detour_budget=6,
            max_candidates=1,
        )
        best = result.ranked()[0] if result.candidates else None
        print(
            f"threading {index}: {result.status.value} complete={bool(best and best.complete)} "
            f"moves={len(best.moves) if best else None}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiment", choices=("escape", "last-module", "lattice"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.experiment == "escape":
        run_escape(args.workers)
    elif args.experiment == "last-module":
        run_last_module()
    else:
        run_lattice()


if __name__ == "__main__":
    main()
