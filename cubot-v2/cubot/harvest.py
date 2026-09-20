"""Seeded, time-bounded, resumable icon harvests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable, Sequence

from .generate import DEMO_NAMES
from .pipeline import PipelineRun, run_pipeline
from .match import DEFAULT_PROPOSALS
from .records import dump_json
from .viz import contact_sheet


@dataclass(frozen=True, slots=True)
class HarvestResult:
    root: Path
    state_path: Path
    summary_path: Path
    contact_sheet_path: Path | None
    completed: tuple[str, ...]
    attempted: tuple[str, ...]
    elapsed_s: float
    exhausted: bool


def _load_state(path: Path, *, seed: int, icons: Sequence[str]) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema": "cubot.harvest.v1",
            "seed": seed,
            "icons": list(icons),
            "completed": {},
            "attempts": {},
            "archive": {},
        }
    state = json.loads(path.read_text())
    if state.get("schema") != "cubot.harvest.v1":
        raise ValueError(f"unsupported harvest state in {path}")
    if int(state.get("seed")) != seed or list(state.get("icons", [])) != list(icons):
        raise ValueError("resume state seed/icon list differs from this harvest")
    state.setdefault("completed", {})
    state.setdefault("attempts", {})
    state.setdefault("archive", {})
    return state


def _archive_run(state: dict[str, Any], icon: str, run: PipelineRun, *, seed: int) -> None:
    """Update a small MAP-Elites-style archive of route phenotypes.

    Bins retain distinct completion/verdict, progress, path-length, and soft
    score regimes.  The archive references immutable checked records rather
    than trusting stored flags or duplicating bulky move reports in state.
    """

    icon_archive = state["archive"].setdefault(icon, {})
    for index, candidate in enumerate(run.record.plans):
        category = "passing" if candidate.complete and candidate.hard_ok else "violating" if candidate.complete else "partial"
        worst = min(candidate.scores.values(), default=1.0)
        descriptor = ":".join(
            (
                category,
                f"progress-{candidate.goal_progress // 3}",
                f"moves-{len(candidate.moves) // 4}",
                f"soft-{min(4, int(worst * 5.0))}",
            )
        )
        quality = list(candidate.rank_key)
        previous = icon_archive.get(descriptor)
        if previous is None or tuple(quality) < tuple(previous["quality"]):
            icon_archive[descriptor] = {
                "quality": quality,
                "record": str(run.record_path),
                "candidate": index,
                "seed": seed,
            }


def harvest(
    out_dir: str | Path,
    *,
    icons: Sequence[str] = DEMO_NAMES,
    seed: int = 0,
    duration_s: float = 30.0 * 60.0,
    profile: str = "easy",
    strict_profile: str = "strict",
    k: int = 5,
    beam_width: int = 1200,
    node_budget: int | None = None,
    detour_budget: int | None = None,
    max_candidates: int = 8,
    family: str | Path | None = None,
    proposals: str | Path | None = None,
    library_root: str | Path | None = None,
    resume: bool = True,
    pipeline_runner: Callable[..., PipelineRun] = run_pipeline,
) -> HarvestResult:
    """Harvest icon plans until ``duration_s`` expires.

    State is flushed after every icon, so interruption loses at most the
    currently running icon.  A resumed run skips only entries whose record and
    top render still exist; stale completion markers are repaired by rerunning
    that icon.  The seed for an icon is independent of resume order.
    """

    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    if not icons:
        raise ValueError("harvest needs at least one icon")
    ordered_icons = tuple(dict.fromkeys(str(icon) for icon in icons))
    proposal_source = DEFAULT_PROPOSALS if proposals is None else Path(proposals)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    runs_root = root / "runs"
    state_path = root / "harvest-state.json"
    if not resume and state_path.exists():
        state_path.unlink()
    state = _load_state(state_path, seed=seed, icons=ordered_icons)
    started = time.monotonic()
    deadline = started + duration_s
    attempted: list[str] = []

    for icon_index, icon in enumerate(ordered_icons):
        completed = state["completed"].get(icon)
        if completed:
            record_path = Path(completed.get("record", ""))
            top_path = Path(completed.get("top", ""))
            if record_path.is_file() and top_path.is_file():
                continue
            state["completed"].pop(icon, None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        attempted.append(icon)
        attempt = {
            "seed": seed + icon_index,
            "started_unix_s": time.time(),
            "status": "running",
        }
        state["attempts"][icon] = attempt
        dump_json(state, state_path)
        unfinished = sum(
            1 for candidate in ordered_icons[icon_index:] if candidate not in state["completed"]
        )
        fair_share = remaining / max(1, unfinished)
        # Matching, strict replay, persistence, and rendering happen after the
        # folder's own clock. Reserve part of each fair share so the outer
        # harvest deadline remains a meaningful wall-clock bound.
        finalization_reserve = min(30.0, fair_share * 0.15)
        icon_budget = max(0.001, fair_share - finalization_reserve)
        try:
            run = pipeline_runner(
                icon,
                runs_root,
                profile=profile,
                strict_profile=strict_profile,
                seed=seed + icon_index,
                k=k,
                beam_width=beam_width,
                family=family,
                proposals=proposal_source,
                time_budget_s=icon_budget,
                node_budget=node_budget,
                detour_budget=detour_budget,
                max_candidates=max_candidates,
                library_root=library_root,
            )
        except Exception as exc:  # keep the batch resumable and try other icons
            attempt.update(
                {
                    "status": "failed",
                    "finished_unix_s": time.time(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            dump_json(state, state_path)
            continue
        attempt["finished_unix_s"] = time.time()
        _archive_run(state, icon, run, seed=seed + icon_index)
        has_complete = any(candidate.complete for candidate in run.record.plans)
        attempt["status"] = "complete" if has_complete else "partial"
        attempt["record"] = str(run.record_path)
        if has_complete:
            state["completed"][icon] = {
                "record": str(run.record_path),
                "checked_plan": str(run.raw_plan_path),
                "loose_report": str(run.loose_report_path),
                "strict_report": str(run.strict_report_path),
                "top": str(run.top_path),
                "iso": str(run.iso_path),
                "hard_ok": any(
                    candidate.complete and candidate.hard_ok
                    for candidate in run.record.plans
                ),
            }
        dump_json(state, state_path)

    entries: list[tuple[str, Path]] = []
    for icon in ordered_icons:
        item = state["completed"].get(icon)
        if item and Path(item["top"]).is_file():
            entries.append((icon, Path(item["top"])))
    sheet_path: Path | None = None
    if entries:
        # Hide concept names on the review sheet so recognizability is tested
        # rather than cued by the label.  The ordered icon list in summary.json
        # is the explicit number-to-name legend after review.
        sheet_path = contact_sheet(
            entries,
            root / "contact-sheet.png",
            show_labels=False,
        )

    elapsed = time.monotonic() - started
    completed_names = tuple(icon for icon in ordered_icons if icon in state["completed"])
    summary = {
        "schema": "cubot.harvest-summary.v1",
        "seed": seed,
        "duration_s": duration_s,
        "elapsed_s": elapsed,
        "completed": list(completed_names),
        "attempted_this_run": attempted,
        "remaining": [icon for icon in ordered_icons if icon not in state["completed"]],
        "loose_passing": [
            icon
            for icon in ordered_icons
            if state["completed"].get(icon, {}).get("hard_ok")
        ],
        "archive_bins": {
            icon: len(state["archive"].get(icon, {})) for icon in ordered_icons
        },
        "contact_sheet": str(sheet_path) if sheet_path else None,
        "contact_sheet_legend": {
            str(index): icon for index, (icon, _) in enumerate(entries, start=1)
        },
        "state": str(state_path),
    }
    summary_path = root / "summary.json"
    dump_json(summary, summary_path)
    return HarvestResult(
        root=root,
        state_path=state_path,
        summary_path=summary_path,
        contact_sheet_path=sheet_path,
        completed=completed_names,
        attempted=tuple(attempted),
        elapsed_s=elapsed,
        exhausted=time.monotonic() >= deadline and len(completed_names) < len(ordered_icons),
    )


__all__ = ["HarvestResult", "harvest"]
