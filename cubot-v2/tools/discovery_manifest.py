#!/usr/bin/env python3
"""Write a ``cubot.handoff.manifest.v1`` file for a glyph-atlas discovery sweep.

``tools/discover_glyphs.py`` leaves ``summary.json`` next to its folded runs;
this turns every complete, loose-passing candidate into a manifest entry so the
sweep exports through ``tools/export_handoff.py --manifest`` exactly like the
mask-first exploration winners (``tools/explore_summary.py`` writes the same
file for that method).  Candidate slugs (``c-v01``) are used as the handoff
names as-is: they are unique within the sweep and never collide with the demo
seven or the exploration winners, whose names carry no ``-vNN`` suffix.

Usage (from ``cubot-v2/``)::

    uv run python tools/discovery_manifest.py --out out/discovery-20260919
    uv run python tools/export_handoff.py --manifest out/explore-20260919/handoff-manifest.json \
                                          --manifest out/discovery-20260919/handoff-manifest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MANIFEST_SCHEMA = "cubot.handoff.manifest.v1"


def write_manifest(summary: dict, out_root: Path, only: set[str] | None = None) -> Path:
    """Write the complete + loose-passing candidates as a manifest; run dirs are relative to it."""

    shapes = []
    for row in summary["candidates"]:
        if not (row["complete"] and row["loose_hard_ok"]):
            continue
        if only is not None and row["slug"] not in only:
            continue
        run_dir = Path(row["record"]).parent
        try:
            run = str(run_dir.resolve().relative_to(out_root.resolve()))
        except ValueError:
            run = str(run_dir)
        shapes.append({"name": row["slug"], "variant": row["slug"], "concept": row["concept"], "run": run,
                       "moves": row["moves"], "ends_flat": row["ends_flat"]})
    if only is not None:
        missing = sorted(only - {s["name"] for s in shapes})
        if missing:
            raise SystemExit(f"--only slugs without a loose-passing row: {', '.join(missing)}")
    path = out_root / "handoff-manifest.json"
    path.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "source": str(out_root), "shapes": shapes}, indent=2) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("out/discovery-20260919"))
    parser.add_argument("--only", nargs="*", default=None, metavar="SLUG",
                        help="restrict handoff-manifest.json to these candidate slugs")
    args = parser.parse_args()

    summary = json.loads((args.out / "summary.json").read_text())
    if summary.get("schema") != "cubot.discovery-summary.v1":
        raise SystemExit(f"{args.out / 'summary.json'}: unexpected schema {summary.get('schema')!r}")
    manifest = write_manifest(summary, args.out, None if args.only is None else set(args.only))
    n = len(json.loads(manifest.read_text())["shapes"])
    print(f"{n} of {summary['folded']} folded candidates are complete and loose-passing; wrote {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
