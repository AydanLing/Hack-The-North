#!/usr/bin/env python3
"""Blind-naming prefilter for library candidates (before and after folding).

Recognizability is decided by a human blind pick (``docs/RULES.md``); at
library scale the fold minutes have to be rationed first.  This tool renders
candidates as clean silhouettes on numbered *blind* sheets, records what a
judge who never saw the intended names calls each tile, and turns the
agreement into a fold queue or a survivors list.  It filters and orders; it
never registers anything.

Three steps, all from ``cubot-v2/``::

    # 1. sheets: render tiles + numbered blind sheets + key.json
    uv run python tools/blind_judge.py sheets --masks 'data/candidates/*/*.txt' \\
        --threadable-only --out out/library-20260919/judge-pre
    uv run python tools/blind_judge.py sheets --results out/library-20260919 \\
        --out out/library-20260919/judge-post              # folded PASS rows, drawn as authored

    # 2. judge: either the Claude vision judge (needs ANTHROPIC_API_KEY) ...
    uv run python tools/blind_judge.py judge --out out/library-20260919/judge-pre --backend api
    #    ... or labels written by fresh-context reviewers who saw only the blind sheets:
    #    labels.json = {"blind-01": {"1": {"label": "cat", "confidence": 0.7, "alternatives": ["fox"]}, ...}}
    uv run python tools/blind_judge.py judge --out out/library-20260919/judge-pre \\
        --backend import --labels out/library-20260919/judge-pre/labels.json

    # 3. queue: keep the best-named variants per concept for tools/explore_batch.py
    uv run python tools/blind_judge.py queue --out out/library-20260919/judge-pre \\
        --per-concept 2 --queue out/library-20260919/queue.jsonl

Concept aliases come from ``data/library-concepts.json`` (and the mask's
concept name, taken from ``<name>-vN.txt``); matching reuses
``tools/vision_judge.label_matches``.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
for entry in (str(ROOT), str(TOOLS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from cubot.config import load_machine  # noqa: E402
from cubot.generate.base import PixelTarget, parse_grid  # noqa: E402
from cubot.shapes import screen  # noqa: E402
from cubot.solver import solve  # noqa: E402
from cubot.viz import contact_sheet  # noqa: E402
from explore_shape import read_mask, variant_label  # noqa: E402
from explore_summary import load_rows  # noqa: E402
from vision_judge import label_matches  # noqa: E402

CONCEPTS_PATH = ROOT / "data" / "library-concepts.json"
TILES_PER_SHEET = 24
COLUMNS = 6


def render_rows(rows: list[str], out_path: Path, *, cell_px: int = 54, margin: int = 36) -> Path:
    """Render mask rows as one dark silhouette, exactly as drawn (top row first).

    ``cubot.viz.render_silhouette`` projects onto the two longest axes, which
    transposes tall drawings; a blind judge must see the drawing the author
    drew, so tiles are rendered straight from the rows.
    """

    from PIL import Image, ImageDraw

    width = len(rows[0]) * cell_px + 2 * margin
    height = len(rows) * cell_px + 2 * margin
    image = Image.new("RGB", (width, height), (248, 247, 243))
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == "#":
                x0, y0 = margin + x * cell_px, margin + y * cell_px
                draw.rectangle((x0, y0, x0 + cell_px, y0 + cell_px), fill=(31, 39, 46))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def concept_of(variant: str) -> str:
    stem, sep, suffix = variant.rpartition("-v")
    return stem if sep and suffix.isdigit() else variant


def load_aliases(path: Path = CONCEPTS_PATH) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return {entry["name"]: list(entry.get("aliases", [])) for entry in data}


def aliases_for(name: str, table: dict[str, list[str]]) -> list[str]:
    return [name, name.replace("-", " "), *table.get(name, [])]


# --- sheets -----------------------------------------------------------------


def tiles_from_masks(patterns: list[str], out: Path, *, threadable_only: bool) -> list[dict]:
    machine = load_machine()
    roll = machine.roll
    tether = bool(getattr(machine, "has_tether", False))
    tiles: list[dict] = []
    skipped = 0
    for pattern in patterns:
        for mask_path in sorted(Path(p) for p in glob.glob(pattern)):
            rows = read_mask(mask_path)
            variant = variant_label(mask_path)
            name = concept_of(variant)
            target = PixelTarget(parse_grid(rows), name, "")
            threadings = None
            if threadable_only:
                report = screen(target.cells, 27)
                if not report.ok:
                    skipped += 1
                    continue
                result = solve(target.cells, roll, all_solutions=True, max_solutions=64, tether=tether)
                threadings = len(result.solutions)
                if not result.found:
                    skipped += 1
                    continue
            png = render_rows(rows, out / "tiles" / f"{variant}.png")
            tiles.append({"name": name, "variant": variant, "mask": str(mask_path), "png": str(png),
                          "threadings": threadings, "mask_rows": rows})
    if threadable_only:
        print(f"{len(tiles)} threadable masks rendered, {skipped} skipped (structural or UNSAT)")
    return tiles


def tiles_from_results(root: Path, out: Path, *, all_variants: bool) -> list[dict]:
    if all_variants:
        rows = [
            json.loads(line)
            for path in sorted(root.rglob("results.jsonl"))
            for line in path.read_text().splitlines()
            if line.strip()
        ]
    else:
        rows = load_rows(root)
    tiles: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not (row.get("complete") and row.get("hard_ok") and row.get("goal_is_mask") and row.get("top_png")):
            continue
        key = (row["name"], row["variant"])
        if key in seen or not Path(row["top_png"]).is_file():
            continue
        seen.add(key)
        png = render_rows(list(row["mask_rows"]), out / "tiles" / f"{row['variant']}.png")
        tiles.append({"name": row["name"], "variant": row["variant"], "mask": row["mask"], "png": str(png),
                      "fold_png": row["top_png"],
                      "threadings": row["threadings"], "mask_rows": row["mask_rows"],
                      "record_json": row.get("record_json"), "moves": row.get("moves"), "ends_flat": row.get("ends_flat")})
    return tiles


def write_sheets(tiles: list[dict], out: Path, *, seed: int) -> Path:
    """Shuffle (so neighbours do not hint at each other), tile into sheets, write key.json."""

    import random

    order = list(range(len(tiles)))
    random.Random(seed).shuffle(order)
    key: list[dict] = []
    for sheet_index, start in enumerate(range(0, len(order), TILES_PER_SHEET), start=1):
        sheet = f"blind-{sheet_index:02d}"
        chunk = order[start : start + TILES_PER_SHEET]
        entries = [(tiles[i]["name"], tiles[i]["png"]) for i in chunk]
        contact_sheet(entries, out / f"{sheet}.png", columns=COLUMNS, show_labels=False)
        contact_sheet(entries, out / f"{sheet}-labeled.png", columns=COLUMNS, show_labels=True)
        for tile_number, i in enumerate(chunk, start=1):
            key.append({"sheet": sheet, "tile": tile_number, **tiles[i]})
    path = out / "key.json"
    path.write_text(json.dumps(key, indent=1) + "\n")
    print(f"{len(tiles)} tiles on {(len(tiles) + TILES_PER_SHEET - 1) // TILES_PER_SHEET} sheets -> {out}")
    return path


# --- judge ------------------------------------------------------------------


def judge_api(key: list[dict], out: Path, aliases: dict[str, list[str]], model: str | None) -> list[dict]:
    from vision_judge import DEFAULT_MODEL, judge_silhouette, make_client

    client = make_client()
    if client is None:
        raise SystemExit("api backend unavailable (install the judge extra and set ANTHROPIC_API_KEY)")
    rows = []
    for entry in key:
        result = judge_silhouette(client, Path(entry["png"]), aliases=aliases_for(entry["name"], aliases),
                                  model=model or DEFAULT_MODEL, cache_path=out / "api-cache.jsonl")
        if result is None:
            continue
        rows.append({**entry, "label": result.label, "confidence": result.confidence,
                     "alternatives": result.alternatives, "matched": result.matched,
                     "matched_alternative": result.matched_alternative, "backend": f"api:{result.model}"})
    return rows


def judge_import(key: list[dict], labels_path: Path, aliases: dict[str, list[str]]) -> list[dict]:
    labels = json.loads(labels_path.read_text())
    rows = []
    missing = 0
    for entry in key:
        got = labels.get(entry["sheet"], {}).get(str(entry["tile"]))
        if got is None:
            missing += 1
            continue
        label = str(got.get("label", "unclear"))
        alternatives = [str(a) for a in got.get("alternatives", []) if str(a).strip()]
        wanted = aliases_for(entry["name"], aliases)
        rows.append({**entry, "label": label, "confidence": float(got.get("confidence", 0.0)),
                     "alternatives": alternatives, "matched": label_matches(label, wanted),
                     "matched_alternative": any(label_matches(a, wanted) for a in alternatives),
                     "backend": f"import:{labels_path.name}"})
    if missing:
        print(f"warning: {missing} tiles have no label in {labels_path}")
    return rows


def judge_score(row: dict) -> tuple:
    """Higher is better: exact match, then alternative match, then confidence."""

    return (row["matched"], row["matched_alternative"], row["confidence"])


def write_judgements(rows: list[dict], out: Path) -> None:
    path = out / "judgements.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)
    lines = ["| concept | variants | matched | best label (conf) | other labels |", "|---|---:|---:|---|---|"]
    named = 0
    for name in sorted(by_name):
        group = sorted(by_name[name], key=judge_score, reverse=True)
        matched = [r for r in group if r["matched"] or r["matched_alternative"]]
        named += bool(matched)
        best = group[0]
        others = ", ".join(sorted({f"{r['label']}" for r in group[1:]})) or "-"
        lines.append(f"| {name} | {len(group)} | {len(matched)} | {best['label']} ({best['confidence']:.2f}) | {others} |")
    lines.insert(0, f"{named} of {len(by_name)} concepts named by the blind judge; {sum(r['matched'] for r in rows)} "
                    f"of {len(rows)} tiles matched exactly.\n")
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(lines[0].strip())


# --- queue ------------------------------------------------------------------


def write_queue(judge_dir: Path, queue_path: Path, *, per_concept: int, include_unmatched: bool) -> None:
    rows = [json.loads(line) for line in (judge_dir / "judgements.jsonl").read_text().splitlines() if line.strip()]
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)
    items = []
    unmatched_concepts = []
    for name in sorted(by_name):
        group = sorted(by_name[name], key=judge_score, reverse=True)
        keep = [r for r in group if r["matched"] or r["matched_alternative"]]
        if not keep:
            unmatched_concepts.append(name)
            if not include_unmatched:
                continue
            keep = group
        for row in keep[:per_concept]:
            items.append({"name": name, "mask": row["mask"], "category": Path(row["mask"]).parent.name,
                          "label": row["label"], "confidence": row["confidence"]})
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text("".join(json.dumps(item) + "\n" for item in items))
    print(f"{len(items)} masks for {len(by_name) - len(unmatched_concepts)} named concepts -> {queue_path}")
    if unmatched_concepts:
        print(f"{len(unmatched_concepts)} concepts with no named variant: {', '.join(unmatched_concepts)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sheets = sub.add_parser("sheets", help="render tiles and numbered blind sheets")
    sheets.add_argument("--masks", nargs="*", default=[], help="glob(s) of candidate mask files")
    sheets.add_argument("--results", type=Path, help="exploration out dir with results.jsonl (folded PASS rows)")
    sheets.add_argument("--all-variants", action="store_true", help="with --results, every PASS variant, not best per concept")
    sheets.add_argument("--threadable-only", action="store_true", help="with --masks, gate first and skip UNSAT/structural")
    sheets.add_argument("--out", type=Path, required=True)
    sheets.add_argument("--seed", type=int, default=0)

    judge = sub.add_parser("judge", help="record blind labels for the sheets under --out")
    judge.add_argument("--out", type=Path, required=True)
    judge.add_argument("--backend", choices=("api", "import"), default="import")
    judge.add_argument("--labels", type=Path, help="import backend: labels.json keyed by sheet then tile number")
    judge.add_argument("--model", default=None)
    judge.add_argument("--concepts", type=Path, default=CONCEPTS_PATH)

    queue = sub.add_parser("queue", help="write a fold queue from the judgements")
    queue.add_argument("--out", type=Path, required=True, help="judge dir holding judgements.jsonl")
    queue.add_argument("--queue", type=Path, required=True)
    queue.add_argument("--per-concept", type=int, default=2)
    queue.add_argument("--include-unmatched", action="store_true", help="also queue concepts the judge did not name")

    args = parser.parse_args()
    if args.command == "sheets":
        args.out.mkdir(parents=True, exist_ok=True)
        tiles = tiles_from_masks(args.masks, args.out, threadable_only=args.threadable_only) if args.masks else []
        if args.results:
            tiles += tiles_from_results(args.results, args.out, all_variants=args.all_variants)
        if not tiles:
            raise SystemExit("nothing to render")
        write_sheets(tiles, args.out, seed=args.seed)
        return 0
    if args.command == "judge":
        key = json.loads((args.out / "key.json").read_text())
        aliases = load_aliases(args.concepts)
        if args.backend == "api":
            rows = judge_api(key, args.out, aliases, args.model)
        else:
            if not args.labels:
                parser.error("--labels is required for the import backend")
            rows = judge_import(key, args.labels, aliases)
        write_judgements(rows, args.out)
        return 0
    write_queue(args.out, args.queue, per_concept=args.per_concept, include_unmatched=args.include_unmatched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
