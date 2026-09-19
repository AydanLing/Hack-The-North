#!/usr/bin/env python3
"""Replay recorded fold paths under the current checker and report the verdicts.

Used when a rule changes (2026-09-19: the wire bundle leaving module 0's free
face became a collision body — ``docs/RULES.md``).  Every path is replayed
move for move with its recorded sides under the profile it was accepted with
(``record.meta.profile``) and under ``loose``; nothing is re-searched here.
Rows that fail are the ones to re-fold.

Inputs: handoff ``path.json`` files, pipeline ``record.json`` files, or
``results.jsonl`` files (each row's ``record_json``).

Usage (from ``cubot-v2/``)::

    uv run python tools/recheck_paths.py handoff/shapes/*/path.json
    uv run python tools/recheck_paths.py out/explore3d-20260919/w*/results.jsonl --json out/recheck.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402
from cubot.folder import replay  # noqa: E402
from cubot.records import Move, Pose  # noqa: E402


def _pose(raw: dict, roll: str | None = None) -> Pose:
    return Pose(tuple(int(s) for s in raw["states"]), raw.get("roll") or roll, int(raw["base"]), raw.get("lying"))


def _moves(raw_moves: list[dict]) -> list[Move]:
    return [Move(int(m["joint"]), int(m["delta"]), m["side"], float(m.get("duration_s", 2.0))) for m in raw_moves]


def load_paths(path: Path) -> list[dict]:
    """Yield ``{name, start, goal, moves, profile, source}`` for every path in a file."""

    if path.name == "results.jsonl":
        out = []
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("record_json") and row.get("complete"):
                out.extend(load_paths(Path(row["record_json"])))
        return out
    raw = json.loads(path.read_text())
    if "plans" in raw:  # pipeline record.json
        plan = raw["plans"][0]
        return [{
            "name": raw["name"], "source": str(path),
            "start": _pose(plan["start"]), "goal": _pose(plan["goal"]), "moves": _moves(plan["moves"]),
            "profile": raw.get("meta", {}).get("profile", "loose"),
        }]
    # handoff path.json
    roll = raw["machine"]["roll"]
    return [{
        "name": raw["name"], "source": str(path),
        "start": _pose(raw["start"], roll), "goal": _pose(raw["goal"], roll), "moves": _moves(raw["moves"]),
        "profile": raw.get("status", {}).get("accept_profile", "loose"),
    }]


def recheck(entry: dict, machine, profiles: dict) -> dict:
    result = {"name": entry["name"], "source": entry["source"], "accept_profile": entry["profile"], "moves": len(entry["moves"])}
    for name in sorted({entry["profile"], "loose"}):
        candidate = replay(entry["start"], entry["moves"], goal=entry["goal"], machine=machine, profile=profiles[name])
        result[name] = {
            "complete": candidate.complete,
            "hard_ok": candidate.hard_ok,
            "violations": candidate.violations,
            "tether_violations": [v for v in candidate.violations if "tether" in v],
        }
    accepted = result[entry["profile"]]
    result["still_valid"] = bool(accepted["complete"] and accepted["hard_ok"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", type=Path, default=None, help="write the full report here")
    args = parser.parse_args()

    machine = load_machine()
    profiles = {name: load_profile(name) for name in ("loose", "platform", "strict")}
    report = []
    for path in args.paths:
        for entry in load_paths(path):
            result = recheck(entry, machine, profiles)
            report.append(result)
            accepted = result[result["accept_profile"]]
            flag = "OK " if result["still_valid"] else "FAIL"
            tether = accepted["tether_violations"]
            print(
                f"{flag} {result['name']:<16} {result['accept_profile']:<8} {result['moves']:>3} moves"
                + (f"  tether: {tether[0]}" if tether else "")
                + ("" if result["still_valid"] or tether else f"  other: {accepted['violations'][:1]}"),
                flush=True,
            )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    failed = [r for r in report if not r["still_valid"]]
    print(f"{len(report) - len(failed)} still valid, {len(failed)} need re-folding")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
