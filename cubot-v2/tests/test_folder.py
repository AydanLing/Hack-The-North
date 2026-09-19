from __future__ import annotations

from collections import Counter
from dataclasses import replace

from cubot.config import load_machine, load_profile
from cubot.folder import (
    aggregate_reports,
    check_move,
    escape_probe,
    fold,
    goal_distance,
    load_heart_certificate,
    merge_reports,
    next_pose,
    replay,
    replay_heart,
)
from cubot.records import CheckReport, Move, Pose, SearchStatus


def _accept(
    pose: Pose,
    move: Move,
    machine: object,
    profile: object,
) -> CheckReport:
    return CheckReport(
        hard={"fixture": (True, "accepted by deterministic test checker")},
        soft={"clearance": (0.75, "fixture score")},
        measurements={"joint": move.joint},
    )


def _reject(
    pose: Pose,
    move: Move,
    machine: object,
    profile: object,
) -> CheckReport:
    return CheckReport(hard={"fixture": (False, "blocked by deterministic test checker")})


def _out_side(
    pose: Pose,
    joint: int,
    machine: object,
    profile: object,
) -> tuple[str, ...]:
    return ("out",)


def _pose(*changes: tuple[int, int], lying: int | None = 0) -> Pose:
    machine = load_machine()
    states = [0] * machine.joints
    for joint, state in changes:
        states[joint] = state
    return Pose(tuple(states), machine.roll, lying=lying)


def test_report_merge_and_plan_aggregation_keep_worst_outcomes() -> None:
    first = CheckReport(
        hard={"collision": (True, "clear")},
        soft={"torque": (0.8, "low")},
        measurements={"peak": 1.0},
    )
    second = CheckReport(
        hard={"collision": (False, "touching")},
        soft={"torque": (0.25, "high")},
        measurements={"peak": 4.0},
    )
    merged = merge_reports(first, second)
    assert not merged.hard_ok
    assert merged.soft["torque"] == (0.25, "high")
    assert merged.measurements == {"peak": 1.0, "peak_2": 4.0}

    moves = [Move(0, 1, "out", checks=first), Move(1, -1, "in", checks=second)]
    aggregate = aggregate_reports(moves)
    assert not aggregate.hard_ok
    assert aggregate.soft["torque"][0] == 0.25
    assert aggregate.measurements["hard_failures"] == 1


def test_replay_preserves_recorded_sides_with_physical_state_range() -> None:
    start = _pose()
    goal = _pose((0, -1))
    candidate = replay(
        start,
        [Move(0, -1, "in")],
        goal=goal,
        checker=_accept,
    )
    assert candidate.complete
    assert candidate.hard_ok
    assert [move.side for move in candidate.moves] == ["in"]
    assert candidate.scores == {"clearance": 0.75}


def test_next_pose_updates_world_base_only_when_in_side_moves() -> None:
    start = _pose()
    outgoing = next_pose(start, Move(4, 1, "out"))
    incoming = next_pose(start, Move(4, 1, "in"))
    assert outgoing.states[4] == incoming.states[4] == 1
    assert outgoing.base == start.base
    assert incoming.base != start.base
    assert incoming.lying == start.lying


def test_best_first_does_not_use_an_out_of_range_alternate_winding() -> None:
    start = _pose()
    goal = _pose((0, 1))

    def block_short_way(
        pose: Pose,
        move: Move,
        machine: object,
        profile: object,
    ) -> CheckReport:
        if move.joint == 0 and pose.states[0] == 0 and move.delta == 1:
            return _reject(pose, move, machine, profile)
        return _accept(pose, move, machine, profile)

    result = fold(
        start,
        goal,
        checker=block_short_way,
        side_selector=_out_side,
        node_budget=12,
        time_budget_s=2.0,
        detour_budget=0,
        max_candidates=1,
        search_lying_faces=False,
    )
    assert not any(candidate.complete and candidate.hard_ok for candidate in result.candidates)
    assert all(
        state in (-1, 0, 1)
        for candidate in result.candidates
        for move in candidate.moves
        for state in candidate.goal.states
    )


def test_final_candidate_is_rechecked_forward_without_edge_cache() -> None:
    start = _pose()
    goal = _pose((0, 1), (1, -1))
    calls: Counter[tuple[tuple[int, ...], int, int]] = Counter()

    def counting_checker(
        pose: Pose,
        move: Move,
        machine: object,
        profile: object,
    ) -> CheckReport:
        calls[(pose.states, move.joint, move.delta)] += 1
        return _accept(pose, move, machine, profile)

    result = fold(
        start,
        goal,
        checker=counting_checker,
        side_selector=_out_side,
        edge_cache={},
        node_budget=16,
        time_budget_s=2.0,
        detour_budget=0,
        max_candidates=1,
        search_lying_faces=False,
    )
    assert result.status is SearchStatus.FOUND
    plan = result.ranked()[0]
    assert "final forward recheck" in plan.notes
    for pose, move in zip(
        [start, _pose((0, 1))] if plan.moves[0].joint == 0 else [start, _pose((1, -1))],
        plan.moves,
        strict=True,
    ):
        assert calls[(pose.states, move.joint, move.delta)] >= 1
    assert sum(calls.values()) > len(plan.moves)


def test_edge_cache_key_includes_full_profile_not_only_its_name() -> None:
    start = _pose()
    goal = _pose((0, 1))
    profile = load_profile("loose")
    cache = {}
    calls = 0

    def counting_checker(
        pose: Pose,
        move: Move,
        machine: object,
        selected_profile: object,
    ) -> CheckReport:
        nonlocal calls
        calls += 1
        return _accept(pose, move, machine, selected_profile)

    for selected in (profile, profile, replace(profile, ground_hard_mm=39.0)):
        replay(
            start,
            [Move(0, 1, "out")],
            goal=goal,
            profile=selected,
            checker=counting_checker,
            edge_cache=cache,
        )
    assert calls == 2


def test_unsat_requires_exhaustive_forward_closure() -> None:
    start = _pose()
    goal = _pose((0, 1), (1, 1))
    result = fold(
        start,
        goal,
        checker=_reject,
        side_selector=_out_side,
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=100,
        search_lying_faces=False,
    )
    assert result.status is SearchStatus.UNSAT
    assert result.proof == {
        "kind": "exhaustive_forward_closure",
        "states": 1,
        "directed": True,
        "start_side": True,
    }

    bounded = fold(
        start,
        goal,
        checker=_reject,
        side_selector=_out_side,
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=0,
        search_lying_faces=False,
    )
    assert bounded.status is SearchStatus.TIMEOUT
    assert bounded.proof is None
    assert any("not an UNSAT proof" in note for note in bounded.diagnostics)

    # FOUND denotes geometric completion; the hard verdict stays separate.
    direct_goal = fold(
        start,
        _pose((0, 1)),
        checker=_reject,
        side_selector=_out_side,
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=100,
        search_lying_faces=False,
    )
    assert direct_goal.status is SearchStatus.FOUND
    assert any(candidate.complete and not candidate.hard_ok for candidate in direct_goal.candidates)


def test_goal_side_probe_is_diagnostic_not_an_unsat_claim() -> None:
    result = escape_probe(
        _pose(),
        checker=_reject,
        side_selector=_out_side,
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=100,
    )
    assert result.status is SearchStatus.TIMEOUT
    assert result.proof is not None
    assert result.proof["diagnostic_only"] is True


def test_heart_certificate_replays_exact_moves_and_assist_note() -> None:
    certificate = load_heart_certificate()
    candidate = replay_heart(checker=_accept)
    assert candidate.complete and candidate.hard_ok
    assert len(candidate.moves) == 16
    assert [(move.joint, move.delta, move.side) for move in candidate.moves] == [
        (move.joint, move.delta, move.side) for move in certificate.moves
    ]
    assert candidate.goal.residues == certificate.goal.residues
    assert any("Tether" in note for note in candidate.notes)


def test_real_heart_certificate_passes_loose_checks_and_reports_balance() -> None:
    candidate = replay_heart()
    assert candidate.complete and candidate.hard_ok
    assert candidate.violations == []
    assert "balance" in candidate.scores


def test_sparse_precheck_soundly_rejects_obvious_ground_failure() -> None:
    certificate = load_heart_certificate()
    machine = load_machine()
    profile = load_profile("loose")
    after_first = next_pose(certificate.start, certificate.moves[0])
    report = check_move(after_first, Move(4, -1, "in"), machine, profile)
    assert report.measurements["early_rejection"] is True
    assert not report.hard["ground"][0]


def test_general_search_rediscovers_heart_residue_class_with_smoke_budget() -> None:
    certificate = load_heart_certificate()
    assert goal_distance(certificate.start, certificate.goal) == 16
    result = fold(
        certificate.start,
        certificate.goal,
        checker=_accept,
        side_selector=_out_side,
        node_budget=64,
        time_budget_s=2.0,
        detour_budget=0,
        max_candidates=1,
        search_lying_faces=False,
    )
    assert result.status is SearchStatus.FOUND
    plan = result.ranked()[0]
    assert plan.complete and plan.hard_ok
    assert len(plan.moves) == 16
    assert {move.joint for move in plan.moves} == {
        index for index, state in enumerate(certificate.goal.states) if state
    }
