"""Forward fold planning over signed CuBot joint states.

The folder is deliberately the policy layer between exact lattice kinematics
and the continuous mechanics modules.  Geometry and load analysis return
measurements; this module combines their configured hard/soft outcomes, caches
checked directed edges, and searches only through hard-valid moves.

Two details are important for callers:

* every goal has one physical state word in ``{-1, 0, +1}``; geometry residue
  ``2`` is represented physically as ``-1``;
* ``UNSAT`` is returned only after the complete forward closure has been
  explored.  A budget limit, a detour bound, or a goal-side escape probe is not
  a proof and therefore returns ``TIMEOUT`` when it finds no plan.
"""

from __future__ import annotations

import numpy as np

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
import heapq
import json
from pathlib import Path
import time
from typing import Any, Protocol

from .config import Machine, Profile, load_machine, load_profile
from .lattice import (
    apply_detent,
    base_rot_orientation,
    lying_variants,
    pose_cells,
)
from .records import (
    CheckReport,
    FoldResult,
    Move,
    PlanCandidate,
    Pose,
    SearchStatus,
    Side,
)


class MoveChecker(Protocol):
    """A replaceable directed-edge checker used by search and tests."""

    def __call__(
        self,
        pose: Pose,
        move: Move,
        machine: Machine,
        profile: Profile,
    ) -> CheckReport: ...


class SideSelector(Protocol):
    """Return planning sides in preference order for one joint."""

    def __call__(
        self,
        pose: Pose,
        joint: int,
        machine: Machine,
        profile: Profile,
    ) -> Sequence[Side]: ...


EdgeKey = tuple[tuple[int, ...], str, int, int | None, int, int, Side, str, str]
EdgeCache = dict[EdgeKey, CheckReport]


@dataclass(frozen=True, slots=True)
class HeartCertificate:
    """The checked-in heart certificate in planner-native records."""

    start: Pose
    goal: Pose
    moves: tuple[Move, ...]
    notes: tuple[str, ...] = ()


@dataclass(slots=True)
class _Node:
    pose: Pose
    parent: int | None
    move: Move | None
    depth: int
    detours: int
    scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _PendingEdge:
    parent: int
    move: Move
    after: Pose
    detours: int
    distance: int


def _copy_report(report: CheckReport) -> CheckReport:
    return CheckReport(
        hard=dict(report.hard),
        soft=dict(report.soft),
        measurements=dict(report.measurements),
    )


def merge_reports(*reports: CheckReport) -> CheckReport:
    """Combine reports for one move, keeping the most conservative outcome.

    Duplicate hard rules are ANDed, duplicate soft rules keep their minimum
    score, and duplicate measurement names are retained with a numeric suffix.
    """

    merged = CheckReport()
    for report in reports:
        for name, (passed, reason) in report.hard.items():
            if name in merged.hard:
                old_passed, old_reason = merged.hard[name]
                reasons = [text for text in (old_reason, reason) if text]
                merged.hard[name] = (old_passed and passed, "; ".join(dict.fromkeys(reasons)))
            else:
                merged.hard[name] = (bool(passed), str(reason))
        for name, (score, reason) in report.soft.items():
            score = max(0.0, min(1.0, float(score)))
            if name in merged.soft:
                old_score, old_reason = merged.soft[name]
                if score < old_score:
                    merged.soft[name] = (score, str(reason))
                else:
                    merged.soft[name] = (old_score, old_reason)
            else:
                merged.soft[name] = (score, str(reason))
        for name, value in report.measurements.items():
            key = name
            suffix = 2
            while key in merged.measurements:
                key = f"{name}_{suffix}"
                suffix += 1
            merged.measurements[key] = value
    return merged


def aggregate_reports(moves: Sequence[Move]) -> CheckReport:
    """Aggregate per-move checks into a conservative whole-plan report."""

    aggregate = CheckReport()
    for index, move in enumerate(moves):
        for name, (passed, reason) in move.checks.hard.items():
            if name not in aggregate.hard:
                aggregate.hard[name] = (bool(passed), reason)
            else:
                previous, previous_reason = aggregate.hard[name]
                if previous and not passed:
                    aggregate.hard[name] = (False, f"move {index}: {reason}")
                elif not previous:
                    aggregate.hard[name] = (False, previous_reason)
        for name, (score, reason) in move.checks.soft.items():
            previous = aggregate.soft.get(name)
            if previous is None or score < previous[0]:
                aggregate.soft[name] = (float(score), f"move {index}: {reason}")

    aggregate.measurements.update(
        {
            "moves": len(moves),
            "hard_failures": sum(
                1
                for move in moves
                for passed, _ in move.checks.hard.values()
                if not passed
            ),
            "worst_soft": min(
                (
                    score
                    for move in moves
                    for score, _ in move.checks.soft.values()
                ),
                default=1.0,
            ),
        }
    )
    return aggregate


def tether_cell(pose: Pose) -> tuple[int, int, int]:
    """The lattice cell behind module 0's free face, where its wire bundle lives."""

    from .lattice import DIRS

    cells = pose_cells(pose)
    direction = DIRS[pose.base, 0]
    return tuple(int(v) for v in (np.asarray(cells[0]) - np.asarray(direction)))


def _rest_report(after: Pose, machine: Machine | None = None, profile: Profile | None = None) -> CheckReport:
    """Lattice-level rest checks, plus the tether rules when the machine has a cable bundle.

    Without a ``machine`` the shipped one is assumed, i.e. the tether rules
    apply (``machine.has_tether`` switches them off for a bare chain).  With a
    ``profile`` the keep-out's actual table incursion at rest is measured too.
    """

    cells = pose_cells(after)
    unique = len(set(cells))
    report = CheckReport(
        hard={
            "rest_cell_overlap": (
                unique == len(cells),
                f"{len(cells) - unique} duplicate occupied lattice cells at rest",
            ),
        },
        measurements={"rest_unique_cells": unique},
    )
    if machine is not None and not machine.has_tether:
        return report
    wire = tether_cell(after)
    wire_clear = wire not in set(cells)
    lowest = min(cell[2] for cell in cells)
    wire_down = wire[2] < cells[0][2] and cells[0][2] == lowest
    report.hard["tether_cell"] = (
        wire_clear,
        f"cell {wire} outside module 0's mount face is clear at rest"
        if wire_clear
        else f"a module rests in the wire cell {wire} outside module 0's mount face",
    )
    report.hard["tether_down"] = (
        not wire_down,
        "wire bundle does not point into the resting surface"
        if not wire_down
        else "module 0 rests on the lowest layer with its wire bundle pointing down",
    )
    if machine is not None and profile is not None:
        from .geometry import tether_rest_depth

        depth = tether_rest_depth(after, machine)
        report.hard["tether_ground"] = (
            depth <= profile.ground_hard_mm + 1e-6,
            f"tether keep-out enters the table {depth:.3f} mm at rest (limit {profile.ground_hard_mm:.3f} mm)",
        )
        report.measurements["tether_rest_depth_mm"] = depth
    return report


def _early_geometry_rejection(
    pose: Pose,
    move: Move,
    machine: Machine,
    profile: Profile,
) -> CheckReport | None:
    """Sound sparse hard precheck before paying for a complete sweep.

    Most rejected fold orders put a moving side hundreds of millimetres below
    the table.  Four strategically spread samples identify those edges in a
    fraction of a full 1-degree-refined sweep.  A sparse pass proves nothing
    and falls through to :func:`geometry.sweep`; a sparse failure is already a
    real sampled hard violation and can be returned immediately.
    """

    from .geometry import _evaluate_sample, _pose_frames
    from .solid import MODULE_SOLID, TETHER_MODULE

    frames = _pose_frames(pose, machine)
    max_depth = 0.0
    max_ground = 0.0
    failed_angle: float | None = None
    samples = 0
    for angle in (120.0, 60.0, 90.0, 30.0):
        samples += 1
        collisions, ground = _evaluate_sample(
            pose,
            move,
            machine,
            angle,
            MODULE_SOLID,
            frames,
        )
        max_depth = max(max_depth, max((hit.depth_mm for hit in collisions), default=0.0))
        max_ground = max(
            max_ground,
            max((hit.depth_mm for hit in ground if not hit.pivot_piece and hit.module != TETHER_MODULE), default=0.0),
        )
        # The tether's own table contact obeys the table rule (``ground_hard_mm``),
        # like a module's: it is a rigid stand-in for a cable that really bends.
        max_ground = max(max_ground, max((hit.depth_mm for hit in ground if hit.module == TETHER_MODULE), default=0.0))
        if (
            max_depth > profile.hard_penetration_mm + 1e-6
            or max_ground > profile.ground_hard_mm + 1e-6
        ):
            failed_angle = angle
            break
    if failed_angle is None:
        return None
    collision_reason = (
        f"early sampled CAD penetration {max_depth:.3f} mm "
        f"(limit {profile.hard_penetration_mm:.3f} mm)"
    )
    ground_reason = (
        f"early sampled table incursion {max_ground:.3f} mm "
        f"(limit {profile.ground_hard_mm:.3f} mm)"
    )
    return CheckReport(
        hard={
            "cad_penetration": (
                max_depth <= profile.hard_penetration_mm + 1e-6,
                collision_reason,
            ),
            "ground": (
                max_ground <= profile.ground_hard_mm + 1e-6,
                ground_reason,
            ),
        },
        soft={
            "near_contact": (
                0.0 if max_depth > profile.hard_penetration_mm + 1e-6 else 1.0,
                collision_reason,
            ),
            "ground": (
                0.0 if max_ground > profile.ground_hard_mm + 1e-6 else 1.0,
                ground_reason,
            ),
        },
        measurements={
            "early_rejection": True,
            "early_rejection_angle_deg": failed_angle,
            "max_penetration_mm": max_depth,
            "max_ground_depth_mm": max_ground,
            "samples": samples,
        },
    )


def next_pose(pose: Pose, move: Move) -> Pose:
    """Advance a pose while accounting for motion of the root-side half.

    An ``in`` move rotates the base-side modules, so the world orientation of
    module zero changes.  Mechanics owns that frame transform; the fallback is
    kept solely for lightweight checker installations predating that helper.
    """

    try:
        from .geometry import advance_pose
    except ImportError:  # pragma: no cover - compatibility with partial installs
        advance_pose = None
    if advance_pose is not None:
        return advance_pose(pose, move)
    return replace(pose, states=apply_detent(pose.states, move.joint, move.delta))


def replay_tracked(start: Pose, moves: Iterable[Move]) -> Pose:
    """Replay ``moves`` from ``start`` and keep the world-tracked base.

    ``in`` moves rotate the base side, so the finished shape's world
    orientation is a consequence of the recorded sides rather than of the
    nominal goal.  This is the pose the simulation should expect.
    """

    pose = start
    for move in moves:
        pose = next_pose(pose, move)
    return pose


def lattice_span(pose: Pose) -> tuple[int, int, int]:
    """Extent of the rest cells along each world lattice axis."""

    cells = pose_cells(pose)
    return tuple(  # type: ignore[return-value]
        max(cell[axis] for cell in cells) - min(cell[axis] for cell in cells)
        for axis in range(3)
    )


def ends_flat_on_table(pose: Pose) -> bool:
    """True when the tracked rest pose lies in a single horizontal layer."""

    return lattice_span(pose)[2] == 0


def check_move(
    pose: Pose,
    move: Move,
    machine: Machine,
    profile: Profile,
) -> CheckReport:
    """Run rest, sampled geometry, and analytic load checks for one move."""

    try:
        apply_detent(pose.states, move.joint, move.delta)
    except ValueError as exc:
        return CheckReport(hard={"winding": (False, str(exc))})
    after = next_pose(pose, move)
    rest = _rest_report(after, machine, profile)

    # Imports stay local so lattice-only tools can import ``cubot.folder`` even
    # in minimal installations, and to keep the mechanics boundary explicit.
    from .geometry import score_balance, score_sweep, sweep
    from .loads import move_moment, score as score_moment

    early = _early_geometry_rejection(pose, move, machine, profile)
    if early is not None:
        return merge_reports(rest, early, score_balance(after, machine, profile))
    sweep_report = score_sweep(sweep(pose, move, machine, profile), profile)
    moment = move_moment(
        pose,
        move.joint,
        move.delta,
        move.side,
        machine,
        duration_s=move.duration_s,
        ambiguity_ratio=profile.side_ambiguity_ratio,
    )
    load_report = score_moment(moment, profile)
    return merge_reports(rest, sweep_report, load_report, score_balance(after, machine, profile))


def _default_side_selector(
    pose: Pose,
    joint: int,
    machine: Machine,
    profile: Profile,
) -> tuple[Side, ...]:
    from .loads import moving_side

    choice = moving_side(
        pose,
        joint,
        machine,
        ambiguity_ratio=profile.side_ambiguity_ratio,
    )
    primary: Side = choice.side
    if choice.ambiguous:
        other: Side = "out" if primary == "in" else "in"
        return primary, other
    return (primary,)


def _edge_key(pose: Pose, move: Move, machine: Machine, profile: Profile) -> EdgeKey:
    return (
        pose.states,
        pose.roll,
        pose.base,
        pose.lying,
        move.joint,
        move.delta,
        move.side,
        repr(machine),
        repr(profile),
    )


def _checked_move(
    pose: Pose,
    move: Move,
    machine: Machine,
    profile: Profile,
    checker: MoveChecker,
    cache: EdgeCache | None,
) -> Move:
    key = _edge_key(pose, move, machine, profile)
    if cache is not None and key in cache:
        report = _copy_report(cache[key])
    else:
        report = checker(pose, move, machine, profile)
        if cache is not None:
            cache[key] = _copy_report(report)
    return Move(move.joint, move.delta, move.side, move.duration_s, report)


def goal_reached(pose: Pose, goal: Pose) -> bool:
    """Whether ``pose`` has reached the unique physical goal word."""

    return pose.roll == goal.roll and pose.states == goal.states


def goal_distance(pose: Pose, goal: Pose) -> int:
    """Admissible single-detent distance to the physical goal word."""

    if pose.roll != goal.roll:
        raise ValueError("start and goal roll words differ")
    return sum(
        abs(state - target)
        for state, target in zip(pose.states, goal.states, strict=True)
    )


def goal_progress(pose: Pose, goal: Pose) -> int:
    """Number of joints already at the unique physical goal position."""

    return sum(a == b for a, b in zip(pose.states, goal.states, strict=True))


def _candidate(
    start: Pose,
    goal: Pose,
    moves: list[Move],
    final_pose: Pose,
    *,
    notes: Iterable[str] = (),
) -> PlanCandidate:
    report = aggregate_reports(moves)
    violations = [
        f"move {index} {name}: {reason}"
        for index, move in enumerate(moves)
        for name, (passed, reason) in move.checks.hard.items()
        if not passed
    ]
    return PlanCandidate(
        start=start,
        goal=goal,
        moves=moves,
        complete=goal_reached(final_pose, goal),
        goal_progress=goal_progress(final_pose, goal),
        hard_ok=report.hard_ok,
        scores={name: score for name, (score, _) in report.soft.items()},
        violations=violations,
        notes=list(notes),
    )


def replay(
    start: Pose,
    moves: Sequence[Move | tuple[int, int, Side]],
    *,
    goal: Pose | None = None,
    machine: Machine | None = None,
    profile: Profile | None = None,
    checker: MoveChecker = check_move,
    edge_cache: EdgeCache | None = None,
    stop_on_hard: bool = False,
    notes: Iterable[str] = (),
) -> PlanCandidate:
    """Replay explicit moves forward, preserving every recorded side.

    Replay never substitutes the gravity-selected side.  This is required for
    stored certificates and also makes final plan verification exact.
    """

    machine = machine or load_machine()
    profile = profile or load_profile("loose")
    if start.roll != machine.roll:
        machine = replace(machine, roll=start.roll)
    pose = start
    checked: list[Move] = []
    for raw in moves:
        move = raw if isinstance(raw, Move) else Move(*raw)
        evaluated = _checked_move(pose, move, machine, profile, checker, edge_cache)
        checked.append(evaluated)
        try:
            apply_detent(pose.states, evaluated.joint, evaluated.delta)
        except ValueError:
            break
        pose = next_pose(pose, evaluated)
        if stop_on_hard and not evaluated.checks.hard_ok:
            break
    requested_goal = goal or pose
    return _candidate(start, requested_goal, checked, pose, notes=notes)


def replay_forward(*args: Any, **kwargs: Any) -> PlanCandidate:
    """Compatibility name emphasizing that validation is from the real start."""

    return replay(*args, **kwargs)


def replay_direct_goal(
    start: Pose,
    goal: Pose,
    *,
    machine: Machine | None = None,
    profile: Profile | None = None,
    checker: MoveChecker = check_move,
    side_selector: SideSelector = _default_side_selector,
) -> PlanCandidate:
    """Build and check one complete direct kinematic route to ``goal``.

    Unlike the hard-gated folder, this diagnostic replay deliberately
    continues after failed checks.  It therefore preserves a complete
    violating plan for repair instead of returning only a one-edge-short
    partial.  It never changes a hard verdict or contributes to an UNSAT proof.
    """

    machine = machine or load_machine()
    profile = profile or load_profile("loose")
    cursor = start
    moves: list[Move] = []
    joint_order = sorted(
        range(len(cursor.states)),
        key=lambda joint: (min(joint + 1, len(cursor.states) - joint), joint),
    )
    for joint in joint_order:
        while cursor.states[joint] != goal.states[joint]:
            delta = 1 if cursor.states[joint] < goal.states[joint] else -1
            sides = tuple(side_selector(cursor, joint, machine, profile))
            if not sides:
                raise ValueError(f"side selector returned no side for joint {joint}")
            move = Move(joint, delta, sides[0], machine.move_time_s)
            moves.append(move)
            cursor = next_pose(cursor, move)
    return replay(
        start,
        moves,
        goal=goal,
        machine=machine,
        profile=profile,
        checker=checker,
        edge_cache=None,
        notes=("deterministic complete kinematic fallback",),
    )


def load_heart_certificate(path: str | Path | None = None) -> HeartCertificate:
    """Load the checked-in 16-move heart certificate."""

    source_root = Path(__file__).resolve().parent.parent / "data" / "golden"
    wheel_root = Path(__file__).resolve().parent / "_assets" / "data" / "golden"
    source = Path(path) if path is not None else (source_root if source_root.is_dir() else wheel_root) / "heart.json"
    raw = json.loads(source.read_text())
    base = base_rot_orientation(int(raw["base_rot"]))
    lying = int(raw.get("lying", raw["base_rot"]))
    start = Pose((0,) * len(raw["roll"]), raw["roll"], base=base, lying=lying)
    goal = Pose(tuple(int(value) for value in raw["signed"]), raw["roll"], base=base, lying=lying)
    moves = tuple(Move(int(joint), int(delta), side) for joint, delta, side in raw["moves"])
    return HeartCertificate(start, goal, moves, tuple(str(note) for note in raw.get("notes", [])))


def replay_heart(
    *,
    path: str | Path | None = None,
    machine: Machine | None = None,
    profile: Profile | None = None,
    checker: MoveChecker = check_move,
    edge_cache: EdgeCache | None = None,
) -> PlanCandidate:
    """Replay the heart golden with its recorded sides and assist note."""

    certificate = load_heart_certificate(path)
    return replay(
        certificate.start,
        certificate.moves,
        goal=certificate.goal,
        machine=machine,
        profile=profile,
        checker=checker,
        edge_cache=edge_cache,
        notes=certificate.notes,
    )


def _reconstruct(nodes: Sequence[_Node], index: int) -> list[Move]:
    moves: list[Move] = []
    while nodes[index].parent is not None:
        move = nodes[index].move
        assert move is not None
        moves.append(move)
        index = nodes[index].parent  # type: ignore[assignment]
    moves.reverse()
    return moves


def _merged_scores(scores: dict[str, float], report: CheckReport) -> dict[str, float]:
    merged = dict(scores)
    for name, (score, _) in report.soft.items():
        merged[name] = min(merged.get(name, 1.0), float(score))
    return merged


def _state_key(pose: Pose) -> tuple[tuple[int, ...], int, int | None]:
    return pose.states, pose.base, pose.lying


def _rank_partial(candidate: PlanCandidate) -> tuple[int, int, float, int]:
    return (
        -candidate.goal_progress,
        len(candidate.violations),
        -min(candidate.scores.values(), default=1.0),
        len(candidate.moves),
    )


def _candidate_rank(candidate: PlanCandidate) -> tuple[int, float, float, float, int, int]:
    """Requested complete/pass, complete/violation, partial ordering.

    Partial progress deliberately precedes its soft score and violations.  The
    shared record exposes the same key to external callers; keeping the local
    policy explicit also makes in-search archive pruning correct.
    """

    return candidate.rank_key


def fold(
    start: Pose,
    goal: Pose,
    *,
    machine: Machine | None = None,
    profile: Profile | None = None,
    checker: MoveChecker = check_move,
    side_selector: SideSelector = _default_side_selector,
    edge_cache: EdgeCache | None = None,
    node_budget: int | None = None,
    time_budget_s: float | None = None,
    detour_budget: int | None = None,
    search_lying_faces: bool | None = None,
    max_candidates: int = 8,
    exhaustive: bool = False,
) -> FoldResult:
    """Search forward for a hard-valid single-detent fold plan.

    Direct goal-reducing moves are ordered before bounded detours.  The
    heuristic is the exact per-joint distance to the unique physical goal
    state.  Every complete candidate is
    replayed through a fresh checker pass before it is reported.
    """

    started = time.monotonic()
    machine = machine or load_machine()
    profile = profile or load_profile("loose")
    if start.roll != goal.roll:
        raise ValueError("start and goal roll words differ")
    if start.roll != machine.roll:
        machine = replace(machine, roll=start.roll)
    node_limit = int(profile.node_budget if node_budget is None else node_budget)
    seconds = float(profile.fold_budget_s if time_budget_s is None else time_budget_s)
    detour_limit = int(profile.detour_budget if detour_budget is None else detour_budget)
    if node_limit <= 0 or seconds <= 0 or detour_limit < 0:
        raise ValueError("search budgets must be positive (detour budget may be zero)")
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")

    use_all_lying = start.lying is None if search_lying_faces is None else search_lying_faces
    starts = lying_variants(start) if use_all_lying else [start]
    active_joints = {
        index
        for index, (initial, target) in enumerate(zip(start.states, goal.states, strict=True))
        if initial != target
    }
    run_start: dict[int, int] = {}
    anchor: int | None = None
    previous_active: int | None = None
    for joint in sorted(active_joints):
        if previous_active is None or joint != previous_active + 1:
            anchor = joint
        assert anchor is not None
        run_start[joint] = anchor
        previous_active = joint
    nodes: list[_Node] = []
    # Heap payload kind 0 is a hard-valid node ready to expand; kind 1 is an
    # unchecked edge.  Nodes win equal-priority ties, so one validated direct
    # move can immediately generate the next, closer layer before sibling
    # sweeps are paid for.  This is what makes 0.6 s CAD edges practical.
    frontier: list[tuple[int, int, int, float, int, int]] = []
    pending: list[_PendingEdge] = []
    best: dict[tuple[tuple[int, ...], int, int | None], tuple[int, int, float]] = {}
    sequence = 0
    for initial in starts:
        node = _Node(initial, None, None, 0, 0)
        index = len(nodes)
        nodes.append(node)
        distance = goal_distance(initial, goal)
        heapq.heappush(frontier, (distance, 0, 0, 0.0, sequence, index))
        best[_state_key(initial)] = (0, 0, 0.0)
        sequence += 1

    passing: list[PlanCandidate] = []
    violating: list[PlanCandidate] = []
    partial_snapshots: dict[tuple[tuple[int, ...], int, int | None], PlanCandidate] = {}
    expanded = 0
    timed_out = False
    pruned_by_detour = False
    stopped_for_candidates = False

    while frontier:
        if time.monotonic() - started >= seconds:
            timed_out = True
            break
        _, _, payload_kind, _, _, payload_index = heapq.heappop(frontier)

        if payload_kind == 1:
            edge = pending[payload_index]
            parent = nodes[edge.parent]
            if expanded >= node_limit or time.monotonic() - started >= seconds:
                timed_out = True
                break
            # Another path may have reached this signed/world state while the
            # edge waited in the heap.  Skip it before invoking CAD.
            state_key = _state_key(edge.after)
            tentative = (parent.depth + 1, edge.detours)
            previous = best.get(state_key)
            if previous is not None and previous[:2] <= tentative:
                continue
            evaluated = _checked_move(
                parent.pose,
                edge.move,
                machine,
                profile,
                checker,
                edge_cache,
            )
            expanded += 1
            next_path = _reconstruct(nodes, edge.parent) + [evaluated]
            origin = starts[parent.pose.lying or 0] if use_all_lying else start
            if not evaluated.checks.hard_ok:
                failed = _candidate(
                    origin,
                    goal,
                    next_path,
                    edge.after,
                    notes=("search edge rejected by hard checks",),
                )
                violating.append(failed)
                violating.sort(key=_candidate_rank)
                del violating[max_candidates:]
                continue

            next_scores = _merged_scores(parent.scores, evaluated.checks)
            severity = 1.0 - min(next_scores.values(), default=1.0)
            cost = (parent.depth + 1, edge.detours, severity)
            previous = best.get(state_key)
            if previous is not None and previous <= cost:
                continue
            best[state_key] = cost
            child = _Node(
                edge.after,
                edge.parent,
                evaluated,
                parent.depth + 1,
                edge.detours,
                next_scores,
            )
            child_index = len(nodes)
            nodes.append(child)
            heapq.heappush(
                frontier,
                (edge.distance, edge.detours, 0, severity, sequence, child_index),
            )
            sequence += 1
            continue

        node_index = payload_index
        node = nodes[node_index]
        path = _reconstruct(nodes, node_index)

        if goal_reached(node.pose, goal):
            # Do not trust cached search-edge reports at the handoff boundary.
            verified = replay(
                starts[node.pose.lying or 0] if use_all_lying else start,
                path,
                goal=goal,
                machine=machine,
                profile=profile,
                checker=checker,
                edge_cache=None,
                notes=("final forward recheck",),
            )
            (passing if verified.hard_ok else violating).append(verified)
            # Rejected edges that happen to land in the geometric goal class
            # are retained as complete violating candidates, but must not stop
            # the search for an actually checked route.
            if len(passing) >= max_candidates:
                stopped_for_candidates = True
                break
            # A complete pose need not be expanded further for this target.
            continue

        snapshot = _candidate(
            starts[node.pose.lying or 0] if use_all_lying else start,
            goal,
            path,
            node.pose,
        )
        partial_snapshots[_state_key(node.pose)] = snapshot
        current_distance = goal_distance(node.pose, goal)

        completed_active = {
            index
            for index in active_joints
            if node.pose.states[index] == goal.states[index]
        }
        proposals: list[tuple[int, int, int, int, int, int]] = []
        for joint, state in enumerate(node.pose.states):
            for delta in (-1, 1):
                if not -1 <= state + delta <= 1:
                    continue
                trial_states = apply_detent(node.pose.states, joint, delta)
                trial = replace(node.pose, states=trial_states)
                next_distance = goal_distance(trial, goal)
                # Goal-reducing moves first, then neutral moves, then true
                # detours.  Within a layer, grow already-started runs of
                # target joints before opening another run; this support-aware
                # ordering cuts substantial fold-order backtracking while
                # remaining shape-generic and deterministic.
                kind = 0 if next_distance < current_distance else 1 if next_distance == current_distance else 2
                adjacent = sum(
                    neighbor in completed_active
                    for neighbor in (joint - 1, joint + 1)
                    if neighbor in active_joints
                )
                # Establish several separated, short-side supports before
                # growing a run.  Once three target hinges are placed, favor
                # run growth.  End distance is a generic proxy for moving-side
                # mass and makes the ordering independent of a named shape.
                adjacency_priority = (1 if adjacent else 0) if len(completed_active) < 3 else -adjacent
                target_anchor = run_start.get(joint, joint)
                end_distance = min(target_anchor + 1, len(node.pose.states) - target_anchor)
                proposals.append((kind, adjacency_priority, end_distance, target_anchor, joint, delta))
        proposals.sort()

        for kind, _, _, _, joint, delta in proposals:
            if time.monotonic() - started >= seconds:
                timed_out = True
                break
            next_detours = node.detours + (kind != 0)
            if next_detours > detour_limit and not exhaustive:
                pruned_by_detour = True
                continue
            try:
                sides = tuple(side_selector(node.pose, joint, machine, profile))
            except (ValueError, ArithmeticError):
                continue
            for side in dict.fromkeys(sides):
                if time.monotonic() - started >= seconds:
                    timed_out = True
                    break
                move = Move(joint, delta, side, machine.move_time_s)
                after = next_pose(node.pose, move)
                rest = _rest_report(after, machine)
                if not rest.hard_ok:
                    failed_move = Move(
                        move.joint,
                        move.delta,
                        move.side,
                        move.duration_s,
                        rest,
                    )
                    failed = _candidate(
                        starts[node.pose.lying or 0] if use_all_lying else start,
                        goal,
                        path + [failed_move],
                        after,
                        notes=("search edge rejected by cheap rest check",),
                    )
                    violating.append(failed)
                    violating.sort(key=_candidate_rank)
                    del violating[max_candidates:]
                    continue
                state_key = _state_key(after)
                previous = best.get(state_key)
                if previous is not None and previous[:2] <= (node.depth + 1, next_detours):
                    continue
                distance = goal_distance(after, goal)
                edge = _PendingEdge(node_index, move, after, next_detours, distance)
                edge_index = len(pending)
                pending.append(edge)
                severity = 1.0 - min(node.scores.values(), default=1.0)
                heapq.heappush(
                    frontier,
                    (distance, next_detours, 1, severity, sequence, edge_index),
                )
                sequence += 1
            if timed_out:
                break
        if timed_out:
            break

    partial = sorted(partial_snapshots.values(), key=_rank_partial)[:max_candidates]
    candidates = sorted([*passing, *violating, *partial], key=_candidate_rank)[:max_candidates]
    # FOUND is geometric completion by contract.  Whether the complete route
    # passes the selected profile remains explicit on each candidate.
    has_complete = any(candidate.complete for candidate in candidates)
    closure_complete = not frontier and not timed_out and not pruned_by_detour and not stopped_for_candidates
    if has_complete:
        status = SearchStatus.FOUND
    elif closure_complete:
        status = SearchStatus.UNSAT
    else:
        status = SearchStatus.TIMEOUT

    diagnostics: list[str] = []
    if timed_out:
        diagnostics.append("node or wall-clock budget exhausted")
    if pruned_by_detour:
        diagnostics.append("detour bound pruned edges; closure is not an UNSAT proof")
    if stopped_for_candidates:
        diagnostics.append("candidate limit reached before closure")
    proof = None
    if status is SearchStatus.UNSAT:
        proof = {
            "kind": "exhaustive_forward_closure",
            "states": len(best),
            "directed": True,
            "start_side": True,
        }
    return FoldResult(status, candidates, expanded, time.monotonic() - started, proof, diagnostics)


def plan_fold(*args: Any, **kwargs: Any) -> FoldResult:
    """Readable alias for :func:`fold`."""

    return fold(*args, **kwargs)


def escape_probe(
    pose: Pose,
    target: Pose | None = None,
    **kwargs: Any,
) -> FoldResult:
    """Explore forward from ``pose`` without misusing a goal-side closure.

    With ``target`` this is an ordinary exhaustive forward reachability query.
    Without one, a closed set is returned as diagnostic proof metadata but its
    status is ``TIMEOUT``: directed outgoing closure at a goal does not prove
    that the original start cannot reach that goal.
    """

    kwargs.setdefault("exhaustive", True)
    kwargs.setdefault("search_lying_faces", False)
    if target is not None:
        return fold(pose, target, **kwargs)

    # An unreachable sentinel residue class cannot be represented directly,
    # so exhaust against the same pose while preventing the root from being
    # treated as a solution by using a private closure walk through ``fold`` is
    # needlessly subtle.  Probe each outgoing edge with a target that differs
    # at one joint, then report only diagnostic closure facts.  For the common
    # closed-pose case this remains a one-node, complete forward check.
    sentinel_states = [
        next(value for value in (-1, 0, 1) if value % 3 != state % 3)
        for state in pose.states
    ]
    sentinel = replace(pose, states=tuple(sentinel_states))
    result = fold(pose, sentinel, **kwargs)
    if result.status is SearchStatus.UNSAT:
        result.status = SearchStatus.TIMEOUT
        result.proof = {
            **(result.proof or {}),
            "kind": "goal_side_forward_closure",
            "diagnostic_only": True,
        }
        result.diagnostics.append(
            "goal-side closure is diagnostic only; predecessor reachability was not proven"
        )
    return result


__all__ = [
    "EdgeCache",
    "HeartCertificate",
    "MoveChecker",
    "SideSelector",
    "aggregate_reports",
    "check_move",
    "ends_flat_on_table",
    "escape_probe",
    "fold",
    "goal_distance",
    "goal_progress",
    "goal_reached",
    "lattice_span",
    "load_heart_certificate",
    "merge_reports",
    "next_pose",
    "plan_fold",
    "replay",
    "replay_direct_goal",
    "replay_forward",
    "replay_heart",
    "replay_tracked",
    "tether_cell",
]
