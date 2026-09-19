#!/usr/bin/env python3
"""make_fold_viewer.py — bundle cubot_shipped.urdf + meshes/*.stl + the seven handoff fold paths into
fold_viewer.html, a standalone page that animates each shape folding and unfolding.

The page builds the chain from the URDF text exactly like viewer.html, then drives the servos from the
move lists in ../cubot-v2/handoff/shapes/*/path.json.  Only the fields the animation needs are embedded;
the page re-checks every rest pose against the planner's cells_after / base_after at load.

Run:  python3 make_fold_viewer.py   ->  fold_viewer.html   (open in any browser; three.js comes from jsDelivr)
"""
import base64, glob, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
HANDOFF = os.path.join(HERE, "..", "cubot-v2", "handoff")

urdf = open(os.path.join(HERE, "cubot_shipped.urdf")).read()
assert "</script" not in urdf
stl = {n: base64.b64encode(open(os.path.join(HERE, "meshes", f"{n}.stl"), "rb").read()).decode() for n in ("still", "moving")}


def slim(path):
    d = json.load(open(path))
    return {
        "name": d["name"],
        "demo_number": d["demo_number"],
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
assert len(shapes) == 7, f"expected the seven demo paths, found {len(shapes)}"
shapes_json = json.dumps(shapes, separators=(",", ":"))
assert "</script" not in shapes_json

html = open(os.path.join(HERE, "fold_template.html")).read()
html = (html.replace("__URDF__", urdf).replace("__STL_STILL__", stl["still"]).replace("__STL_MOVING__", stl["moving"])
            .replace("__SHAPES__", shapes_json))
open(os.path.join(HERE, "fold_viewer.html"), "w").write(html)
print(f"wrote fold_viewer.html ({len(html)//1024} kB; shapes {len(shapes_json)//1024} kB: "
      + ", ".join(f"{s['name']} {len(s['moves'])}" for s in shapes) + ")")
