#!/usr/bin/env python3
"""Flag thrashing fold paths: moves >> min detents to the goal states.

A path that bends joints that finish at 0 (or revisits a joint many times) is
usually a search detour workaround, not a clean booth demo.  Use this on a
handoff folder or a results.jsonl campaign:

    python tools/audit_path_quality.py cubot-v2/handoff-17
    python tools/audit_path_quality.py cubot-v2/out/n17-mine --max-ratio 1.5
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def audit_path(doc: dict) -> dict:
    states = list(doc["goal"]["states"])
    moves = doc["moves"]
    min_detents = sum(abs(s) for s in states)
    hits = Counter(m["joint"] for m in moves)
    waste = sum(max(0, hits[j] - abs(states[j])) for j in hits)
    thrash0 = [j for j, h in hits.items() if j < len(states) and states[j] == 0]
    peak = (doc.get("summary") or {}).get("peak_demand_nm")
    return {
        "name": doc.get("name"),
        "moves": len(moves),
        "min_detents": min_detents,
        "ratio": round(len(moves) / max(1, min_detents), 2),
        "waste_hits": waste,
        "thrash_zero_joints": thrash0,
        "peak_nm": peak,
        "flat": (doc.get("summary") or {}).get("ends_flat_on_table"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path, help="handoff dir or campaign out dir")
    p.add_argument("--max-ratio", type=float, default=1.5,
                   help="flag paths with moves/min_detents above this (default 1.5)")
    p.add_argument("--max-peak", type=float, default=None,
                   help="also flag peak_demand_nm above this")
    args = p.parse_args()
    root: Path = args.root

    rows = []
    for path_json in sorted(root.rglob("path.json")):
        doc = json.loads(path_json.read_text())
        row = audit_path(doc)
        row["path"] = str(path_json)
        rows.append(row)
    # also accept pipeline records under runs/*/record.json primary plan
    if not rows:
        for rec in sorted(root.rglob("record.json")):
            data = json.loads(rec.read_text())
            plans = data.get("plans") or []
            if not plans:
                continue
            best = next((pl for pl in plans if pl.get("complete") and pl.get("hard_ok")), plans[0])
            fake = {
                "name": data.get("name") or rec.parent.name,
                "goal": {"states": best["goal"]["states"]},
                "moves": best["moves"],
                "summary": {
                    "peak_demand_nm": max(
                        (m.get("checks", {}).get("measurements", {}).get("peak_demand_nm") or 0.0)
                        for m in best["moves"]
                    ) if best.get("moves") else None,
                    "ends_flat_on_table": None,
                },
            }
            row = audit_path(fake)
            row["path"] = str(rec)
            rows.append(row)

    if not rows:
        print(f"no path.json / record.json under {root}")
        return 1

    print(f"{'shape':<12} {'moves':>5} {'min':>4} {'ratio':>5} {'waste':>5} {'peak':>6}  flags")
    print("-" * 72)
    bad = 0
    for r in sorted(rows, key=lambda x: (-x["ratio"], x["name"] or "")):
        flags = []
        if r["ratio"] > args.max_ratio:
            flags.append("THRASH")
        if args.max_peak is not None and r["peak_nm"] is not None and r["peak_nm"] > args.max_peak:
            flags.append("TORQUE")
        if r["thrash_zero_joints"]:
            flags.append(f"zeroj={r['thrash_zero_joints']}")
        if flags:
            bad += 1
        peak = f"{r['peak_nm']:.2f}" if r["peak_nm"] is not None else "  ?"
        print(f"{(r['name'] or '?'):<12} {r['moves']:5d} {r['min_detents']:4d} {r['ratio']:5.2f} "
              f"{r['waste_hits']:5d} {peak:>6}  {' '.join(flags) or 'ok'}")
    print(f"\n{bad}/{len(rows)} flagged (max_ratio={args.max_ratio}"
          + (f", max_peak={args.max_peak}" if args.max_peak is not None else "") + ")")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
