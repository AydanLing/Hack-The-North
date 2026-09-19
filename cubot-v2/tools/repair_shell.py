#!/usr/bin/env python3
"""Gate layered (3D) masks and repair roll-UNSAT ones by single-cell perturbation.

Layered masks are z-slices, top layer first, separated by ``---`` lines
(:func:`cubot.shapes.parse_layers`).  ``gate`` prints, per mask, the structural
screen verdict, the exact shipped-roll threading count, whether the drawing
hides a filled 2x2x2 block (a two-thick solid in disguise — always rejected,
``docs/CUBE_FEASIBILITY.md``), the dense-cell count and whether it is really
volumetric (all three lattice spans > 0).

``repair`` takes an UNSAT base mask and enumerates every (remove one cell, add
one frontier cell) variant, skips 2x2x2 blocks and structural failures, threads
the rest, and writes the threadable ones as ``<out>/<name>-rN.txt`` plus an
iso render so a designer can check the concept survived.  Hand-drawn 3D shells
thread ~30 % of the time; a single-cell repair finds variants for most UNSAT
concepts in 20–40 s.

Usage (from ``cubot-v2/``)::

    uv run python tools/repair_shell.py gate data/candidates/volumetric/tray-v*.txt
    uv run python tools/repair_shell.py repair --name tube data/candidates/volumetric/tube-v1.txt \\
        --out data/candidates/volumetric --max-found 6 --deadline 90
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine  # noqa: E402
from cubot.shapes import (  # noqa: E402
    dense_cell_count,
    has_2x2x2_block,
    neighbours,
    parse_layers,
    screen,
    to_layers,
)
from cubot.solver import solve  # noqa: E402
from cubot.viz import render_voxels  # noqa: E402


def read_layers(path: Path) -> tuple[tuple, ...]:
    return parse_layers(path.read_text())


def spans(cells) -> tuple[int, int, int]:
    xs, ys, zs = zip(*cells)
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def gate_one(cells, roll: str, *, deadline_s: float = 20.0, max_solutions: int = 64) -> dict:
    row = {
        "cells": len(set(cells)),
        "two_thick": has_2x2x2_block(cells),
        "dense": dense_cell_count(cells),
        "spans": spans(cells) if cells else (0, 0, 0),
        "screen_ok": False,
        "screen_stage": None,
        "threadings": 0,
        "thread_status": None,
    }
    row["volumetric"] = all(s > 0 for s in row["spans"])
    report = screen(cells, 27)
    row["screen_ok"] = report.ok
    row["screen_stage"] = report.stage
    if not report.ok or row["two_thick"]:
        return row
    result = solve(cells, roll, all_solutions=True, max_solutions=max_solutions, deadline_s=deadline_s)
    row["threadings"] = len(result.solutions)
    row["thread_status"] = result.status.value
    return row


def gate_line(name: str, row: dict) -> str:
    box = "x".join(str(s + 1) for s in row["spans"])
    tags = f"box {box}, dense {row['dense']}, {'volumetric' if row['volumetric'] else 'PLANAR'}"
    if row["cells"] != 27:
        return f"{name}: WRONG COUNT {row['cells']} ({tags})"
    if row["two_thick"]:
        return f"{name}: REJECT two-thick (contains a 2x2x2 block) ({tags})"
    if not row["screen_ok"]:
        return f"{name}: STRUCTURAL FAIL at {row['screen_stage']} ({tags})"
    if row["threadings"]:
        return f"{name}: FOUND, {row['threadings']} threadings ({tags})"
    return f"{name}: {row['thread_status']} ({tags})"


def repair(base, roll: str, *, max_found: int, deadline_s: float, max_variants: int, per_solve_s: float = 3.0):
    started = time.monotonic()
    base_set = frozenset(base)
    frontier = {n for c in base_set for n in neighbours(c) if n not in base_set}
    found: list[tuple[frozenset, tuple, tuple, int]] = []
    gated = 0
    seen: set[frozenset] = set()
    for rem in sorted(base_set):
        for add in sorted(frontier):
            if time.monotonic() - started > deadline_s or len(found) >= max_found or gated >= max_variants:
                return found, gated, time.monotonic() - started
            cand = (base_set - {rem}) | {add}
            if len(cand) != 27 or cand in seen or has_2x2x2_block(cand):
                continue
            seen.add(cand)
            if not screen(cand, 27).ok:
                continue
            gated += 1
            result = solve(cand, roll, all_solutions=True, max_solutions=8, deadline_s=per_solve_s)
            if result.found:
                found.append((cand, rem, add, len(result.solutions)))
    return found, gated, time.monotonic() - started


def write_layered(path: Path, cells, header: str) -> None:
    body = [f"// {header}"]
    for layer_index, rows in enumerate(to_layers(cells)):
        if layer_index:
            body.append("---")
        body.extend(rows)
    path.write_text("\n".join(body) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("gate", help="screen + thread layered masks; never fold")
    g.add_argument("masks", nargs="+", type=Path)
    g.add_argument("--iso", action="store_true", help="also write <mask>.png iso renders next to the masks")
    r = sub.add_parser("repair", help="single-cell perturbation repair of an UNSAT layered mask")
    r.add_argument("masks", nargs="+", type=Path, help="base mask(s)")
    r.add_argument("--name", required=True)
    r.add_argument("--out", type=Path, default=Path("data/candidates/volumetric"))
    r.add_argument("--max-found", type=int, default=6)
    r.add_argument("--deadline", type=float, default=90.0, help="seconds per base mask")
    r.add_argument("--max-variants", type=int, default=500)
    r.add_argument("--start-index", type=int, default=1, help="first N in <name>-rN.txt")
    args = parser.parse_args()

    roll = load_machine().roll
    if args.command == "gate":
        for path in args.masks:
            try:
                cells = read_layers(path)
            except ValueError as error:
                print(f"{path.stem}: PARSE ERROR {error}")
                continue
            print(gate_line(path.stem, gate_one(cells, roll)), flush=True)
            if args.iso and cells:
                render_voxels(cells, path.with_suffix(".png"))
        return 0

    index = args.start_index
    for path in args.masks:
        base = read_layers(path)
        found, gated, elapsed = repair(
            base, roll, max_found=args.max_found, deadline_s=args.deadline, max_variants=args.max_variants
        )
        print(f"{path.stem}: {len(found)} threadable single-cell variants of {gated} gated in {elapsed:.0f} s")
        args.out.mkdir(parents=True, exist_ok=True)
        for cand, rem, add, n in found:
            cells = tuple(sorted(cand))
            out_path = args.out / f"{args.name}-r{index}.txt"
            write_layered(
                out_path,
                cells,
                f"repaired from {path.name}: moved {rem} -> {add}; {n} threadings; dense {dense_cell_count(cells)}",
            )
            png = render_voxels(cells, args.out / f"{args.name}-r{index}.png")
            print(f"  wrote {out_path} ({n} threadings) -> {png}")
            index += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
