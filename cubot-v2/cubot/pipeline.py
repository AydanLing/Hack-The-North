"""Offline orchestration for one icon target.

This module intentionally contains policy and persistence, not kinematics or
mechanics.  Matching proposes roll-compatible goals, :mod:`cubot.folder`
searches and checks directed paths, and this layer retains every useful class
of result (passing, violating, and partial) together with review renders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterable, Sequence

from .config import Machine, Profile, load_machine, load_profile
from .family import Family, load_family
from .folder import (
    MoveChecker,
    aggregate_reports,
    check_move,
    fold,
    load_heart_certificate,
    replay,
    replay_direct_goal,
    replay_heart,
)
from .generate import get_demo, get_icon
from .generate.base import PixelTarget
from .lattice import pose_cells
from .match import MatchResult, proposal_matches, match, recognition_distance
from .records import FoldResult, PlanCandidate, Pose, ShapeRecord, dump_json
from .runtime import run_meta
from .viz import contact_sheet, render_iso, render_silhouette, render_top


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """Files and in-memory record produced by :func:`run_pipeline`."""

    name: str
    run_dir: Path
    record_path: Path
    raw_plan_path: Path
    loose_report_path: Path
    strict_report_path: Path
    top_path: Path
    iso_path: Path
    contact_sheet_path: Path
    record: ShapeRecord
    fold_statuses: tuple[str, ...]


def _target_hash(target: PixelTarget) -> str:
    payload = json.dumps(
        {
            "concept": target.concept,
            "rows": target.rows,
            "source": target.source,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _family_entries(family: Family) -> Iterable[tuple[Pose, tuple[tuple[int, int, int], ...]]]:
    """Adapt the compact 2-D family cache to the matcher interface."""

    axes = tuple(axis for axis in range(3) if axis != family.plane_axis)
    for states, cells_2d in zip(family.states, family.cells, strict=True):
        if len(states) != 26:
            continue
        cells: list[tuple[int, int, int]] = []
        for first, second in cells_2d:
            cell = [0, 0, 0]
            cell[axes[0]] = int(first)
            cell[axes[1]] = int(second)
            cells.append(tuple(cell))  # type: ignore[arg-type]
        physical = tuple(-1 if int(value) == 2 else int(value) for value in states)
        yield Pose(physical, family.roll, family.base), tuple(cells)


def _ranked_unique(candidates: Iterable[PlanCandidate]) -> list[PlanCandidate]:
    unique: dict[tuple[Any, ...], PlanCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.start.states,
            candidate.start.base,
            candidate.goal.residues,
            tuple((move.joint, move.delta, move.side) for move in candidate.moves),
            candidate.complete,
        )
        previous = unique.get(key)
        if previous is None or candidate.rank_key < previous.rank_key:
            unique[key] = candidate
    return sorted(unique.values(), key=lambda candidate: candidate.rank_key)


def _representative_ranking(
    candidates: Iterable[PlanCandidate], limit: int
) -> list[PlanCandidate]:
    """Bound output while retaining each available result category."""

    ranked = _ranked_unique(candidates)
    if len(ranked) <= limit:
        return ranked
    selected: list[PlanCandidate] = []
    categories = (
        lambda item: item.complete and item.hard_ok,
        lambda item: item.complete and not item.hard_ok,
        lambda item: not item.complete,
    )
    for belongs in categories:
        candidate = next((item for item in ranked if belongs(item)), None)
        if candidate is not None and candidate not in selected and len(selected) < limit:
            selected.append(candidate)
    for candidate in ranked:
        if len(selected) >= limit:
            break
        if candidate not in selected:
            selected.append(candidate)
    return sorted(selected, key=lambda candidate: candidate.rank_key)


def _report_payload(
    profile: Profile,
    candidates: Sequence[PlanCandidate],
    *,
    machine: Machine,
    seed: int,
    source_hash: str,
    fold_results: Sequence[FoldResult] = (),
) -> dict[str, Any]:
    passing = [candidate for candidate in candidates if candidate.complete and candidate.hard_ok]
    violating = [candidate for candidate in candidates if candidate.complete and not candidate.hard_ok]
    partial = [candidate for candidate in candidates if not candidate.complete]
    return {
        "meta": run_meta(machine, profile, seed=seed, source_hash=source_hash),
        "profile": profile.name,
        "summary": {
            "candidates": len(candidates),
            "complete_passing": len(passing),
            "complete_violating": len(violating),
            "partial": len(partial),
            "hard_ok": bool(passing),
        },
        "fold_results": [
            {
                "status": result.status,
                "nodes": result.nodes,
                "elapsed_s": result.elapsed_s,
                "proof": result.proof,
                "diagnostics": result.diagnostics,
            }
            for result in fold_results
        ],
        "passing": passing,
        "violating": violating,
        "partial": partial,
        "ranked": list(candidates),
    }


def _strict_replays(
    candidates: Sequence[PlanCandidate],
    *,
    machine: Machine,
    profile: Profile,
    checker: MoveChecker,
) -> list[PlanCandidate]:
    """Recheck exactly the reported routes; never substitute move sides."""

    return [
        replay(
            candidate.start,
            candidate.moves,
            goal=candidate.goal,
            machine=machine,
            profile=profile,
            checker=checker,
            notes=(*candidate.notes, f"rechecked under {profile.name} profile"),
        )
        for candidate in candidates
    ]


def _raw_plan(
    candidate: PlanCandidate | None,
    strict_candidate: PlanCandidate | None,
    *,
    machine: Machine,
    loose: Profile,
    strict: Profile,
    seed: int,
    source_hash: str,
) -> dict[str, Any]:
    """Simulation-adapter-neutral checked-plan record."""

    if candidate is None:
        return {
            "schema": "cubot.checked-plan.v1",
            "meta": run_meta(machine, loose, seed=seed, source_hash=source_hash),
            "status": "NO_CANDIDATE",
            "start": None,
            "goal": None,
            "moves": [],
            "profile_reports": {loose.name: None, strict.name: None},
        }
    return {
        "schema": "cubot.checked-plan.v1",
        "meta": run_meta(machine, loose, seed=seed, source_hash=source_hash),
        "status": "COMPLETE" if candidate.complete else "PARTIAL",
        "machine": asdict(machine),
        "start": candidate.start,
        "goal": candidate.goal,
        "lying_face": candidate.start.lying,
        "moves": candidate.moves,
        "profile_reports": {
            loose.name: {
                "hard_ok": candidate.hard_ok,
                "aggregate": aggregate_reports(candidate.moves),
                "scores": candidate.scores,
                "violations": candidate.violations,
            },
            strict.name: (
                {
                    "hard_ok": strict_candidate.hard_ok,
                    "aggregate": aggregate_reports(strict_candidate.moves),
                    "scores": strict_candidate.scores,
                    "violations": strict_candidate.violations,
                    "moves": strict_candidate.moves,
                }
                if strict_candidate is not None
                else None
            ),
        },
    }


def run_pipeline(
    target: str | PixelTarget,
    out_dir: str | Path,
    *,
    machine: Machine | None = None,
    profile: str | Profile = "easy",
    strict_profile: str | Profile = "strict",
    seed: int = 0,
    k: int = 5,
    beam_width: int = 1200,
    family: Family | str | Path | None = None,
    proposals: str | Path | None = None,
    match_results: Sequence[MatchResult] | None = None,
    checker: MoveChecker = check_move,
    time_budget_s: float | None = None,
    node_budget: int | None = None,
    detour_budget: int | None = None,
    max_candidates: int = 8,
    include_heart_certificate: bool = True,
    library_root: str | Path | None = None,
) -> PipelineRun:
    """Run target generation, matching, folding, checking, and persistence.

    ``time_budget_s`` is a total fold-search budget for this icon.  Mechanics
    replay and rendering are deterministic finalization steps and therefore do
    not consume search budget.  ``match_results`` and ``checker`` are explicit
    dependency-injection seams used by small tests and offline experiments.
    """

    if k < 1 or beam_width < 1 or max_candidates < 1:
        raise ValueError("k, beam_width, and max_candidates must be positive")
    machine = machine or load_machine()
    loose = load_profile(profile) if isinstance(profile, str) else profile
    strict = load_profile(strict_profile) if isinstance(strict_profile, str) else strict_profile
    pixel_target = get_icon(target) if isinstance(target, str) else target
    source_hash = _target_hash(pixel_target)

    family_value: Family | None
    if isinstance(family, (str, Path)):
        family_value = load_family(family)
    else:
        family_value = family
    if match_results is None:
        current_matches: list[MatchResult] = []
        try:
            demo = get_demo(pixel_target.concept)
        except KeyError:
            demo = None
        if demo is not None and demo.target.rows == pixel_target.rows:
            demo_pose = Pose(demo.states, machine.roll, base=demo.base)
            demo_cells = tuple(pose_cells(demo_pose))
            demo_distance, demo_transform = recognition_distance(
                demo_cells, pixel_target
            )
            current_matches.append(
                MatchResult(
                    demo_pose,
                    demo_cells,
                    demo_distance,
                    "demo-certified",
                    demo_transform,
                )
            )
        if len(current_matches) < k:
            current_matches.extend(
                match(
                    pixel_target,
                    machine.roll,
                    k=k,
                    family=family_value,
                    beam_width=beam_width,
                    seed=seed,
                )
            )
        if proposals is not None:
            current_matches.extend(
                proposal_matches(
                    pixel_target,
                    machine.roll,
                    path=proposals,
                    k=k,
                )
            )
        unique_matches: dict[frozenset[tuple[int, int, int]], MatchResult] = {}
        for result in sorted(current_matches, key=lambda item: item.distance):
            unique_matches.setdefault(frozenset(result.cells), result)
        match_results = list(unique_matches.values())[:k]
    else:
        match_results = list(match_results)

    started = time.monotonic()
    folds: list[FoldResult] = []
    candidates: list[PlanCandidate] = []
    if pixel_target.concept == "heart" and include_heart_certificate:
        candidates.append(
            replay_heart(machine=machine, profile=loose, checker=checker)
        )

    for index, matched in enumerate(match_results[:k]):
        remaining = None
        if time_budget_s is not None:
            remaining = time_budget_s - (time.monotonic() - started)
            if remaining <= 0:
                break
            # Leave a fair deterministic slice for every remaining proposal.
            remaining_matches = max(1, min(k, len(match_results)) - index)
            remaining /= remaining_matches
        start = Pose((0,) * machine.joints, machine.roll, base=0, lying=None)
        result = fold(
            start,
            matched.pose,
            machine=machine,
            profile=loose,
            checker=checker,
            node_budget=node_budget,
            time_budget_s=remaining,
            detour_budget=detour_budget,
            max_candidates=max_candidates,
        )
        folds.append(result)
        candidates.extend(result.candidates)
        if (
            not any(candidate.complete for candidate in result.candidates)
            and any(candidate.violations for candidate in result.candidates)
        ):
            candidates.append(
                replay_direct_goal(
                    start,
                    matched.pose,
                    machine=machine,
                    profile=loose,
                    checker=checker,
                )
            )

    ranked = _representative_ranking(candidates, max_candidates)
    strict_ranked = _strict_replays(
        ranked, machine=machine, profile=strict, checker=checker
    )
    primary = ranked[0] if ranked else None
    strict_primary = strict_ranked[0] if strict_ranked else None

    root = Path(out_dir)
    run_dir = root / pixel_target.concept
    render_dir = run_dir / "renders"
    run_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    if primary is not None:
        display_pose = primary.goal
        display_cells = tuple(pose_cells(primary.goal))
    elif match_results:
        display_cells = tuple(match_results[0].cells)
        display_pose: Pose | None = match_results[0].pose
    elif pixel_target.concept == "heart":
        certificate = load_heart_certificate()
        display_cells = tuple(pose_cells(certificate.goal))
        display_pose = certificate.goal
    else:
        display_cells = tuple(pixel_target.cells)
        display_pose = None

    # Recognition review gets an uncluttered, canonically oriented silhouette.
    # Path indices and module coloring live in a separate engineering render so
    # they cannot make a poor silhouette appear more informative than it is.
    display_transform = recognition_distance(display_cells, pixel_target)[1]
    top_path = render_silhouette(
        display_cells,
        render_dir / "top.png",
        transform=display_transform,
    )
    engineering_path = render_top(
        display_cells,
        render_dir / "engineering.png",
        numbered=True,
        transform=display_transform,
    )
    iso_path = render_iso(display_cells, render_dir / "iso.png")
    review_entries: list[tuple[str, Path]] = [(f"{pixel_target.concept} top", top_path)]
    # Distinct matched goals are more useful for recognition review than
    # several fold orders for the same geometry.
    for index, matched in enumerate(match_results[1:max_candidates], start=2):
        path = render_silhouette(
            matched.cells,
            render_dir / f"candidate-{index:02d}.png",
            transform=matched.transform,
        )
        review_entries.append((f"{pixel_target.concept} candidate {index}", path))
    contact_path = contact_sheet(
        review_entries,
        run_dir / "contact-sheet.png",
        show_labels=False,
    )

    loose_payload = _report_payload(
        loose,
        ranked,
        machine=machine,
        seed=seed,
        source_hash=source_hash,
        fold_results=folds,
    )
    strict_payload = _report_payload(
        strict,
        strict_ranked,
        machine=machine,
        seed=seed,
        source_hash=source_hash,
    )
    loose_path = run_dir / "loose-report.json"
    strict_path = run_dir / "strict-report.json"
    dump_json(loose_payload, loose_path)
    dump_json(strict_payload, strict_path)

    raw_path = run_dir / "checked-plan.json"
    dump_json(
        _raw_plan(
            primary,
            strict_primary,
            machine=machine,
            loose=loose,
            strict=strict,
            seed=seed,
            source_hash=source_hash,
        ),
        raw_path,
    )

    complete = any(candidate.complete for candidate in ranked)
    status = "checked" if complete else "planned" if ranked else "threadable" if match_results else "proposed"
    human_pick: bool | None = None
    library = None
    if library_root is not None:
        from .library import Library

        library = Library(library_root)
        try:
            previous = library.get(pixel_target.concept)
        except KeyError:
            pass
        else:
            if isinstance(previous.get("human_pick"), bool):
                human_pick = bool(previous["human_pick"])
    if human_pick and complete:
        status = "picked"
    record = ShapeRecord(
        name=pixel_target.concept,
        aliases=[],
        target=pixel_target.rows,
        cells=list(display_cells),
        pose=display_pose,
        plans=ranked,
        renders={
            "top": str(top_path),
            "engineering": str(engineering_path),
            "iso": str(iso_path),
            "contact_sheet": str(contact_path),
        },
        human_pick=human_pick,
        source=pixel_target.source,
        status=status,
        meta=run_meta(machine, loose, seed=seed, source_hash=source_hash),
        notes=[
            "recognizability requires an explicit human pick",
            "strict profile is reporting-only for loose acceptance",
        ],
    )
    record_path = run_dir / "record.json"
    dump_json(record, record_path)
    if library is not None:
        library.add(record, replace=True)

    return PipelineRun(
        name=pixel_target.concept,
        run_dir=run_dir,
        record_path=record_path,
        raw_plan_path=raw_path,
        loose_report_path=loose_path,
        strict_report_path=strict_path,
        top_path=top_path,
        iso_path=iso_path,
        contact_sheet_path=contact_path,
        record=record,
        fold_statuses=tuple(result.status.value for result in folds),
    )


__all__ = ["PipelineRun", "run_pipeline"]
