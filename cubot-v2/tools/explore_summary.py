#!/usr/bin/env python3
"""Summarize an exploration run written by ``tools/explore_shape.py``.

Reads ``<out>/results.jsonl``, keeps the best variant per concept, and writes
``summary.md`` (ranked table), ``contact-sheet-blind.png`` (numbered, no
labels, for the recognizability pick), ``contact-sheet-labeled.png`` and
``handoff-manifest.json`` — every loose-passing row in
``cubot.handoff.manifest.v1`` form, so the winners export with
``tools/export_handoff.py --manifest <out>/handoff-manifest.json`` after the
blind pick (``docs/METHOD.md``).  Pass ``--only`` to restrict the manifest to
the picked names.

Usage (from ``cubot-v2/``)::

    uv run python tools/explore_summary.py --out out/explore-20260919
    uv run python tools/explore_summary.py --out out/explore-20260919 --only rocket mug bell
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
        return (6, 0, 0, 0)
    if not row["threadings"]:
        return (5, 0, 0, 0)
    if row["complete"] is None:
        return (4, 0, 0, 0)
    if row["complete"] and row["hard_ok"]:
        # 3D rows carry a tier: 1 = passes loose on the table, 2 = passes platform only.
        klass = 0 if (row.get("tier") or 1) == 1 else 1
    elif row["complete"]:
        klass = 2
    else:
        klass = 3
    finish_ok = row["ends_flat"] or row.get("final_upright")
    return (klass, 0 if finish_ok else 1, -(row["worst_soft"] or 0.0), row["moves"] or 999)


def verdict(row: dict) -> str:
    if not row["screen_ok"]:
        return f"structural: {row['screen_stage']}"
    if not row["threadings"]:
        return f"roll-{row['thread_status']}"
    if row["complete"] is None:
        return "threadable, no plan"
    if row["complete"] and row["hard_ok"]:
        return "PASS" if (row.get("tier") or 1) == 1 else f"PASS ({row.get('fold_profile') or 'platform'}, tier 2)"
    if row["complete"]:
        return f"violating ({len(row['violations'])})"
    return "partial"


def load_rows(root: Path, prefer: dict[str, str] | None = None) -> list[dict]:
    """Merge every ``results.jsonl`` under ``root`` (one per parallel worker).

    ``prefer`` maps a concept name to the variant that should represent it
    even when another variant ranks better mechanically (the blind pick may
    prefer a better-reading drawing); it must have a loose-passing row.
    """

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
    prefer = prefer or {}
    for row in rows:
        tried[row["name"]] = tried.get(row["name"], 0) + 1
        wanted = prefer.get(row["name"])
        if wanted is not None:
            if row["variant"] != wanted:
                continue
            current = best.get(row["name"])
            if current is None or rank_key(row) < rank_key(current):
                best[row["name"]] = row
            continue
        if row["name"] not in best or rank_key(row) < rank_key(best[row["name"]]):
            best[row["name"]] = row
    missing = sorted(name for name in prefer if name not in best)
    if missing:
        raise SystemExit(f"--prefer variants without a row: {', '.join(f'{n}={prefer[n]}' for n in missing)}")
    for name, row in best.items():
        row["variants_tried"] = tried[name]
    return sorted(best.values(), key=lambda r: (rank_key(r), r["name"]))


def is_layered(row: dict) -> bool:
    return (row.get("layers") or 1) > 1


def review_png(row: dict) -> str | None:
    """Iso render for layered (3D) rows, top view for flat drawings."""

    return row.get("iso_png") if is_layered(row) and row.get("iso_png") else row["top_png"]


def finish_label(row: dict) -> str:
    if is_layered(row):
        if row.get("final_upright") is None:
            return "-"
        return "upright" if row["final_upright"] else f"tilted ({row.get('final_up_axis')})"
    return {True: "flat", False: "STANDING", None: "-"}[row["ends_flat"]]


def write_summary(rows: list[dict], out_root: Path) -> Path:
    lines = [
        "| # | shape | variant | tried | threadings | verdict | moves | worst soft | finish | box | render |",
        "|---|-------|---------|------:|-----------:|---------|------:|-----------:|--------|-----|--------|",
    ]
    for index, row in enumerate(rows, start=1):
        finish = finish_label(row)
        png = review_png(row)
        render = f"`{Path(png).relative_to(out_root)}`" if png else "-"
        lines.append(
            f"| {index} | {row['name']} | {row['variant']} | {row['variants_tried']} | {row['threadings']} | "
            f"{verdict(row)} | {row['moves'] if row['moves'] is not None else '-'} | "
            f"{row['worst_soft'] if row['worst_soft'] is not None else '-'} | {finish} | "
            f"{'x'.join(str(b) for b in row['box'])} | {render} |"
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


MANIFEST_SCHEMA = "cubot.handoff.manifest.v1"


def write_manifest(rows: list[dict], out_root: Path, only: set[str] | None = None) -> Path:
    """Write the loose-passing rows as a handoff manifest; run dirs are relative to the manifest."""

    shapes = []
    for row in rows:
        if not (row["complete"] and row["hard_ok"] and row["record_json"]):
            continue
        if only is not None and row["name"] not in only:
            continue
        run_dir = Path(row["record_json"]).resolve().parent
        try:
            run = str(run_dir.relative_to(out_root.resolve()))
        except ValueError:
            run = str(run_dir)
        entry = {"name": row["name"], "variant": row["variant"], "run": run,
                 "moves": row["moves"], "ends_flat": row["ends_flat"]}
        if is_layered(row):
            entry.update({"tier": row.get("tier"), "profile": row.get("fold_profile"),
                          "final_upright": row.get("final_upright"), "volumetric": row.get("volumetric")})
        shapes.append(entry)
    if only is not None:
        missing = sorted(only - {s["name"] for s in shapes})
        if missing:
            raise SystemExit(f"--only names without a loose-passing row: {', '.join(missing)}")
    path = out_root / "handoff-manifest.json"
    path.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "source": str(out_root), "shapes": shapes}, indent=2) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("out/explore-20260919"))
    parser.add_argument("--columns", type=int, default=6)
    parser.add_argument("--only", nargs="*", default=None, metavar="NAME",
                        help="restrict handoff-manifest.json to these picked concept names")
    parser.add_argument("--prefer", nargs="*", default=[], metavar="NAME=VARIANT",
                        help="represent NAME by VARIANT (a better-reading pick) instead of the mechanics-best row")
    args = parser.parse_args()

    prefer = {}
    for spec in args.prefer:
        name, sep, variant = spec.partition("=")
        if not sep or not variant:
            parser.error(f"--prefer expects NAME=VARIANT, got {spec!r}")
        prefer[name] = variant
    rows = load_rows(args.out, prefer)
    summary = write_summary(rows, args.out)
    manifest = write_manifest(rows, args.out, None if args.only is None else set(args.only))
    rendered = [(row["name"], review_png(row)) for row in rows if review_png(row) and Path(review_png(row)).is_file()]
    if rendered:
        contact_sheet(rendered, args.out / "contact-sheet-labeled.png", columns=args.columns, show_labels=True)
        contact_sheet(rendered, args.out / "contact-sheet-blind.png", columns=args.columns, show_labels=False)
    counts: dict[str, int] = {}
    for row in rows:
        key = verdict(row).split(" ")[0].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    print(f"{len(rows)} shapes: {counts}; wrote {summary} and {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
