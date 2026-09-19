#!/usr/bin/env python3
"""Replay and verify a CuBot handoff ``path.json`` with no dependencies.

Pure Python 3.10+, integer arithmetic only.  It rebuilds the lattice kinematics
from the two generator matrices in the README, replays the moves, and checks
that every stored number in the file is reproducible:

* joint states stay in {-1, 0, +1} and each move is exactly one detent;
* the moves reach ``goal.states``;
* forward kinematics of ``goal`` reproduces ``goal.cells`` and is self-avoiding;
* every ``moves[i].cells_after`` / ``base_after`` is reproduced, including the
  base re-orientation caused by ``in`` moves;
* the snake_pipeline cell list is the axis-relabelled goal.

Usage::

    python3 tools/replay.py shapes/01-heart/path.json            # verify + print
    python3 tools/replay.py shapes/*/path.json --quiet            # verify all
    python3 tools/replay.py shapes/06-t/path.json --steps         # ASCII after every move
    python3 tools/replay.py shapes/02-arrow/path.json --emit-moves  # compact move list
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

Matrix = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
Vec = tuple[int, int, int]

I3: Matrix = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
J: Matrix = ((0, 0, 1), (1, 0, 0), (0, 1, 0))       # +120 deg about (1,1,1): x->y->z->x
RX: Matrix = ((1, 0, 0), (0, 0, -1), (0, 1, 0))     # +90 deg about local +x
X_HAT: Vec = (1, 0, 0)


def matmul(a: Matrix, b: Matrix) -> Matrix:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]


def matvec(a: Matrix, v: Vec) -> Vec:
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]


def transpose(a: Matrix) -> Matrix:
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def mpow(a: Matrix, n: int) -> Matrix:
    out = I3
    for _ in range(n):
        out = matmul(out, a)
    return out


def group_closure(generators: list[Matrix]) -> list[Matrix]:
    """Breadth-first right-multiplication closure; this ordering IS the base index."""

    elements = [I3]
    seen = {I3}
    cursor = 0
    while cursor < len(elements):
        for g in generators:
            candidate = matmul(elements[cursor], g)
            if candidate not in seen:
                seen.add(candidate)
                elements.append(candidate)
        cursor += 1
    return elements


ORIENTS = group_closure([J, RX])
ORIENT_INDEX = {m: i for i, m in enumerate(ORIENTS)}
assert len(ORIENTS) == 24


def fk(states: list[int], roll: str, base: int) -> tuple[list[Vec], list[Matrix]]:
    """Integer forward kinematics: module cells (lattice units) and world orientation matrices."""

    if len(states) != 26 or len(roll) != 26:
        raise ValueError("expected 26 joint states and a 26-digit roll word")
    M = ORIENTS[base]
    cell: Vec = (0, 0, 0)
    cells = [cell]
    frames = [M]
    for s, r in zip(states, roll):
        after_joint = matmul(M, mpow(J, s % 3))
        d = matvec(after_joint, X_HAT)
        cell = (cell[0] + d[0], cell[1] + d[1], cell[2] + d[2])
        M = matmul(after_joint, mpow(RX, int(r)))
        cells.append(cell)
        frames.append(M)
    return cells, frames


def advance(states: list[int], base: int, roll: str, joint: int, delta: int, side: str) -> tuple[list[int], int]:
    """Apply one detent.  An ``in`` move keeps the tail fixed, so the base re-orients."""

    if delta not in (-1, 1):
        raise ValueError("delta must be -1 or +1")
    new_states = list(states)
    new_states[joint] += delta
    if new_states[joint] not in (-1, 0, 1):
        raise ValueError(f"joint {joint} would leave the physical range [-1, +1]")
    if side == "out":
        return new_states, base
    if side != "in":
        raise ValueError(f"unknown side {side!r}")
    # World hinge axis of joint j is M_j (1,1,1).  Rotating the base side by
    # -delta*120 deg about it is M_j J^{-delta} M_j^T in integer form.
    _, frames = fk(states, roll, base)
    M_j = frames[joint]
    root_motion = matmul(matmul(M_j, mpow(J, (-delta) % 3)), transpose(M_j))
    return new_states, ORIENT_INDEX[matmul(root_motion, ORIENTS[base])]


def silhouette(cells: list[Vec]) -> list[str]:
    xs, ys, zs = zip(*cells)
    spans = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    axes = [i for i in range(3) if spans[i] > 0]
    if len(axes) != 2:
        return [f"(not planar: lattice span {spans})"]
    a, b = axes
    occ = {(c[a], c[b]) for c in cells}
    lo_a, hi_a = min(c[a] for c in cells), max(c[a] for c in cells)
    lo_b, hi_b = min(c[b] for c in cells), max(c[b] for c in cells)
    return ["".join("#" if (i, j) in occ else "." for i in range(lo_a, hi_a + 1)) for j in range(hi_b, lo_b - 1, -1)]


def verify(path: Path, *, quiet: bool, steps: bool, emit_moves: bool) -> bool:
    data = json.loads(path.read_text())
    problems: list[str] = []
    roll = data["machine"]["roll"]
    states = list(data["start"]["states"])
    base = int(data["start"]["base"])
    if any(s not in (-1, 0, 1) for s in states):
        problems.append("start states outside {-1,0,+1}")

    start_cells, _ = fk(states, roll, base)
    if [list(c) for c in start_cells] != data["start"]["cells"]:
        problems.append("start cells do not match FK")

    for move in data["moves"]:
        try:
            states, base = advance(states, base, roll, move["joint"], move["delta"], move["side"])
        except ValueError as exc:
            problems.append(f"step {move['step']}: {exc}")
            break
        if states != move["states_after"]:
            problems.append(f"step {move['step']}: states_after mismatch")
        if base != move["base_after"]:
            problems.append(f"step {move['step']}: base_after mismatch (replay {base}, file {move['base_after']})")
        cells, _ = fk(states, roll, base)
        if [list(c) for c in cells] != move["cells_after"]:
            problems.append(f"step {move['step']}: cells_after mismatch")
        if len(set(cells)) != 27:
            problems.append(f"step {move['step']}: rest pose is not self-avoiding")
        if steps:
            print(f"-- after step {move['step']}: joint {move['joint']} {move['delta']:+d} side={move['side']} base={base}")
            print("\n".join(silhouette(cells)))

    goal = data["goal"]
    if states != goal["states"]:
        problems.append("moves do not reach goal.states")
    goal_cells, _ = fk(goal["states"], roll, goal["base"])
    if [list(c) for c in goal_cells] != goal["cells"]:
        problems.append("goal cells do not match FK")
    if len(set(goal_cells)) != 27:
        problems.append("goal is not self-avoiding")

    tracked = data["final_tracked"]
    if base != tracked["base"]:
        problems.append(f"final tracked base mismatch (replay {base}, file {tracked['base']})")
    tracked_cells, _ = fk(states, roll, base)
    zs = [c[2] for c in tracked_cells]
    if (max(zs) - min(zs) == 0) != tracked["ends_flat_on_table"]:
        problems.append("ends_flat_on_table flag disagrees with replay")

    sp = data["snake_pipeline"]
    M = sp["axis_map_v2_to_snake_pipeline"]
    relabelled = [[sum(M[i][k] * c[k] for k in range(3)) for i in range(3)] for c in goal["cells"]]
    if relabelled != sp["cells_chain_frame"]:
        problems.append("snake_pipeline cells are not the relabelled goal cells")
    if sp["goal_states_mod3_27"] != [s % 3 for s in goal["states"]] + [0]:
        problems.append("snake_pipeline states are not goal states mod 3")

    ok = not problems
    if not quiet or not ok:
        print(f"== {data['demo_number']}. {data['name']}  ({len(data['moves'])} moves, "
              f"loose_hard_ok={data['status']['loose_hard_ok']}, ends_flat={tracked['ends_flat_on_table']})")
        print("\n".join(silhouette(goal_cells)))
        if not tracked["ends_flat_on_table"]:
            print(f"   NOTE: predicted to finish standing (lattice span {tracked['lattice_span']}), not lying flat")
        for violation in data["status"]["loose_violations"]:
            print(f"   loose violation: {violation}")
    if emit_moves:
        print("moves = [" + ", ".join(f"({m['joint']}, {m['delta']:+d}, {m['side']!r})" for m in data["moves"]) + "]")
    if problems:
        for problem in problems:
            print(f"   FAIL: {problem}")
    elif not quiet:
        print("   verified: moves reach goal; every stored pose/cell/base reproduced")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--quiet", action="store_true", help="only print failures")
    parser.add_argument("--steps", action="store_true", help="print the silhouette after every move")
    parser.add_argument("--emit-moves", action="store_true", help="print the compact (joint, delta, side) list")
    args = parser.parse_args()
    all_ok = True
    for path in args.paths:
        all_ok &= verify(path, quiet=args.quiet, steps=args.steps, emit_moves=args.emit_moves)
    if args.quiet and all_ok:
        print(f"all {len(args.paths)} path files verified")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
