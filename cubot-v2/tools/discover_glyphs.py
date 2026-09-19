#!/usr/bin/env python3
"""Discover new demo shapes by sweeping a glyph atlas on the shipped roll.

Stages (each resumable from its cache under ``--out``):

  atlas   generate exact-27-cell masks for every glyph (strokes, bitmaps, runs,
          boundary perturbation)                          -> atlas.jsonl
  thread  solve each unique mask for exact shipped-roll threadings
                                                          -> thread-cache.jsonl
  rank    score threadable masks (recognition + legibility), pick a shortlist,
          render blind/labeled contact sheets              -> ranked.json, rank/
  fold    run the standard pipeline (fold search + loose/strict checks) on the
          shortlist within a wall-clock budget             -> runs/, fold-state.json
  judge   optional Claude blind naming of the folded silhouettes (annotation)
                                                          -> judge.json
  report  summary.json, SUMMARY.md, folded contact sheets, optional digest

Examples:
  uv run python tools/discover_glyphs.py --out out/discovery-smoke --dry-run --glyphs h t n plus --assert-known
  uv run python tools/discover_glyphs.py --out out/discovery-20260919 --seed 20260919
  uv run python tools/discover_glyphs.py --out out/discovery-20260919 --stages report --digest docs/DISCOVERY.md
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from cubot.discovery import (  # noqa: E402
    FOLD_STATE,
    stage_atlas,
    stage_fold,
    stage_judge,
    stage_rank,
    stage_report,
    stage_thread,
)
from cubot.generate.glyph_atlas import GLYPHS, canonical_key, rows_to_cells, select_glyphs  # noqa: E402
from cubot.generate.parametric import _PATTERNS  # noqa: E402

STAGES = ("atlas", "thread", "rank", "fold", "judge", "report")


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def _assert_known(atlas_rows: list[dict], concepts: set[str]) -> None:
    """The generator must reproduce the shipped exact-27 demo masks it covers."""

    known = {
        name: canonical_key({(x, y) for x, y, _ in rows_to_cells(_PATTERNS[name])})
        for name in ("h", "t", "n", "plus")
        if name in concepts
    }
    seen = {row["mask_hash"] for row in atlas_rows}
    from cubot.generate.glyph_atlas import mask_hash

    missing = [name for name, key in known.items() if mask_hash(key) not in seen]
    if missing:
        raise SystemExit(f"--assert-known failed: shipped masks not regenerated: {', '.join(missing)}")
    _log(f"assert-known: shipped masks regenerated for {', '.join(known) or 'nothing'}")


def _emit_promotion(out_dir: Path, slugs: list[str]) -> None:
    import json

    state = json.loads((out_dir / FOLD_STATE).read_text())
    threads = {}
    for line in (out_dir / "thread-cache.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            threads[row["mask_hash"]] = row
    for slug in slugs:
        entry = state[slug]
        thread = threads[entry["mask_hash"]]
        plan = entry["plan"] or {}
        rows = thread["rows"]
        states = plan.get("goal_states") or thread["poses"][0]["states"]
        base = plan.get("goal_base", thread["poses"][0]["base"])
        name = entry["concept"]
        print(f"# ---- {slug} -> parametric._PATTERNS[{name!r}]")
        print(f"    {name!r}: (")
        for row in rows:
            print(f"        {row!r},")
        print("    ),")
        print(f"# ---- {slug} -> demo_icons.DEMO_ICONS[{name!r}]")
        print(f"_{name.upper().replace('-', '_')}_STATES = {tuple(states)!r}")
        print(f"# base={base}; source record: {entry['record']}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "discovery")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--dry-run", action="store_true", help="atlas, thread and rank only")
    parser.add_argument("--glyphs", nargs="+", help="concept names (default: all)")
    parser.add_argument("--categories", nargs="+", choices=("letter", "digit", "symbol", "icon"))
    parser.add_argument("--max-variants-per-base", type=int, default=2000)
    parser.add_argument("--node-budget", type=int, default=100_000, help="solver node budget per mask")
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="solver processes")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--per-concept", type=int, default=3)
    parser.add_argument("--quota", nargs="*", default=["letter=0.4"], help="category=fraction caps")
    parser.add_argument("--pick-file", type=Path, help="one slug per line; restricts the fold stage")
    parser.add_argument("--k", type=int, default=2, help="threadings folded per candidate")
    parser.add_argument("--fold-budget-s", type=float, default=30.0)
    parser.add_argument("--fold-wall-s", type=float, default=3600.0)
    parser.add_argument("--fold-node-budget", type=int, default=200_000)
    parser.add_argument("--detour-budget", type=int, default=0)
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--fold-workers", type=int, default=1, help="parallel fold processes")
    parser.add_argument("--refold", action="store_true", help="re-run non-passing candidates when the budgets are larger")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--judge-model", default="claude-opus-5")
    parser.add_argument("--judge-max", type=int, default=120)
    parser.add_argument("--digest", type=Path, help="also write the summary markdown here (e.g. docs/DISCOVERY.md)")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--assert-known", action="store_true")
    parser.add_argument("--emit-promotion", nargs="+", metavar="SLUG")
    args = parser.parse_args(argv)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.emit_promotion:
        _emit_promotion(out_dir, args.emit_promotion)
        return 0
    stages = ["atlas", "thread", "rank"] if args.dry_run else list(args.stages)
    if args.no_judge and "judge" in stages:
        stages.remove("judge")
    resume = not args.no_resume
    glyphs = select_glyphs(args.glyphs, args.categories)
    _log(f"discover: {len(glyphs)} glyphs, stages {stages}, out {out_dir}")

    atlas_rows = None
    threads = None
    selected = None
    fold_state = None
    if "atlas" in stages or any(s in stages for s in ("thread", "rank")):
        atlas_rows = stage_atlas(
            glyphs,
            out_dir,
            seed=args.seed,
            max_per_base=args.max_variants_per_base,
            resume=resume,
            workers=args.workers,
            log=_log,
        )
        if args.assert_known:
            _assert_known(atlas_rows, {g.concept for g in glyphs})
    if "thread" in stages or "rank" in stages:
        threads = stage_thread(
            atlas_rows,
            out_dir,
            node_budget=args.node_budget,
            retry_timeouts=args.retry_timeouts,
            workers=args.workers,
            log=_log,
        )
    if "rank" in stages:
        selected = stage_rank(
            atlas_rows,
            threads,
            out_dir,
            per_concept=args.per_concept,
            top_n=args.top_n,
            quota=args.quota,
            render=not args.no_render,
            log=_log,
        )
    if "fold" in stages:
        if selected is None or threads is None:
            import json

            ranked = json.loads((out_dir / "ranked.json").read_text())
            selected = [c for c in ranked["candidates"] if c.get("selected")]
            threads = {}
            for line in (out_dir / "thread-cache.jsonl").read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    threads[row["mask_hash"]] = row
        picks = None
        if args.pick_file:
            picks = [line.strip() for line in args.pick_file.read_text().splitlines() if line.strip()]
        fold_state = stage_fold(
            selected,
            threads,
            out_dir,
            seed=args.seed,
            k=args.k,
            fold_budget_s=args.fold_budget_s,
            wall_s=args.fold_wall_s,
            detour_budget=args.detour_budget,
            node_budget=args.fold_node_budget,
            max_candidates=args.max_candidates,
            picks=picks,
            refold=args.refold,
            workers=args.fold_workers,
            resume=resume,
            log=_log,
        )
    if "judge" in stages:
        if fold_state is None:
            import json

            path = out_dir / FOLD_STATE
            fold_state = json.loads(path.read_text()) if path.is_file() else {}
        from vision_judge import judge_factory

        judge = judge_factory(model=args.judge_model, cache_path=out_dir / "judge-cache.jsonl", log=_log)
        stage_judge(fold_state, out_dir, judge=judge, limit=args.judge_max, log=_log)
    if "report" in stages:
        stage_report(out_dir, digest_path=args.digest, log=_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
