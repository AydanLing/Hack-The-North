#!/usr/bin/env python3
"""Gentle explore for the next wave of popular handoff shapes (common25)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cubot.pipeline import get_icon  # noqa: E402

WANTED = [
    "rocket", "tree", "flag", "crown", "wave", "bell", "anchor", "boat",
    "umbrella", "hourglass", "dumbbell", "y", "f", "paperclip", "hammer",
    "smiley", "cube-frame", "home", "phone", "key", "battery", "headphones",
    "camera", "bridge", "bottle",
]

PY = sys.executable
OUT = ROOT / "out" / "explore-common25"
PARALLEL = 3
TIME_BUDGET = "200"


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
    out = ROOT / "data" / "candidates" / "common25"
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for name in WANTED:
        row = best_row(idx, name)
        if not row:
            print(f"MISSING {name}", flush=True)
            continue
        rows = rows_for(name, row)
        if not rows:
            print(f"no mask {name}", flush=True)
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
        print(f"{entry['number']:3d} {entry['name']:20} -> {entry['mask']}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest {len(manifest)} shapes", flush=True)
    return manifest


def explore_one(entry: dict) -> dict:
    """Each shape gets its own out dir so parallel results.jsonl lines don't collide."""
    shape_out = OUT / "by-shape" / entry["name"]
    shape_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        PY, "-u", str(ROOT / "tools" / "explore_shape.py"),
        "--name", entry["name"],
        str(ROOT / entry["mask"]),
        "--out", str(shape_out),
        "--profile", "gentle",
        "--yaw-expand",
        "--time-budget", TIME_BUDGET,
        "-k", "6",
        "--max-candidates", "8",
    ]
    print(f"=== START {entry['name']}", flush=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    # keep last 8 lines of stdout for the log
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-8:])
    if proc.returncode != 0:
        print(f"=== FAIL-CMD {entry['name']} rc={proc.returncode}\n{tail}\n{(proc.stderr or '')[-500:]}",
              flush=True)
    results_path = shape_out / "results.jsonl"
    row = None
    if results_path.is_file():
        for line in reversed(results_path.read_text().splitlines()):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("name") == entry["name"]:
                row = r
                break
    ok = bool(row and row.get("complete") and row.get("hard_ok"))
    moves = row.get("moves") if row else None
    viol = len((row or {}).get("violations") or [])
    print(f"=== DONE {'PASS' if ok else 'FAIL'} {entry['name']} moves={moves} viol={viol}", flush=True)
    if tail:
        print(tail, flush=True)
    return {**entry, "result": row, "ok": ok, "stdout_tail": tail}


def patch(passes: list[dict]) -> None:
    if not passes:
        print("nothing to patch", flush=True)
        return
    args = [PY, str(ROOT / "tools" / "patch_handoff_shapes.py")]
    for p in passes:
        run_dir = Path(p["record_json"]).parent
        args.append(f"--shape={p['name']}={run_dir}")
        args.append(f"--number={p['name']}={p['number']}")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.check_call(args, cwd=ROOT, env=env)
    print(f"patched {len(passes)} shapes", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    results_path = OUT / "batch_results.jsonl"
    if results_path.exists():
        results_path.unlink()

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futs = {pool.submit(explore_one, e): e for e in manifest}
        for fut in as_completed(futs):
            row = fut.result()
            rows.append(row)
            with results_path.open("a") as fh:
                fh.write(json.dumps({k: v for k, v in row.items() if k != "stdout_tail"}) + "\n")

    passes = []
    for row in rows:
        r = row.get("result") or {}
        if row.get("ok") and r.get("record_json"):
            passes.append({
                "name": row["name"],
                "number": row["number"],
                "record_json": r["record_json"],
                "moves": r.get("moves"),
            })
    (OUT / "passes.json").write_text(json.dumps(passes, indent=2) + "\n")
    print(f"\npasses {len(passes)}/{len(manifest)}", flush=True)
    for p in passes:
        print(f"  PASS {p['name']} moves={p['moves']}", flush=True)
    fails = [row["name"] for row in rows if not row.get("ok")]
    if fails:
        print("fails:", ", ".join(sorted(fails)), flush=True)

    patch(passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
