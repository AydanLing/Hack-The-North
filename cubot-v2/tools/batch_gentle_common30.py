#!/usr/bin/env python3
"""Build masks + run gentle explore for the ~30 most common handoff shapes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cubot.pipeline import get_icon  # noqa: E402

WANTED = [
    "heart", "arrow", "lightning", "h", "t", "n", "c", "j", "m", "a", "e", "i", "o", "u", "s", "k", "w",
    "spiral", "staircase", "triangle", "ring", "rocket", "tree", "flag", "crown", "diamond",
    "paperclip", "hammer", "smiley", "cube-frame",
]

# Already shipped gentle in a prior pass — still re-run if in list is fine, but skip to save time.
ALREADY_GENTLE = {"checkmark", "square", "plus", "mug"}


def best_row(idx: dict, name: str) -> dict | None:
    exact = [s for s in idx["shapes"] if s["name"] == name]
    if exact:
        return sorted(exact, key=lambda r: int(r["number"]))[0]
    alts = [s for s in idx["shapes"] if s["name"].startswith(name + "-")]
    if not alts:
        return None
    return sorted(alts, key=lambda r: int(r["number"]))[0]


def rows_for(name: str, row: dict) -> list[str] | None:
    sil = ROOT / "handoff" / row["dir"] / "silhouette.txt"
    if sil.is_file():
        text = sil.read_text()
        if "---" not in text:
            rows = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() and not ln.startswith("//")]
            if sum(c == "#" for r in rows for c in r) == 27:
                return rows
    for key in (name, name.split("-")[0]):
        try:
            rows = get_icon(key).rows
            if sum(c == "#" for r in rows for c in r) == 27:
                return rows
        except Exception:
            continue
    return None


def build_manifest() -> list[dict]:
    idx = json.loads((ROOT / "handoff" / "index.json").read_text())
    out = ROOT / "data" / "candidates" / "common30"
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for name in WANTED:
        if name in ALREADY_GENTLE:
            print(f"skip already-gentle {name}")
            continue
        row = best_row(idx, name)
        if not row:
            print(f"MISSING {name}")
            continue
        rows = rows_for(name, row)
        if not rows:
            print(f"no mask {name}")
            continue
        mask_path = out / f"{row['name']}.txt"
        mask_path.write_text("\n".join(rows) + "\n")
        entry = {
            "name": row["name"],
            "number": int(row["number"]),
            "dir": row["dir"],
            "mask": str(mask_path.relative_to(ROOT)),
        }
        manifest.append(entry)
        print(f"{entry['number']:3d} {entry['name']:20} -> {entry['mask']}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest {len(manifest)} shapes")
    return manifest


def explore(manifest: list[dict], out_root: Path) -> list[dict]:
    out_root.mkdir(parents=True, exist_ok=True)
    results_path = out_root / "batch_results.jsonl"
    if results_path.exists():
        results_path.unlink()
    passes: list[dict] = []
    for entry in manifest:
        cmd = [
            sys.executable, "-u", str(ROOT / "tools" / "explore_shape.py"),
            "--name", entry["name"],
            str(ROOT / entry["mask"]),
            "--out", str(out_root),
            "--profile", "gentle",
            "--yaw-expand",
            "--time-budget", "200",
            "-k", "6",
            "--max-candidates", "8",
        ]
        print("===", entry["name"], flush=True)
        proc = subprocess.run(cmd, cwd=ROOT, env={**dict(**{k: v for k, v in __import__('os').environ.items()}), "PYTHONPATH": str(ROOT)})
        # read last results line for this variant
        if not (out_root / "results.jsonl").is_file():
            continue
        lines = (out_root / "results.jsonl").read_text().splitlines()
        row = None
        for line in reversed(lines):
            r = json.loads(line)
            if r.get("name") == entry["name"]:
                row = r
                break
        if not row:
            continue
        with results_path.open("a") as fh:
            fh.write(json.dumps({**entry, "result": row}) + "\n")
        ok = bool(row.get("complete") and row.get("hard_ok"))
        print(f"  -> {'PASS' if ok else 'FAIL'} moves={row.get('moves')} viol={len(row.get('violations') or [])}", flush=True)
        if ok and row.get("record_json"):
            passes.append({**entry, "record_json": row["record_json"], "moves": row.get("moves")})
    (out_root / "passes.json").write_text(json.dumps(passes, indent=2) + "\n")
    print(f"passes {len(passes)}/{len(manifest)}")
    return passes


def patch(passes: list[dict]) -> None:
    if not passes:
        print("nothing to patch")
        return
    args = [sys.executable, str(ROOT / "tools" / "patch_handoff_shapes.py")]
    for p in passes:
        run_dir = Path(p["record_json"]).parent
        args.append(f"--shape={p['name']}={run_dir}")
        args.append(f"--number={p['name']}={p['number']}")
    subprocess.check_call(args, cwd=ROOT, env={**dict(**{k: v for k, v in __import__('os').environ.items()}), "PYTHONPATH": str(ROOT)})


def main() -> int:
    manifest = build_manifest()
    out_root = ROOT / "out" / "explore-common30"
    passes = explore(manifest, out_root)
    patch(passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
