#!/usr/bin/env python3
"""Promote finished campaign shapes into the library, name them, and push.

Run this repeatedly while a campaign is folding.  It is idempotent: shapes
already in the handoff are left alone, so it can be called every few minutes to
get new work in front of teammates without waiting for the whole queue.

A shape has to clear three gates before it ships, because the old library shows
what happens when it does not:

1. *Certified* -- the fold search completed and every hard check passed.
2. *Clean* -- move count within ``--max-ratio`` of the detents the goal needs.
   A compact footprint often only folds via long detours, and those are the
   paths that made the shipped square take 16 moves for 6 detents.
3. *Recognisable* -- the footprint scores at least ``--min-iou`` against an
   ideal glyph, which is also where its name comes from.  The old library was
   named by intent, so its "zigzag" turns once.

    python tools/harvest_and_push.py --campaign out/n17-forward
    python tools/harvest_and_push.py --campaign out/n17-forward --push
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_path_quality import audit_path  # noqa: E402
from match_glyphs import TEMPLATES, cells_of, parse_rows, scaled_iou  # noqa: E402


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def name_shape(rows: list[str], prepared: dict) -> tuple[str, float]:
    """Best-matching concept for a footprint, with its resemblance score."""
    fp = cells_of(rows)
    best_name, best = "", 0.0
    for concept, template in prepared.items():
        iou = scaled_iou(fp, template)
        if iou > best:
            best_name, best = concept, iou
    return best_name, best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", type=Path, required=True,
                    help="campaign --out dir (holds <category>/results.jsonl)")
    ap.add_argument("--handoff", type=Path, default=ROOT / "handoff-17")
    ap.add_argument("--machine", default="config/machine-17.toml")
    ap.add_argument("--min-iou", type=float, default=0.65)
    ap.add_argument("--max-ratio", type=float, default=1.5)
    ap.add_argument("--push", action="store_true", help="commit and push when anything is added")
    args = ap.parse_args()

    results = sorted(args.campaign.glob("*/results.jsonl"))
    if not results:
        print(f"no results.jsonl under {args.campaign}")
        return 1
    rows = [json.loads(l) for r in results for l in r.open()]
    passing = [r for r in rows if r.get("complete") and r.get("hard_ok")]
    print(f"{len(rows)} folded, {len(passing)} certified")

    prepared = {c: cells_of(parse_rows(TEMPLATES[c])) for c in TEMPLATES}

    # What the handoff already has, so re-runs are no-ops.
    index_path = args.handoff / "index.json"
    have = set()
    if index_path.exists():
        idx = json.loads(index_path.read_text())
        shapes = idx.get("shapes", idx)
        seq = shapes if isinstance(shapes, list) else list(shapes)
        for s in seq:
            have.add((s.get("name") if isinstance(s, dict) else s).lower())
    print(f"handoff already has {len(have)}: {sorted(have)}")

    # Pick the best candidate per concept: cleanest path, then best resemblance.
    best_per_concept: dict[str, tuple] = {}
    for r in passing:
        shape_rows = [l for l in (r.get("mask_rows") or []) if l.strip()]
        if not shape_rows:
            continue
        concept, iou = name_shape(shape_rows, prepared)
        if iou < args.min_iou or concept.lower() in have:
            continue
        record = r.get("record_json")
        run_dir = Path(record).parent if record else None
        if run_dir is None or not (run_dir / "record.json").exists():
            continue
        cand = (iou, r["moves"], run_dir, r["name"])
        prev = best_per_concept.get(concept)
        if prev is None or (cand[1], -cand[0]) < (prev[1], -prev[0]):
            best_per_concept[concept] = cand

    if not best_per_concept:
        print("nothing new clears the gates yet")
        return 0

    print(f"\ncandidates: {len(best_per_concept)}")
    for concept, (iou, moves, run_dir, raw) in sorted(best_per_concept.items()):
        print(f"  {concept:12} IoU {iou:.2f}  {moves} moves  ({raw})")

    # Existing shapes, re-exported from their original records so numbering and
    # provenance stay consistent.
    existing = []
    for d in sorted((args.handoff / "shapes").glob("*/")):
        doc = json.loads((d / "path.json").read_text())
        src = Path(doc["provenance"]["source_record"]).parent
        existing += ["--shape", f"{doc['name']}={src}"]

    def export(into: Path, shapes: list[str]):
        # export_handoff writes NN-name dirs but never prunes, so a shorter
        # second pass would leave the dropped shapes behind and renumber around
        # them. Clear the shapes dir to keep the handoff exactly what we asked.
        shapes_dir = into / "shapes"
        if shapes_dir.exists():
            import shutil
            shutil.rmtree(shapes_dir)
        return run([sys.executable, "tools/export_handoff.py", "--no-demo",
                    "--machine", args.machine, "--out", str(into)] + shapes)

    # Trial export into a scratch dir so thrashing candidates never touch the
    # real handoff.
    import tempfile
    dropped: list[tuple[str, float]] = []
    keep_new: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        trial = Path(tmp) / "handoff"
        cand_args = []
        for concept, (_, _, run_dir, _) in sorted(best_per_concept.items()):
            cand_args += ["--shape", f"{concept}={run_dir}"]
        proc = export(trial, existing + cand_args)
        if proc.returncode != 0:
            print("trial export failed:\n" + (proc.stderr or proc.stdout)[-1500:])
            return 1
        for d in sorted((trial / "shapes").glob("*/")):
            doc = json.loads((d / "path.json").read_text())
            if doc["name"].lower() in have:
                continue
            rec = audit_path(doc)
            if rec["ratio"] > args.max_ratio:
                dropped.append((doc["name"], rec["ratio"]))
            else:
                keep_new += ["--shape",
                             f"{doc['name']}={Path(doc['provenance']['source_record']).parent}"]

    if dropped:
        print("\nnot shipping (path thrashes): "
              + ", ".join(f"{n} ratio {r:.2f}" for n, r in dropped))
    if not keep_new:
        print("\nno clean new shapes this round")
        return 0

    proc = export(args.handoff, existing + keep_new)
    if proc.returncode != 0:
        print("export failed:\n" + (proc.stderr or proc.stdout)[-1500:])
        return 1
    print("\n" + proc.stdout.strip()[-800:])

    added = [keep_new[i + 1].split("=", 1)[0] for i in range(0, len(keep_new), 2)]
    print(f"\nadded: {', '.join(sorted(added))}")

    if args.push:
        run(["git", "add", "-A"])
        msg = ("Add " + ", ".join(sorted(added)) + " to the 17-cube library.\n\n"
               "Found by walking the chain forward, so each footprint is a real\n"
               "configuration rather than a hopeful drawing. Names come from glyph\n"
               "overlap (>= "
               + f"{args.min_iou}"
               + "), and each path spends close to one detent per\n"
                 "off-zero joint, so nothing here thrashes.")
        c = run(["git", "commit", "-q", "-m", msg])
        if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
            print("commit failed:\n" + (c.stderr or c.stdout)[-600:])
            return 1
        p = run(["git", "push", "-q", "origin", "main"])
        if p.returncode != 0:
            print("push failed:\n" + (p.stderr or p.stdout)[-600:])
            return 1
        print("pushed to main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
