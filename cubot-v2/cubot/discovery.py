"""Glyph-atlas discovery: atlas → thread → rank → fold → judge → report.

Every stage is a plain function over JSON-friendly rows so it can be tested
without the CLI, resumed from its on-disk cache, and rerun deterministically.
The solver stage uses a node budget only (no wall clock) so a rerun makes
zero new solver calls; the fold stage is bounded by wall clock and records
its elapsed time because completion under a budget is machine dependent.

Ranking is offline and explainable: recognition distance to the glyph's own
ideal mask, plus a handful of legibility features.  It decides only which
candidates are worth 30 seconds of fold search; recognisability itself is
still judged by a human on the blind contact sheet.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import time
from typing import Any

from .config import load_machine
from .folder import ends_flat_on_table, replay_tracked
from .generate.base import PixelTarget, parse_grid
from .generate.glyph_atlas import (
    GLYPHS,
    Glyph,
    count_holes,
    rows_to_cells,
    variants,
)
from .lattice import fk, pose_cells
from .match import MatchResult, recognition_score
from .pipeline import run_pipeline
from .records import Pose, SearchStatus, dump_json
from .shapes import canonical_planar, screen
from .solver import solve
from .viz import contact_sheet, render_silhouette

ATLAS_FILE = "atlas.jsonl"
THREAD_CACHE = "thread-cache.jsonl"
RANKED_FILE = "ranked.json"
FOLD_STATE = "fold-state.json"
JUDGE_FILE = "judge.json"
SUMMARY_JSON = "summary.json"
SUMMARY_MD = "SUMMARY.md"

# Iconicity weights (lower score is better).  Tuned by eye on the first
# contact sheet; they only order candidates for fold search.
W_FIDELITY = 1.00
W_NUBS = 0.15
W_THIN = 0.10
W_SYMMETRY = 0.05
W_HOLES = 0.25
W_BLOB = 2.5          # per unit of bounding-box fill above BLOB_FILL
BLOB_FILL = 0.62      # a 27-cell mask filling more of its box is a slab, not a glyph


# --------------------------------------------------------------------------
# JSONL helpers


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _append_jsonl(handle: Any, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# stage 1: atlas


def stage_atlas(
    glyphs: Sequence[Glyph],
    out_dir: Path,
    *,
    seed: int,
    max_per_base: int,
    resume: bool = True,
    workers: int = 1,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Generate (or reload) the exact-27 variant rows for the chosen glyphs."""

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ATLAS_FILE
    header = {
        "kind": "header",
        "seed": seed,
        "max_per_base": max_per_base,
        "glyphs": [g.concept for g in glyphs],
    }
    if resume and path.is_file():
        rows = _read_jsonl(path)
        if rows and rows[0] == header:
            log(f"atlas: reusing {len(rows) - 1} variants from {path}")
            return rows[1:]
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    if workers > 1 and len(glyphs) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            per_glyph = list(pool.map(_atlas_task, [(g.concept, seed, max_per_base) for g in glyphs]))
    else:
        per_glyph = [_atlas_task((g.concept, seed, max_per_base)) for g in glyphs]
    with path.open("w", encoding="utf-8") as handle:
        _append_jsonl(handle, header)
        for glyph, glyph_rows in zip(glyphs, per_glyph, strict=True):
            for row in glyph_rows:
                rows.append(row)
                _append_jsonl(handle, row)
            log(f"atlas: {glyph.concept}: {len(glyph_rows)} variants")
    log(f"atlas: {len(rows)} variants in {time.monotonic() - started:.1f}s")
    return rows


def _atlas_task(args: tuple[str, int, int]) -> list[dict[str, Any]]:
    concept, seed, max_per_base = args
    glyph = GLYPHS[concept]
    return [
        {
            "concept": variant.concept,
            "rows": list(variant.rows),
            "ideal_rows": list(variant.ideal_rows),
            "generator": variant.generator,
            "mask_hash": variant.mask_hash,
        }
        for variant in variants(glyph, seed=seed, max_per_base=max_per_base)
    ]


# --------------------------------------------------------------------------
# stage 2: threading


def _verify_pose(pose: Pose, cells: Sequence[tuple[int, int, int]]) -> bool:
    replayed, _ = fk(pose.states, pose.roll, pose.base)
    return len(set(replayed)) == 27 and canonical_planar(replayed) == canonical_planar(cells)


def _thread_one(
    rows: Sequence[str],
    roll: str,
    node_budget: int,
    max_solutions: int,
    solver: Callable[..., Any] = solve,
) -> dict[str, Any]:
    """Screen and solve one mask; top-level so a process pool can pickle it."""

    cells = rows_to_cells(rows)
    entry: dict[str, Any] = {"roll": roll, "node_budget": node_budget, "rows": list(rows)}
    report = screen(cells, 27, include_hamiltonian=False)
    if not report.ok:
        entry.update({"status": "SCREEN_FAIL", "reason": report.stage, "poses": []})
        return entry
    result = solver(
        cells,
        roll,
        budget_nodes=node_budget,
        all_solutions=True,
        max_solutions=max_solutions,
    )
    poses = [
        {"states": list(pose.states), "base": pose.base}
        for pose in result.poses
        if _verify_pose(pose, cells)
    ]
    entry.update(
        {
            "status": result.status.value,
            "exhaustive": bool(result.exhaustive),
            "nodes": int(result.nodes),
            "poses": poses,
        }
    )
    return entry


def _thread_task(args: tuple[str, list[str], str, int, int]) -> tuple[str, dict[str, Any]]:
    digest, rows, roll, node_budget, max_solutions = args
    return digest, _thread_one(rows, roll, node_budget, max_solutions)


def stage_thread(
    atlas_rows: Sequence[dict[str, Any]],
    out_dir: Path,
    *,
    roll: str | None = None,
    node_budget: int = 100_000,
    max_solutions: int = 8,
    retry_timeouts: bool = False,
    workers: int = 1,
    solver: Callable[..., Any] = solve,
    log: Callable[[str], None] = print,
    flush_every: int = 200,
) -> dict[str, dict[str, Any]]:
    """Thread every unique mask once; cached by mask hash in JSONL.

    The cache is keyed on the dihedral-canonical mask, so a mask shared by
    several concepts is solved once.  With ``workers > 1`` masks are solved in
    a process pool; results are written in completion order but every entry
    is independent of the others, so the cache content is order-free.
    """

    roll = roll or load_machine().roll
    path = out_dir / THREAD_CACHE
    cache: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        cache[row["mask_hash"]] = row
    pending: dict[str, dict[str, Any]] = {}
    for row in atlas_rows:
        digest = row["mask_hash"]
        previous = cache.get(digest)
        stale = previous is None or previous.get("roll") != roll
        if previous is not None and previous["status"] == SearchStatus.TIMEOUT.value:
            stale = stale or (retry_timeouts and previous.get("node_budget", 0) < node_budget)
        if stale and digest not in pending:
            pending[digest] = row
    log(f"thread: {len(cache)} cached, {len(pending)} to solve (budget {node_budget} nodes, {workers} worker(s))")
    started = time.monotonic()
    counts = {"FOUND": 0, "UNSAT": 0, "TIMEOUT": 0, "SCREEN_FAIL": 0}

    def results() -> Iterable[tuple[str, dict[str, Any]]]:
        if workers <= 1 or solver is not solve:
            for digest, row in pending.items():
                yield digest, _thread_one(row["rows"], roll, node_budget, max_solutions, solver)
            return
        from concurrent.futures import ProcessPoolExecutor

        tasks = [(digest, list(row["rows"]), roll, node_budget, max_solutions) for digest, row in pending.items()]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            yield from pool.map(_thread_task, tasks, chunksize=16)

    with path.open("a", encoding="utf-8") as handle:
        for index, (digest, entry) in enumerate(results(), start=1):
            entry["mask_hash"] = digest
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            cache[digest] = entry
            _append_jsonl(handle, entry)
            if index % flush_every == 0:
                handle.flush()
                log(f"thread: {index}/{len(pending)} {counts} {time.monotonic() - started:.0f}s")
    log(f"thread: done {counts} in {time.monotonic() - started:.1f}s")
    return cache


# --------------------------------------------------------------------------
# stage 3: ranking


@dataclass(slots=True)
class Features:
    fidelity: float
    transform: str
    thick_fraction: float
    nubs: int
    symmetry: float
    hole_mismatch: int
    compactness: float
    perimeter: float
    iconicity: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _points(rows: Sequence[str]) -> set[tuple[int, int]]:
    return {(x, y) for x, y, _ in rows_to_cells(rows)}


def _degree(cell: tuple[int, int], occupied: set[tuple[int, int]]) -> int:
    x, y = cell
    return sum(n in occupied for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))


def _thick_fraction(points: set[tuple[int, int]]) -> float:
    covered: set[tuple[int, int]] = set()
    for x, y in points:
        block = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
        if block <= points:
            covered |= block
    return len(covered) / max(1, len(points))


def _symmetry(points: set[tuple[int, int]]) -> float:
    if not points:
        return 1.0
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    mirror_x = {(max_x + min_x - x, y) for x, y in points}
    mirror_y = {(x, max_y + min_y - y) for x, y in points}
    rot = {(max_x + min_x - x, max_y + min_y - y) for x, y in points}
    return min(len(points ^ other) for other in (mirror_x, mirror_y, rot)) / len(points)


def features_for(rows: Sequence[str], ideal_rows: Sequence[str], glyph: Glyph) -> Features:
    cells = rows_to_cells(rows)
    ideal = PixelTarget(parse_grid(list(ideal_rows)), concept=glyph.concept, caption=glyph.concept)
    score = recognition_score(cells, ideal)
    points = _points(rows)
    ideal_points = _points(ideal_rows)
    ideal_endpoints = {c for c in ideal_points if _degree(c, ideal_points) == 1}
    nubs = sum(
        1
        for c in points
        if _degree(c, points) == 1 and c not in ideal_endpoints
    )
    thick = _thick_fraction(points)
    symmetry = _symmetry(points)
    holes = count_holes(points)
    hole_mismatch = 0 if glyph.holes is None else abs(holes - glyph.holes)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    width = max(xs) - min(xs) + 1
    height = max(ys) - min(ys) + 1
    perimeter = sum(4 - _degree(c, points) for c in points) / (4.0 * len(points))
    result = Features(
        fidelity=float(score.distance),
        transform=score.transform,
        thick_fraction=thick,
        nubs=nubs,
        symmetry=symmetry,
        hole_mismatch=hole_mismatch,
        compactness=len(points) / float(width * height),
        perimeter=perimeter,
    )
    # Thick strokes read well for letters; run-based glyphs (zigzag, stairs,
    # spiral) are lines by nature, so there thickness means a merged slab.
    thin_penalty = (1.0 - thick) if glyph.prefers_thick else thick
    blob_penalty = max(0.0, result.compactness - BLOB_FILL)
    result.iconicity = (
        W_FIDELITY * result.fidelity
        + W_NUBS * nubs
        + W_THIN * thin_penalty
        + W_SYMMETRY * symmetry
        + W_HOLES * hole_mismatch
        + W_BLOB * blob_penalty
    )
    return result


def _parse_quota(spec: Sequence[str] | None) -> dict[str, float]:
    quota: dict[str, float] = {}
    for item in spec or ():
        name, _, value = item.partition("=")
        quota[name.strip()] = float(value)
    return quota


def stage_rank(
    atlas_rows: Sequence[dict[str, Any]],
    threads: dict[str, dict[str, Any]],
    out_dir: Path,
    *,
    per_concept: int = 3,
    top_n: int = 50,
    quota: Sequence[str] | None = ("letter=0.4",),
    glyphs: dict[str, Glyph] | None = None,
    render: bool = True,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Score every threadable variant and select the fold shortlist."""

    glyphs = glyphs or GLYPHS
    started = time.monotonic()
    scored: list[dict[str, Any]] = []
    per_concept_counts: dict[str, dict[str, int]] = {}
    for row in atlas_rows:
        entry = threads.get(row["mask_hash"])
        stats = per_concept_counts.setdefault(
            row["concept"], {"variants": 0, "FOUND": 0, "UNSAT": 0, "TIMEOUT": 0, "SCREEN_FAIL": 0}
        )
        stats["variants"] += 1
        if entry is None:
            continue
        stats[entry["status"]] = stats.get(entry["status"], 0) + 1
        if entry["status"] != "FOUND" or not entry["poses"]:
            continue
        glyph = glyphs[row["concept"]]
        feats = features_for(row["rows"], row["ideal_rows"], glyph)
        scored.append(
            {
                "concept": row["concept"],
                "category": glyph.category,
                "mask_hash": row["mask_hash"],
                "rows": list(row["rows"]),
                "ideal_rows": list(row["ideal_rows"]),
                "generator": row["generator"],
                "n_threadings": len(entry["poses"]),
                "exhaustive": bool(entry.get("exhaustive", False)),
                "features": feats.as_dict(),
                "iconicity": feats.iconicity,
            }
        )
    scored.sort(key=lambda item: (item["iconicity"], item["concept"], item["mask_hash"]))
    # Per-concept diversity first, then a global cut with category quotas.
    kept_per_concept: dict[str, int] = {}
    shortlist: list[dict[str, Any]] = []
    for item in scored:
        taken = kept_per_concept.get(item["concept"], 0)
        if taken >= per_concept:
            continue
        kept_per_concept[item["concept"]] = taken + 1
        shortlist.append(item)
    limits = {name: max(1, int(math.floor(top_n * frac))) for name, frac in _parse_quota(quota).items()}
    category_counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for item in shortlist:
        cat = item["category"]
        if len(selected) >= top_n:
            break
        if cat in limits and category_counts.get(cat, 0) >= limits[cat]:
            deferred.append(item)
            continue
        category_counts[cat] = category_counts.get(cat, 0) + 1
        selected.append(item)
    for item in deferred:
        if len(selected) >= top_n:
            break
        selected.append(item)
    selected_hashes = {(item["concept"], item["mask_hash"]) for item in selected}
    variant_index: dict[str, int] = {}
    for item in scored:
        index = variant_index.get(item["concept"], 0) + 1
        variant_index[item["concept"]] = index
        item["slug"] = f"{item['concept']}-v{index:02d}"
        item["selected"] = (item["concept"], item["mask_hash"]) in selected_hashes
    ranked = {
        "per_concept": per_concept,
        "top_n": top_n,
        "quota": list(quota or ()),
        "concept_counts": per_concept_counts,
        "candidates": scored,
    }
    dump_json(ranked, out_dir / RANKED_FILE)
    chosen = [item for item in scored if item["selected"]]
    log(
        f"rank: {len(scored)} threadable variants across "
        f"{sum(1 for c in per_concept_counts.values() if c['FOUND'])} concepts; "
        f"selected {len(chosen)} in {time.monotonic() - started:.1f}s"
    )
    if render and chosen:
        _render_sheet(chosen, out_dir / "rank", log=log)
    return chosen


def _render_sheet(
    items: Sequence[dict[str, Any]], directory: Path, *, log: Callable[[str], None], page: int = 24
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "silhouettes").mkdir(exist_ok=True)
    entries: list[tuple[str, Path]] = []
    legend: dict[int, str] = {}
    for number, item in enumerate(items, start=1):
        cells = rows_to_cells(item["rows"])
        path = render_silhouette(
            cells,
            directory / "silhouettes" / f"{item['slug']}.png",
            transform=item["features"]["transform"],
        )
        entries.append((item["slug"], path))
        legend[number] = item["slug"]
    for start in range(0, len(entries), page):
        chunk = entries[start : start + page]
        index = start // page + 1
        contact_sheet(chunk, directory / f"contact-sheet-blind-{index:02d}.png", show_labels=False)
        contact_sheet(chunk, directory / f"contact-sheet-labeled-{index:02d}.png", show_labels=True)
    dump_json(legend, directory / "legend.json")
    log(f"rank: rendered {len(entries)} silhouettes and {math.ceil(len(entries) / page)} sheet page(s) in {directory}")


# --------------------------------------------------------------------------
# stage 4: fold


def _summarise_plan(plan: Any, roll: str) -> dict[str, Any]:
    moves = list(plan.moves)
    tracked = replay_tracked(plan.start, moves)
    return {
        "complete": bool(plan.complete),
        "hard_ok": bool(plan.hard_ok),
        "goal_progress": int(plan.goal_progress),
        "moves": len(moves),
        "in_moves": sum(1 for m in moves if m.side == "in"),
        "out_moves": sum(1 for m in moves if m.side == "out"),
        "scores": dict(plan.scores),
        "worst_soft": min(plan.scores.values()) if plan.scores else None,
        "violations": list(plan.violations),
        "start_base": plan.start.base,
        "start_lying": plan.start.lying,
        "goal_base": plan.goal.base,
        "final_base": tracked.base,
        "ends_flat": ends_flat_on_table(tracked),
        "goal_states": list(plan.goal.states),
        "moves_compact": [[m.joint, m.delta, m.side] for m in moves],
    }


def _fold_one(
    item: dict[str, Any],
    entry: dict[str, Any],
    runs_root: Path,
    *,
    roll: str,
    seed: int,
    k: int,
    fold_budget_s: float,
    detour_budget: int,
    node_budget: int,
    max_candidates: int,
    pipeline: Callable[..., Any] = run_pipeline,
) -> dict[str, Any]:
    """Fold one candidate through the pipeline and summarise the run."""

    slug = item["slug"]
    target = PixelTarget(
        parse_grid(item["rows"]),
        concept=slug,
        caption=f"A flat pixel {item['concept']}",
        source="discovery-atlas",
    )
    matches: list[MatchResult] = []
    for raw in entry["poses"][:k]:
        pose = Pose(tuple(int(s) for s in raw["states"]), roll, base=int(raw["base"]))
        cells = tuple(pose_cells(pose))
        score = recognition_score(cells, target)
        matches.append(MatchResult(pose, cells, score.distance, "exact-atlas", score.transform))
    run_started = time.monotonic()
    run = pipeline(
        target,
        runs_root,
        seed=seed,
        k=max(1, len(matches)),
        family=None,
        match_results=matches,
        time_budget_s=fold_budget_s,
        node_budget=node_budget,
        detour_budget=detour_budget,
        max_candidates=max_candidates,
        include_heart_certificate=False,
        library_root=None,
    )
    elapsed = time.monotonic() - run_started
    plans = list(run.record.plans)
    primary = plans[0] if plans else None
    summary = _summarise_plan(primary, roll) if primary is not None else None
    strict_ok = None
    strict_path = Path(run.strict_report_path)
    if strict_path.is_file():
        strict = json.loads(strict_path.read_text())
        ranked = strict.get("ranked") or []
        if ranked:
            strict_ok = bool(ranked[0].get("hard_ok", False))
    return {
        "mask_hash": item["mask_hash"],
        "concept": item["concept"],
        "record": str(run.record_path),
        "top": str(run.top_path),
        "status": run.record.status,
        "seed": seed,
        "fold_budget_s": fold_budget_s,
        "detour_budget": detour_budget,
        "elapsed_s": round(elapsed, 2),
        "fold_statuses": list(run.fold_statuses),
        "alternates": max(0, sum(1 for p in plans if p.complete and p.hard_ok) - 1),
        "strict_hard_ok": strict_ok,
        "plan": summary,
    }


def _fold_task(args: tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    item, entry, runs_root, options = args
    return item["slug"], _fold_one(item, entry, Path(runs_root), **options)


def _fold_verdict(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "no plan"
    return (
        f"{'complete' if summary['complete'] else 'partial'} "
        f"{'loose-pass' if summary['hard_ok'] else 'VIOLATES'} "
        f"{summary['moves']} moves {'flat' if summary['ends_flat'] else 'STANDING'}"
    )


def _is_passing(state_entry: dict[str, Any] | None) -> bool:
    plan = (state_entry or {}).get("plan") or {}
    return bool(plan.get("complete")) and bool(plan.get("hard_ok"))


def stage_fold(
    selected: Sequence[dict[str, Any]],
    threads: dict[str, dict[str, Any]],
    out_dir: Path,
    *,
    seed: int = 0,
    k: int = 2,
    fold_budget_s: float = 30.0,
    wall_s: float = 3600.0,
    detour_budget: int = 0,
    node_budget: int = 200_000,
    max_candidates: int = 2,
    picks: Sequence[str] | None = None,
    refold: bool = False,
    workers: int = 1,
    resume: bool = True,
    pipeline: Callable[..., Any] = run_pipeline,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    """Fold each selected candidate through the standard pipeline.

    ``refold`` re-runs only candidates whose previous attempt did not pass
    (and only when the new detour/time budgets are larger), so a cheap first
    pass can be followed by a deeper pass on the near misses.  With
    ``workers > 1`` candidates fold in parallel processes; each run writes
    its own ``runs/<slug>/`` directory and the parent owns the state file and
    the library.
    """

    machine = load_machine()
    roll = machine.roll
    state_path = out_dir / FOLD_STATE
    state: dict[str, dict[str, Any]] = {}
    if resume and state_path.is_file():
        state = json.loads(state_path.read_text())
    runs_root = out_dir / "runs"
    library_root = out_dir / "library"
    wanted = [item for item in selected if not picks or item["slug"] in set(picks)]
    todo: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(wanted):
        slug = item["slug"]
        previous = state.get(slug)
        if previous and previous.get("mask_hash") == item["mask_hash"]:
            record_ok = Path(previous.get("record", "")).is_file() and Path(previous.get("top", "")).is_file()
            deeper = (
                previous.get("detour_budget", 0) < detour_budget
                or previous.get("fold_budget_s", 0) < fold_budget_s
            )
            if record_ok and (_is_passing(previous) or not (refold and deeper)):
                continue
            if record_ok and refold is False:
                continue
        todo.append((index, item))
    log(
        f"fold: {len(todo)} of {len(wanted)} candidates to fold, {fold_budget_s:.0f}s each, "
        f"detour {detour_budget}, wall {wall_s:.0f}s, {workers} worker(s)"
    )
    started = time.monotonic()
    deadline = started + wall_s
    options = {
        "roll": roll,
        "k": k,
        "fold_budget_s": fold_budget_s,
        "detour_budget": detour_budget,
        "node_budget": node_budget,
        "max_candidates": max_candidates,
    }

    def _store(slug: str, result: dict[str, Any], done: int) -> None:
        state[slug] = result
        dump_json(state, state_path)
        try:
            from .library import Library

            Library(library_root).add(json.loads(Path(result["record"]).read_text()), replace=True)
        except (OSError, ValueError, KeyError) as error:  # pragma: no cover - library is advisory
            log(f"fold: {slug}: library update skipped ({error})")
        log(f"fold: {done}/{len(todo)} {slug}: {_fold_verdict(result['plan'])} ({result['elapsed_s']:.0f}s)")

    if workers <= 1 or pipeline is not run_pipeline:
        for done, (index, item) in enumerate(todo, start=1):
            remaining = deadline - time.monotonic()
            if remaining < fold_budget_s + 30.0:
                log(f"fold: stopping before {item['slug']}; {remaining:.0f}s left of the wall budget")
                break
            result = _fold_one(
                item, threads[item["mask_hash"]], runs_root, seed=seed + index, pipeline=pipeline, **options
            )
            _store(item["slug"], result, done)
        return state

    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    queue = list(todo)
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        running: dict[Any, str] = {}
        while queue or running:
            while queue and len(running) < workers:
                remaining = deadline - time.monotonic()
                if remaining < fold_budget_s + 30.0:
                    log(f"fold: wall budget nearly spent; {len(queue)} candidates left unfolded")
                    queue.clear()
                    break
                index, item = queue.pop(0)
                task = (item, threads[item["mask_hash"]], str(runs_root), {**options, "seed": seed + index})
                running[pool.submit(_fold_task, task)] = item["slug"]
            if not running:
                break
            finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for future in finished:
                running.pop(future)
                slug, result = future.result()
                done += 1
                _store(slug, result, done)
    return state


# --------------------------------------------------------------------------
# stage 5: judge (optional)


def stage_judge(
    fold_state: dict[str, dict[str, Any]],
    out_dir: Path,
    *,
    judge: Callable[[Path, Sequence[str]], dict[str, Any] | None] | None,
    glyphs: dict[str, Glyph] | None = None,
    limit: int = 120,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    """Blind-name each folded silhouette; annotation only, never a gate.

    ``judge`` is injected (see ``tools/vision_judge.py``) so this package never
    imports an LLM SDK; ``None`` makes the stage a no-op.
    """

    glyphs = glyphs or GLYPHS
    if judge is None:
        log("judge: skipped (no judge available)")
        return {}
    results: dict[str, dict[str, Any]] = {}
    for slug, entry in list(fold_state.items())[:limit]:
        top = Path(entry.get("top", ""))
        if not top.is_file():
            continue
        glyph = glyphs.get(entry["concept"])
        aliases = glyph.aliases if glyph else (entry["concept"],)
        judgement = judge(top, aliases)
        if judgement is None:
            continue
        results[slug] = judgement
        log(
            f"judge: {slug}: {judgement.get('label')!r} ({judgement.get('confidence', 0):.2f}) "
            f"{'✓' if judgement.get('matched') else '✗'}"
        )
    dump_json(results, out_dir / JUDGE_FILE)
    return results


# --------------------------------------------------------------------------
# stage 6: report


def _load_ranked(out_dir: Path) -> dict[str, Any]:
    path = out_dir / RANKED_FILE
    return json.loads(path.read_text()) if path.is_file() else {"candidates": [], "concept_counts": {}}


def stage_report(
    out_dir: Path,
    *,
    digest_path: Path | None = None,
    library_root: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Aggregate every stage into summary.json / SUMMARY.md (+ optional digest)."""

    ranked = _load_ranked(out_dir)
    state_path = out_dir / FOLD_STATE
    fold_state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    judge_path = out_dir / JUDGE_FILE
    judged = json.loads(judge_path.read_text()) if judge_path.is_file() else {}
    picks: dict[str, bool | None] = {}
    lib_root = library_root or (out_dir / "library")
    if lib_root.is_dir():
        from .library import Library

        for entry in Library(lib_root).entries():
            picks[entry["name"]] = entry.get("human_pick")
    by_slug = {item["slug"]: item for item in ranked.get("candidates", [])}
    rows: list[dict[str, Any]] = []
    for slug, entry in fold_state.items():
        plan = entry.get("plan") or {}
        cand = by_slug.get(slug, {})
        judgement = judged.get(slug, {})
        measured = _record_measurements(Path(entry.get("record", "")))
        rows.append(
            {
                "slug": slug,
                "concept": entry["concept"],
                "generator": cand.get("generator"),
                "rows": cand.get("rows"),
                "iconicity": cand.get("iconicity"),
                "fidelity": (cand.get("features") or {}).get("fidelity"),
                "n_threadings": cand.get("n_threadings"),
                "complete": plan.get("complete", False),
                "loose_hard_ok": plan.get("hard_ok", False),
                "strict_hard_ok": entry.get("strict_hard_ok"),
                "moves": plan.get("moves"),
                "ends_flat": plan.get("ends_flat"),
                "worst_soft": plan.get("worst_soft"),
                "max_penetration_mm": measured.get("max_penetration_mm"),
                "max_ground_depth_mm": measured.get("max_ground_depth_mm"),
                "peak_torque_nm": measured.get("peak_demand_nm"),
                "violations": plan.get("violations", []),
                "alternates": entry.get("alternates", 0),
                "elapsed_s": entry.get("elapsed_s"),
                "judge_label": judgement.get("label"),
                "judge_confidence": judgement.get("confidence"),
                "judge_matched": judgement.get("matched"),
                "human_pick": picks.get(slug),
                "record": entry.get("record"),
                "top": entry.get("top"),
            }
        )
    rows.sort(
        key=lambda r: (
            not (r["complete"] and r["loose_hard_ok"]),
            not r["complete"],
            r["iconicity"] if r["iconicity"] is not None else math.inf,
        )
    )
    passing = [r for r in rows if r["complete"] and r["loose_hard_ok"]]
    summary = {
        "schema": "cubot.discovery-summary.v1",
        "folded": len(rows),
        "complete_loose_passing": len(passing),
        "passing_concepts": sorted({r["concept"] for r in passing}),
        "concept_counts": ranked.get("concept_counts", {}),
        "candidates": rows,
    }
    dump_json(summary, out_dir / SUMMARY_JSON)
    markdown = _summary_markdown(summary, out_dir)
    (out_dir / SUMMARY_MD).write_text(markdown)
    if digest_path is not None:
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text(markdown)
    if passing:
        entries = [(r["slug"], Path(r["top"])) for r in passing if Path(r["top"]).is_file()]
        if entries:
            contact_sheet(entries, out_dir / "contact-sheet-folded-blind.png", show_labels=False)
            contact_sheet(entries, out_dir / "contact-sheet-folded-labeled.png", show_labels=True)
    log(f"report: {len(passing)} complete loose-passing of {len(rows)} folded; wrote {out_dir / SUMMARY_MD}")
    return summary


def _record_measurements(record_path: Path) -> dict[str, float]:
    """Worst per-move measurements of the primary plan, from record.json."""

    if not record_path.is_file():
        return {}
    try:
        plans = json.loads(record_path.read_text()).get("plans") or []
    except (OSError, ValueError):
        return {}
    if not plans:
        return {}
    worst: dict[str, float] = {}
    for move in plans[0].get("moves", []):
        for key, value in (move.get("checks", {}).get("measurements") or {}).items():
            if key in ("max_penetration_mm", "max_ground_depth_mm", "peak_demand_nm") and isinstance(value, (int, float)):
                worst[key] = max(worst.get(key, 0.0), float(value))
    return worst


def _summary_markdown(summary: dict[str, Any], out_dir: Path) -> str:
    lines = [
        "# Glyph-atlas discovery — summary",
        "",
        f"Generated by `tools/discover_glyphs.py` from `{out_dir}`; do not edit.",
        "Ranking is offline; recognisability is decided by a human blind pick.",
        "",
        f"- folded candidates: {summary['folded']}",
        f"- complete and loose-passing: {summary['complete_loose_passing']}"
        f" ({', '.join(summary['passing_concepts']) or 'none'})",
        "",
        "| # | slug | complete | loose | strict | moves | finishes | worst soft | pen. mm | dip mm | peak demand N·m | iconicity | judge | pick |",
        "|---|------|----------|-------|--------|------:|----------|-----------:|--------:|-------:|-----------:|----------:|-------|------|",
    ]
    for number, row in enumerate(summary["candidates"], start=1):
        judge = "—"
        if row["judge_label"] is not None:
            judge = f"{row['judge_label']} ({'✓' if row['judge_matched'] else '✗'})"
        strict = "—" if row["strict_hard_ok"] is None else ("pass" if row["strict_hard_ok"] else "fail")
        finishes = "—" if row["ends_flat"] is None else ("flat" if row["ends_flat"] else "STANDING")
        worst = "—" if row["worst_soft"] is None else f"{row['worst_soft']:.2f}"
        icon = "—" if row["iconicity"] is None else f"{row['iconicity']:.3f}"
        pick = "—" if row["human_pick"] is None else ("yes" if row["human_pick"] else "no")
        def _mm(value: Any) -> str:
            return "—" if value is None else f"{value:.2f}"

        lines.append(
            f"| {number} | {row['slug']} | {'yes' if row['complete'] else 'no'} | "
            f"{'pass' if row['loose_hard_ok'] else 'FAIL'} | {strict} | {row['moves'] or '—'} | "
            f"{finishes} | {worst} | {_mm(row['max_penetration_mm'])} | {_mm(row['max_ground_depth_mm'])} | "
            f"{_mm(row['peak_torque_nm'])} | {icon} | {judge} | {pick} |"
        )
    lines += ["", "## Per-concept threading counts", "", "| concept | variants | FOUND | UNSAT | TIMEOUT | screen fail |", "|---|--:|--:|--:|--:|--:|"]
    for concept, counts in sorted(summary["concept_counts"].items()):
        lines.append(
            f"| {concept} | {counts.get('variants', 0)} | {counts.get('FOUND', 0)} | "
            f"{counts.get('UNSAT', 0)} | {counts.get('TIMEOUT', 0)} | {counts.get('SCREEN_FAIL', 0)} |"
        )
    lines += ["", "## Silhouettes of complete loose-passing candidates", ""]
    for row in summary["candidates"]:
        if not (row["complete"] and row["loose_hard_ok"]) or not row["rows"]:
            continue
        lines += [f"### {row['slug']}", "", "```", *row["rows"], "```", ""]
        if row["violations"]:
            lines += ["violations: " + "; ".join(row["violations"]), ""]
    return "\n".join(lines) + "\n"


__all__ = [
    "Features",
    "features_for",
    "stage_atlas",
    "stage_fold",
    "stage_judge",
    "stage_rank",
    "stage_report",
    "stage_thread",
]
