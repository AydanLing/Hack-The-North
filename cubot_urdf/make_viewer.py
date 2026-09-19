#!/usr/bin/env python3
"""make_viewer.py — bundle cubot_shipped.urdf + meshes/*.stl into viewer.html, a standalone browser viewer.

The page parses the URDF TEXT at load (DOMParser), builds the kinematic tree from the joints it finds,
decodes the STLs, and runs a set of checks against the shipped configuration. Nothing is re-derived
from build_cubot_urdf.py — if the URDF is wrong, the viewer shows it wrong.

Run:  python3 make_viewer.py   ->  viewer.html   (open in any browser; three.js comes from jsDelivr)
"""
import base64, os

HERE = os.path.dirname(os.path.abspath(__file__))
urdf = open(os.path.join(HERE, "cubot_shipped.urdf")).read()
assert "</script" not in urdf
stl = {n: base64.b64encode(open(os.path.join(HERE, "meshes", f"{n}.stl"), "rb").read()).decode() for n in ("still", "moving")}

html = open(os.path.join(HERE, "viewer_template.html")).read()
html = html.replace("__URDF__", urdf).replace("__STL_STILL__", stl["still"]).replace("__STL_MOVING__", stl["moving"])
open(os.path.join(HERE, "viewer.html"), "w").write(html)
print(f"wrote viewer.html ({len(html)//1024} kB)")

# artifact flavour: same page without the doctype/meta lines (the artifact host supplies that skeleton)
art = "\n".join(l for l in html.splitlines() if not l.startswith(("<!doctype", "<meta ")))
out = os.environ.get("VIEWER_ARTIFACT_OUT")
if out:
    open(out, "w").write(art); print(f"wrote {out}")
