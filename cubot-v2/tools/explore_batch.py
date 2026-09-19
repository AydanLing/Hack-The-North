#!/usr/bin/env python3
"""Fold a queue of gated masks with a bounded worker pool (resume-safe).

``tools/explore_shape.py`` folds one concept per process; at library scale
(hundreds of masks, ~3-4 min each) the folds need a queue.  This runner takes
a JSONL queue of ``{"name", "mask", "category"}`` items, folds each with
:func:`explore_shape.explore_one` in a ``ProcessPoolExecutor`` capped at
``--workers`` (keep it at 3 on the 8-core machine: six workers slow every CAD
edge check about four-fold, ``docs/FINDINGS.md``), and appends rows to
``<out>/<category>/results.jsonl`` exactly as the single-shape driver does, so
``tools/explore_summary.py`` needs no changes.  Items whose ``(name, variant)``
already has a row under the target directory are skipped, so the command can
be re-run after an interruption.

Usage (from ``cubot-v2/``)::

    uv run python tools/explore_batch.py --queue out/library-20260919/queue.jsonl \\
        --out out/library-20260919 --workers 3 -k 1 --time-budget 150
    uv run python tools/explore_batch.py --out out/library-20260919 --retry-violating \\
        --workers 3 -k 1 --time-budget 240

``--retry-violating`` ignores the queue and re-folds, into ``<out>/verify/``,
every threadable row that did not pass (complete-but-violating, partial, or no
plan) — a violating verdict is a budget statement, and most flip at 240 s.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import contextlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
for entry in (str(ROOT), str(TOOLS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from explore_shape import explore_one, summary_line  # noqa: E402


def read_queue(path: Path) -> list[dict]:
    items = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        item.setdefault("category", Path(item["mask"]).parent.name)
        items.append(item)
    return items


def existing_rows(root: Path) -> dict[tuple[str, str], dict]:
    """Best-known row per ``(name, variant)`` under ``root`` (PASS wins over anything else)."""

    rows: dict[tuple[str, str], dict] = {}
    for path in sorted(root.rglob("results.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = (row["name"], row["variant"])
            if key not in rows or (row.get("complete") and row.get("hard_ok") and row.get("goal_is_mask")):
                rows[key] = row
    return rows


def passed(row: dict) -> bool:
    return bool(row.get("complete") and row.get("hard_ok") and row.get("goal_is_mask"))


def retry_items(out: Path, *, only_unpassed_concepts: bool) -> list[dict]:
    rows = existing_rows(out)
    passed_concepts = {name for (name, _), row in rows.items() if passed(row)}
    items = []
    for (name, variant), row in sorted(rows.items()):
        if passed(row) or not row.get("threadings"):
            continue
        if only_unpassed_concepts and name in passed_concepts:
            continue
        category = Path(row["mask"]).parent.name
        items.append({"name": name, "mask": row["mask"], "category": category})
    return items


def fold_task(item: dict, out_root: Path, time_budget_s: float, k: int, max_candidates: int, seed: int) -> dict:
    mask = Path(item["mask"])
    out_dir = out_root / item["category"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"fold-{mask.stem}.log"
    with log_path.open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        row = explore_one(
            item["name"], mask, out_dir,
            family=None, time_budget_s=time_budget_s, k=k, max_candidates=max_candidates, seed=seed,
        )
    with (out_dir / "results.jsonl").open("a") as handle:
        handle.write(json.dumps(row) + "\n")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queue", type=Path, help="JSONL of {name, mask, category?} items")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--time-budget", type=float, default=150.0)
    parser.add_argument("-k", type=int, default=1)
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None, help="fold at most this many items")
    parser.add_argument("--retry-violating", action="store_true",
                        help="re-fold every threadable non-passing row under --out into <out>/verify/")
    parser.add_argument("--only-unpassed-concepts", action="store_true",
                        help="with --retry-violating, skip variants of concepts that already have a PASS")
    parser.add_argument("--dry-run", action="store_true", help="list what would be folded")
    args = parser.parse_args()

    if args.retry_violating:
        items = retry_items(args.out, only_unpassed_concepts=args.only_unpassed_concepts)
        out_root = args.out / "verify"
    else:
        if not args.queue:
            parser.error("--queue is required unless --retry-violating is given")
        items = read_queue(args.queue)
        out_root = args.out
    done = existing_rows(out_root)
    pending = [item for item in items if (item["name"], Path(item["mask"]).stem) not in done]
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"{len(items)} items, {len(items) - len(pending)} already folded under {out_root}, {len(pending)} to fold "
          f"with {args.workers} workers at -k {args.k} --time-budget {args.time_budget}", flush=True)
    if args.dry_run or not pending:
        for item in pending:
            print(f"  {item['name']}: {item['mask']}")
        return 0

    started = time.monotonic()
    passes = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fold_task, item, out_root, args.time_budget, args.k, args.max_candidates, args.seed): item
            for item in pending
        }
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                row = future.result()
            except Exception as error:  # noqa: BLE001 - one bad mask must not kill the queue
                print(f"[{index}/{len(pending)}] {item['name']}/{Path(item['mask']).stem}: ERROR {type(error).__name__}: {error}", flush=True)
                continue
            if passed(row):
                passes += 1
            elapsed = time.monotonic() - started
            print(f"[{index}/{len(pending)} {elapsed / 60:.1f} min, {passes} PASS] {summary_line(row)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
