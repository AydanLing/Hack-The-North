#!/usr/bin/env python3
"""Summarize an exploration run written by ``tools/explore_shape.py``.

Reads ``<out>/results.jsonl``, keeps the best variant per concept, and writes
``summary.md`` (ranked table), ``contact-sheet-blind.png`` (numbered, no
labels, for the recognizability pick) and ``contact-sheet-labeled.png``.

Usage (from ``cubot-v2/``)::

    uv run python tools/explore_summary.py --out out/explore-20260919
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.viz import contact_sheet  # noqa: E402


def rank_key(row: dict) -> tuple:
    """Lower is better: passing < complete-violating < partial < threadable-no-plan < UNSAT < structural."""

    if not row["screen_ok"]:
        return (5, 0, 0, 0)
    if not row["threadings"]:
        return (4, 0, 0, 0)
    if row["complete"] is None:
        return (3, 0, 0, 0)
    if row["complete"] and row["hard_ok"]:
        klass = 0
    elif row["complete"]:
        klass = 1
    else:
        klass = 2
    return (klass, 0 if row["ends_flat"] else 1, -(row["worst_soft"] or 0.0), row["moves"] or 999)


def verdict(row: dict) -> str:
    if not row["screen_ok"]:
        return f"structural: {row['screen_stage']}"
    if not row["threadings"]:
        return f"roll-{row['thread_status']}"
    if row["complete"] is None:
        return "threadable, no plan"
    if row["complete"] and row["hard_ok"]:
        return "PASS"
    if row["complete"]:
        return f"violating ({len(row['violations'])})"
    return "partial"


def load_rows(root: Path) -> list[dict]:
    """Merge every ``results.jsonl`` under ``root`` (one per parallel worker)."""

    rows = [
        json.loads(line)
        for path in sorted(root.rglob("results.jsonl"))
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    # Folded rows are trusted only when the driver confirmed the rank-0 goal is
    # the mask itself; rows written before that check existed may describe a
    # family substitute and are dropped.  Gate-only rows (no plan) are kept.
    rows = [row for row in rows if row["complete"] is None or row.get("goal_is_mask") is True]
    best: dict[str, dict] = {}
    tried: dict[str, int] = {}
    for row in rows:
        tried[row["name"]] = tried.get(row["name"], 0) + 1
        if row["name"] not in best or rank_key(row) < rank_key(best[row["name"]]):
            best[row["name"]] = row
    for name, row in best.items():
        row["variants_tried"] = tried[name]
    return sorted(best.values(), key=lambda r: (rank_key(r), r["name"]))


def write_summary(rows: list[dict], out_root: Path) -> Path:
    lines = [
        "| # | shape | variant | tried | threadings | verdict | moves | worst soft | finish | box | render |",
        "|---|-------|---------|------:|-----------:|---------|------:|-----------:|--------|-----|--------|",
    ]
    for index, row in enumerate(rows, start=1):
        finish = {True: "flat", False: "STANDING", None: "-"}[row["ends_flat"]]
        render = f"`{Path(row['top_png']).relative_to(out_root)}`" if row["top_png"] else "-"
        lines.append(
            f"| {index} | {row['name']} | {row['variant']} | {row['variants_tried']} | {row['threadings']} | "
            f"{verdict(row)} | {row['moves'] if row['moves'] is not None else '-'} | "
            f"{row['worst_soft'] if row['worst_soft'] is not None else '-'} | {finish} | "
            f"{row['box'][0]}x{row['box'][1]} | {render} |"
        )
    lines.append("")
    for row in rows:
        lines.append(f"### {row['name']} ({row['variant']}) — {verdict(row)}")
        lines.append("```")
        lines.extend(row["mask_rows"])
        lines.append("```")
        if row["violations"]:
            lines.append(f"violations: {', '.join(row['violations'])}")
        lines.append("")
    path = out_root / "summary.md"
    path.write_text("\n".join(lines))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("out/explore-20260919"))
    parser.add_argument("--columns", type=int, default=6)
    args = parser.parse_args()

    rows = load_rows(args.out)
    summary = write_summary(rows, args.out)
    rendered = [(row["name"], row["top_png"]) for row in rows if row["top_png"] and Path(row["top_png"]).is_file()]
    if rendered:
        contact_sheet(rendered, args.out / "contact-sheet-labeled.png", columns=args.columns, show_labels=True)
        contact_sheet(rendered, args.out / "contact-sheet-blind.png", columns=args.columns, show_labels=False)
    counts: dict[str, int] = {}
    for row in rows:
        key = verdict(row).split(" ")[0].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    print(f"{len(rows)} shapes: {counts}; wrote {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
