#!/usr/bin/env python3
"""make_fold_viewer.py — bundle cubot_shipped.urdf + meshes/*.stl + every handoff fold path into
fold_viewer.html, a standalone page that animates each shape folding and unfolding.

The page builds the chain from the URDF text exactly like viewer.html, then drives the servos from the
move lists in ../cubot-v2/handoff/shapes/*/path.json — the demo seven plus every shape appended by
export_handoff.py --manifest (mask-first exploration winners, glyph-atlas discovery candidates).  Each
shape is tagged with the run family it came from so the page can group them.  Only the fields the
animation needs are embedded; the page re-checks every rest pose against the planner's
cells_after / base_after at load.

Run:  python3 make_fold_viewer.py   ->  fold_viewer.html   (open in any browser; three.js comes from jsDelivr)
"""
import base64, glob, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
HANDOFF = os.path.join(HERE, "..", "cubot-v2", "handoff")

urdf = open(os.path.join(HERE, "cubot_shipped.urdf")).read()
assert "</script" not in urdf
stl = {n: base64.b64encode(open(os.path.join(HERE, "meshes", f"{n}.stl"), "rb").read()).decode() for n in ("still", "moving")}


# Which pipeline run a path came from, read off the record path the exporter recorded.  Order = display order.
GROUPS = (
    ("demo", "demo-", "Demo seven"),
    ("exploration", "explore-", "Mask-first exploration"),
    ("atlas", "discovery-", "Glyph-atlas discovery"),
)


def group_of(source_record):
    run = source_record.split("/out/", 1)[-1].split("/", 1)[0]
    for key, prefix, _ in GROUPS:
        if run.startswith(prefix):
            return key
    raise SystemExit(f"cannot tell which run family {source_record} belongs to (expected out/demo-*, explore-* or discovery-*)")


def slim(path):
    d = json.load(open(path))
    target = d["goal"].get("authored_target")
    return {
        "name": d["name"],
        "demo_number": d["demo_number"],
        "group": group_of(d["provenance"]["source_record"]),
        "variant": d["provenance"].get("mask_variant"),
        "aliases": d.get("aliases", []),
        "target": target if isinstance(target, list) and all(isinstance(r, str) for r in target) else None,
        "roll": d["machine"]["roll"],
        "pitch_mm": d["machine"]["pitch_mm"],
        "loose_hard_ok": d["status"]["loose_hard_ok"],
        "loose_violations": d["status"]["loose_violations"],
        "total_time_s": d["summary"]["total_time_s"],
        "start": {"states": d["start"]["states"], "base": d["start"]["base"], "cells": d["start"]["cells"]},
        "goal": {"states": d["goal"]["states"], "base": d["goal"]["base"], "silhouette": d["goal"]["silhouette"]},
        "final_tracked": {
            "base": d["final_tracked"]["base"],
            "ends_flat_on_table": d["final_tracked"]["ends_flat_on_table"],
            "lattice_span": d["final_tracked"]["lattice_span"],
        },
        "moves": [
            {
                "step": m["step"], "joint": m["joint"], "delta": m["delta"], "side": m["side"],
                "duration_s": m["duration_s"], "hard_ok": m["hard_ok"],
                "peak_demand_nm": m["checks"]["measurements"].get("peak_demand_nm"),
                "failed_checks": [k for k, v in m["checks"]["hard"].items() if not v[0]],
                "states_after": m["states_after"], "base_after": m["base_after"], "cells_after": m["cells_after"],
            }
            for m in d["moves"]
        ],
    }


shapes = sorted((slim(p) for p in glob.glob(os.path.join(HANDOFF, "shapes", "*", "path.json"))), key=lambda s: s["demo_number"])
assert [s["demo_number"] for s in shapes] == list(range(1, len(shapes) + 1)), "handoff numbering has a gap"
assert [s["name"] for s in shapes[:7]] == ["heart", "arrow", "lightning", "plus", "h", "t", "n"], "the demo seven must come first"
assert len({s["name"] for s in shapes}) == len(shapes), "duplicate shape names"
shapes_json = json.dumps(shapes, separators=(",", ":"))
assert "</script" not in shapes_json
groups_json = json.dumps([{"key": k, "title": t} for k, _, t in GROUPS])

html = open(os.path.join(HERE, "fold_template.html")).read()
html = (html.replace("__URDF__", urdf).replace("__STL_STILL__", stl["still"]).replace("__STL_MOVING__", stl["moving"])
            .replace("__SHAPES__", shapes_json).replace("__GROUPS__", groups_json))
open(os.path.join(HERE, "fold_viewer.html"), "w").write(html)
counts = {k: sum(1 for s in shapes if s["group"] == k) for k, _, _ in GROUPS}
print(f"wrote fold_viewer.html ({len(html)//1024} kB; {len(shapes)} shapes, {len(shapes_json)//1024} kB: "
      + ", ".join(f"{n} {k}" for k, n in counts.items()) + "; "
      + f"{sum(len(s['moves']) for s in shapes)} moves total)")
