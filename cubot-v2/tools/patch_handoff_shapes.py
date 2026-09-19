#!/usr/bin/env python3
"""Patch existing handoff shape dirs from pipeline record.json runs without wiping index.json.

Usage (from cubot-v2/)::

    python tools/patch_handoff_shapes.py \\
        --shape checkmark=out/explore-gentle2/runs/checkmark-slim/checkmark \\
        --shape heart=out/explore-gentle2/runs/heart/heart
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine, load_profile  # noqa: E402

# export_handoff lives as a script under tools/, not a package.
import importlib.util

_spec = importlib.util.spec_from_file_location("export_handoff", ROOT / "tools" / "export_handoff.py")
_export = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_export)
PROFILE_NAMES = _export.PROFILE_NAMES
export_shape = _export.export_shape



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shape",
        action="append",
        default=[],
        metavar="NAME=RUN_DIR",
        help="pipeline run directory that contains record.json",
    )
    parser.add_argument("--handoff", type=Path, default=ROOT / "handoff")
    parser.add_argument(
        "--number",
        action="append",
        default=[],
        metavar="NAME=N",
        help="override demo number for NAME (default: keep existing index number)",
    )
    args = parser.parse_args()
    if not args.shape:
        raise SystemExit("pass at least one --shape NAME=RUN_DIR")

    index_path = args.handoff / "index.json"
    index = json.loads(index_path.read_text())
    by_name = {str(s["name"]).lower(): s for s in index["shapes"]}
    number_overrides = {}
    for spec in args.number:
        name, _, raw = spec.partition("=")
        number_overrides[name.strip().lower()] = int(raw)

    machine = load_machine()
    profiles = {}
    for name in list(PROFILE_NAMES) + ["gentle"]:
        path = ROOT / "config" / "profiles" / f"{name}.toml"
        if path.is_file():
            profile = load_profile(name)
            profiles[name] = {k: getattr(profile, k) for k in profile.__dataclass_fields__ if k != "name"}

    # Export into a scratch handoff tree, then copy path artifacts into the live dirs.
    scratch = args.handoff.parent / ".handoff-patch-tmp"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)

    updated = []
    for spec in args.shape:
        name, _, run = spec.partition("=")
        name = name.strip().lower()
        run_dir = Path(run).resolve()
        if name not in by_name and name not in number_overrides:
            raise SystemExit(f"{name}: not in index.json; pass --number {name}=N")
        number = number_overrides.get(name, int(by_name[name]["number"]))
        if not (run_dir / "record.json").is_file():
            raise SystemExit(f"missing record.json in {run_dir}")
        entry = export_shape(name, number, run_dir, scratch, machine, profiles)
        src = scratch / "shapes" / f"{number:02d}-{name}"
        # Prefer existing live dir name (may be 01-heart not 1-heart).
        live_dir_rel = by_name.get(name, {}).get("dir")
        if live_dir_rel:
            dst = args.handoff / live_dir_rel
        else:
            dst = args.handoff / "shapes" / f"{number:02d}-{name}"
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dst / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
        # Merge index row fields we care about; keep number/dir stable.
        row = dict(by_name.get(name, {}))
        row.update({
            "number": number,
            "name": name,
            "dir": str(dst.relative_to(args.handoff)),
            "moves": entry["moves"],
            "complete": entry["complete"],
            "accept_profile": entry.get("accept_profile", "gentle"),
            "tier": entry.get("tier"),
            "loose_hard_ok": entry.get("loose_hard_ok"),
            "platform_hard_ok": entry.get("platform_hard_ok"),
            "strict_hard_ok": entry.get("strict_hard_ok"),
            "loose_violations": entry.get("loose_violations", 0),
            "ends_flat_on_table": entry.get("ends_flat_on_table"),
            "goal_states": entry.get("goal_states"),
            "lattice_span": entry.get("lattice_span"),
            "final_upright": entry.get("final_upright"),
            "layered": entry.get("layered"),
            "final_base_tracked": entry.get("final_base_tracked"),
            "start_base": entry.get("start_base"),
            "goal_base_nominal": entry.get("goal_base_nominal"),
        })
        by_name[name] = row
        updated.append(row)
        print(
            f"patched {number}. {name}: {entry['moves']} moves, "
            f"loose_hard_ok={entry.get('loose_hard_ok')}, ends_flat={entry.get('ends_flat_on_table')} -> {dst}"
        )

    # Preserve order by number.
    shapes = sorted(by_name.values(), key=lambda s: int(s.get("number", 999)))
    index["shapes"] = shapes
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    shutil.rmtree(scratch)
    print(f"updated {index_path} ({len(updated)} shapes patched, {len(shapes)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
