#!/usr/bin/env python3
"""Replay shipped paths against the module-0 cable keep-out (``machine.tether_*``).

A cable bundle leaves module 0 through its mount face.  ``config/machine.toml``
models it as a rigid box that nothing may sweep through, that no module may
occupy at rest, and that may not enter the table.  This audit replays every
``handoff/shapes/*/path.json`` (or any ``record.json``) twice — with the tether
and with it switched off — and reports the moves whose hard verdict changed,
so tether-caused failures are separated from anything else that drifted.

Usage (from ``cubot-v2/``)::

    uv run python tools/tether_audit.py                       # every handoff path
    uv run python tools/tether_audit.py --workers 4 --out out/tether-audit.json
    uv run python tools/tether_audit.py handoff/shapes/01-heart/path.json out/x/record.json
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from multiprocessing import Pool
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402
from cubot.folder import check_move, next_pose, tether_cell  # noqa: E402
from cubot.lattice import pose_cells  # noqa: E402
from cubot.records import Move, Pose  # noqa: E402


def _pose(raw: dict) -> Pose:
    return Pose(tuple(int(s) for s in raw["states"]), raw["roll"], int(raw["base"]), raw.get("lying"))


def load_path(path: Path) -> tuple[str, Pose, list[Move]]:
    data = json.loads(path.read_text())
    if data.get("schema", "").startswith("cubot.handoff"):
        start = _pose({**data["start"], "roll": data["machine"]["roll"]})
        moves = [Move(int(m["joint"]), int(m["delta"]), m["side"], float(m["duration_s"])) for m in data["moves"]]
        return data["name"], start, moves
    plan = data["plans"][0]
    start = _pose(plan["start"])
    moves = [Move(int(m["joint"]), int(m["delta"]), m["side"], float(m["duration_s"])) for m in plan["moves"]]
    return data["name"], start, moves


def audit_one(job: tuple[str, str]) -> dict:
    path, profile_name = job
    name, start, moves = load_path(Path(path))
    machine = load_machine()
    bare = replace(machine, tether_length_mm=0.0)
    profile = load_profile(profile_name)
    pose = start
    tether_failures: list[dict] = []
    other_failures: list[dict] = []
    for index, move in enumerate(moves):
        with_tether = check_move(pose, move, machine, profile)
        if not with_tether.hard_ok:
            without = check_move(pose, move, bare, profile)
            failed = {k: v[1] for k, v in with_tether.hard.items() if not v[0]}
            bare_failed = {k for k, v in without.hard.items() if not v[0]}
            caused = {k: v for k, v in failed.items() if k not in bare_failed}
            if caused:
                tether_failures.append({"move": index, "joint": move.joint, "delta": move.delta, "side": move.side, "checks": caused})
            if bare_failed:
                other_failures.append({"move": index, "checks": {k: failed[k] for k in bare_failed if k in failed}})
        pose = next_pose(pose, move)
    keep_out = tether_cell(pose)
    return {
        "name": name,
        "path": path,
        "moves": len(moves),
        "goal_tether_cell": list(keep_out),
        "goal_tether_cell_occupied": keep_out in set(pose_cells(pose)),
        "tether_failures": tether_failures,
        "other_failures": other_failures,
        "tether_ok": not tether_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path, help="path.json or record.json files (default: handoff/shapes/*/path.json)")
    parser.add_argument("--profile", default="loose")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "tether-audit.json")
    args = parser.parse_args()
    paths = args.paths or sorted((ROOT / "handoff" / "shapes").glob("*/path.json"))
    if not paths:
        parser.error("no paths to audit")
    jobs = [(str(p), args.profile) for p in paths]
    if args.workers > 1:
        with Pool(args.workers) as pool:
            rows = list(pool.imap(audit_one, jobs))
    else:
        rows = [audit_one(job) for job in jobs]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"profile": args.profile, "tether_length_mm": load_machine().tether_length_mm, "tether_width_mm": load_machine().tether_width_mm, "paths": rows}, indent=2, default=str) + "\n")
    bad = [r for r in rows if not r["tether_ok"]]
    for row in rows:
        flag = "ok " if row["tether_ok"] else "TETHER"
        detail = "; ".join(f"move {f['move']} j{f['joint']} {f['side']}: {', '.join(f['checks'])}" for f in row["tether_failures"][:3])
        other = f" (+{len(row['other_failures'])} non-tether)" if row["other_failures"] else ""
        print(f"{flag} {row['name']:<20} {row['moves']:>3} moves  {detail}{other}")
    print(f"\n{len(bad)} of {len(rows)} paths violate the tether keep-out under '{args.profile}' -> {args.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
