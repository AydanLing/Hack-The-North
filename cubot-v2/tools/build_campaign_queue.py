#!/usr/bin/env python3
"""Build fold queues for overnight / multi-machine campaigns.

Queues are JSONL rows ``{name, mask, category}`` for ``tools/explore_batch.py``.

Modes:
  pick-key     — friend's library pick-key.json (66 concepts that already PASSed elsewhere)
  candidates   — every ``data/candidates/**/*.txt`` mask (breadth; huge)
  new-masks    — only masks under places/vehicles that are not yet in handoff
  loose-handoff— re-fold current handoff shapes that are still accept_profile=loose

Usage (from cubot-v2/)::

    python tools/build_campaign_queue.py --mode pick-key -o out/campaign/queue-pick.jsonl
    python tools/build_campaign_queue.py --mode candidates -o out/campaign/queue-all.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prefer_one_per_concept(entries: list[dict]) -> list[dict]:
    """Keep one row per concept name — prefer the pick-key's listed variant."""
    best: dict[str, dict] = {}
    for e in entries:
        name = e["name"]
        if name not in best:
            best[name] = e
    return [best[n] for n in sorted(best)]


def queue_pick_key() -> list[dict]:
    key = json.loads((ROOT / "docs/library-20260919/pick-key.json").read_text())
    items = []
    for e in prefer_one_per_concept(key):
        mask = ROOT / e["mask"]
        if not mask.is_file():
            print(f"skip missing mask {e['mask']}")
            continue
        category = Path(e["mask"]).parent.name
        items.append({"name": e["name"], "mask": str(mask.relative_to(ROOT)), "category": category,
                      "preferred_variant": e.get("variant"), "prior_moves": e.get("moves")})
    return items


def queue_candidates(*, only_dirs: list[str] | None = None) -> list[dict]:
    root = ROOT / "data" / "candidates"
    items = []
    for path in sorted(root.rglob("*.txt")):
        if path.name == "manifest.json":
            continue
        rel = path.relative_to(ROOT)
        category = path.parent.name
        if only_dirs and category not in only_dirs and path.parent.parent.name not in only_dirs:
            # allow filtering by top-level category folder name
            top = path.relative_to(root).parts[0]
            if top not in only_dirs:
                continue
        # concept name: strip -vN suffix
        stem = path.stem
        name = stem.rsplit("-v", 1)[0] if "-v" in stem else stem
        items.append({"name": name, "mask": str(rel), "category": top if (top := path.relative_to(root).parts[0]) else category})
    return items


def queue_loose_handoff() -> list[dict]:
    idx = json.loads((ROOT / "handoff" / "index.json").read_text())
    items = []
    for s in idx["shapes"]:
        path_json = ROOT / "handoff" / s["dir"] / "path.json"
        doc = json.loads(path_json.read_text())
        ap = (doc.get("status") or {}).get("accept_profile") or s.get("accept_profile")
        if ap == "gentle":
            continue
        sil = ROOT / "handoff" / s["dir"] / "silhouette.txt"
        # Prefer library/candidate mask if we have mask_variant
        variant = s.get("mask_variant") or doc.get("provenance", {}).get("mask_variant")
        mask = None
        if variant:
            hits = list((ROOT / "data" / "candidates").rglob(f"{variant}.txt"))
            if hits:
                mask = hits[0]
        if mask is None and sil.is_file():
            # write ephemeral mask from silhouette
            out = ROOT / "data" / "candidates" / "_handoff_refold"
            out.mkdir(parents=True, exist_ok=True)
            text = sil.read_text()
            if "---" in text:
                continue
            rows = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() and not ln.startswith("//")]
            if sum(c == "#" for r in rows for c in r) != 27:
                continue
            mask = out / f"{s['name']}.txt"
            mask.write_text("\n".join(rows) + "\n")
        if mask is None:
            continue
        items.append({
            "name": s["name"],
            "mask": str(mask.relative_to(ROOT)),
            "category": "handoff-loose",
            "number": int(s["number"]),
        })
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True,
                    choices=("pick-key", "candidates", "places-vehicles", "loose-handoff"))
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.mode == "pick-key":
        items = queue_pick_key()
    elif args.mode == "candidates":
        items = queue_candidates()
    elif args.mode == "places-vehicles":
        items = queue_candidates(only_dirs=["places", "vehicles"])
    else:
        items = queue_loose_handoff()

    if args.limit is not None:
        items = items[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        for item in items:
            fh.write(json.dumps(item) + "\n")
    print(f"wrote {len(items)} items -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
