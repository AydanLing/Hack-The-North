"""Shared software home for the physical CuBot chain.

The fold pipeline and MuJoCo sim always speak **handoff state 0 / 0° /
``go(home)``**. This module never turns "zero" into a raw encoder goal like
2903 — it only aligns ``Axis.home`` so that command lands on the straight
line captured in ``calibration/software_homes.json``.

Recapture with the chain physically straight (no motion required)::

    python3 -m cubot_imessage.homes capture
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_HOMES_PATH = Path(__file__).resolve().parent / "calibration" / "software_homes.json"


def homes_path() -> Path:
    override = (os.environ.get("CUBOT_HOMES_JSON") or "").strip()
    return Path(override) if override else DEFAULT_HOMES_PATH


def load_homes(path: Path | None = None) -> dict[int, int]:
    """Map servo id → ``present_position`` reading that means straight / state 0."""
    p = path or homes_path()
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    out: dict[int, int] = {}
    for sid_s, row in (doc.get("homes") or {}).items():
        if isinstance(row, dict):
            out[int(sid_s)] = int(row["present_position"])
        else:
            out[int(sid_s)] = int(row)
    return out


def align_axis_home(axis, target_present: int, wrap_delta, steps_per_rev: int) -> None:
    """Set ``axis.home`` so ``from_home()==0`` at ``target_present`` (one-turn wrap).

    Does not move the servo. Pipeline goals stay ``home + delta``.
    """
    delta = wrap_delta(int(target_present) % steps_per_rev, axis.rep % steps_per_rev)
    axis.home = axis.cont + delta


def apply_homes(axes, homes: dict[int, int], rc_mod) -> list[int]:
    """Align every axis that has a calibration entry. Returns aligned servo ids."""
    wrap_delta = rc_mod.wrap_delta
    steps = rc_mod.STEPS_PER_REV
    aligned: list[int] = []
    for ax in axes:
        if ax.sid not in homes:
            ax.set_zero()
            continue
        align_axis_home(ax, homes[ax.sid], wrap_delta, steps)
        aligned.append(ax.sid)
    return aligned


def capture_homes(
    *,
    hw_root: str = "",
    serial_port: str = "",
    last: int = 27,
    path: Path | None = None,
) -> dict[str, Any]:
    """Soft-zero at the current pose and write the shared calibration JSON.

    Requires the chain to already be physically straight. Writes no motion
    goals — only ``set_zero`` + a snapshot file.
    """
    import sys

    root = os.path.abspath(hw_root or os.environ.get("CUBOT_HW_ROOT", "/Users/jerryli/Downloads/cubot"))
    if root not in sys.path:
        sys.path.insert(0, root)
    import rc  # type: ignore
    import sts3215  # type: ignore

    port = serial_port or os.environ.get("CUBOT_SERIAL_PORT") or sts3215.autodetect_port()
    out_path = path or homes_path()
    geo = rc.Geometry(4.0, rc.resolve_limit(None, False, 4.0))

    with sts3215.Bus(port) as bus:
        ids = bus.scan(range(1, last + 1))
        if not ids:
            raise RuntimeError("no servos found")
        homes_rows: dict[str, Any] = {}
        for sid in ids:
            ax = rc.Axis(bus, sid, geo)
            st = bus.read_state(sid)
            ax.update(st["position"])
            ax.set_zero()
            homes_rows[str(sid)] = {
                "present_position": int(st["position"]),
                "degrees_reported": round(sts3215.steps_to_deg(st["position"] % 4096), 2),
                "cont_at_home": int(ax.cont),
                "home": int(ax.home),
            }

    doc: dict[str, Any] = {
        "schema": "cubot.software_homes.v1",
        "description": (
            "Encoder snapshot of the straight-chain pose. The fold pipeline still "
            "commands state 0 / 0 deg / go(home) — never raw present_position as zero. "
            "On connect, Axis.home is aligned to this snapshot so from_home()==0 on "
            "the straight line. Recapture only with the chain physically straight."
        ),
        "pipeline_contract": {
            "handoff_state_0": "software home (straight line)",
            "command": "axis.go(axis.home) or home + state*steps",
        },
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "port": port,
        "servo_ids": ids,
        "homes": homes_rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    return doc


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="soft-zero here and write software_homes.json")
    cap.add_argument("--last", type=int, default=27)
    cap.add_argument("--port", default="")
    cap.add_argument("--out", type=Path, default=None)
    sub.add_parser("show", help="print the checked-in homes file")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        p = homes_path()
        print(p)
        print(p.read_text(encoding="utf-8"))
        return 0

    doc = capture_homes(serial_port=args.port, last=args.last, path=args.out)
    print(f"wrote {homes_path() if args.out is None else args.out}")
    print(f"servos: {doc['servo_ids']}")
    for sid, row in doc["homes"].items():
        print(f"  {sid:>2}: present={row['present_position']:>5}  "
              f"from_home origin (pipeline zero)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
