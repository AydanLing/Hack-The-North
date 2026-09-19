"""Independent, cross-module acceptance checks for the pre-simulation build.

The closed-cube regression runs all 52 directed strict checks.  Vectorized SAT
and the sound sparse hard precheck keep it fast enough for the default suite.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

from cubot.config import load_machine, load_profile
from cubot.folder import fold, load_heart_certificate
from cubot.generate import get_icon
from cubot.geometry import advance_pose
from cubot.lattice import ORIENTS, continuous_frames, fk, pose_cells
from cubot.loads import moving_side
from cubot.match import match
from cubot.pipeline import run_pipeline
from cubot.records import CheckReport, Move, Pose, SearchStatus
from cubot.solver import solve


ROOT = Path(__file__).resolve().parents[1]
HEART_PATH = ROOT / "data" / "golden" / "heart.json"
CUBE_PATH = ROOT / "data" / "golden" / "cube.json"


def _accept(
    pose: Pose,
    move: Move,
    machine: object,
    profile: object,
) -> CheckReport:
    return CheckReport(
        hard={"integration_fixture": (True, "accepted by deterministic QA checker")},
        soft={"integration_fixture": (1.0, "accepted by deterministic QA checker")},
        measurements={"joint": move.joint, "side": move.side},
    )


def _reject(
    pose: Pose,
    move: Move,
    machine: object,
    profile: object,
) -> CheckReport:
    return CheckReport(
        hard={"integration_fixture": (False, "blocked by deterministic QA checker")}
    )


def _out_only(
    pose: Pose,
    joint: int,
    machine: object,
    profile: object,
) -> tuple[str, ...]:
    return ("out",)


def test_exact_heart_solve_and_certificate_advance_pose_replay() -> None:
    raw = json.loads(HEART_PATH.read_text())
    target = tuple(tuple(int(value) for value in cell) for cell in raw["cells"])
    solved = solve(target, raw["roll"], budget_nodes=10_000, deadline_s=2.0)

    assert solved.status is SearchStatus.FOUND
    assert solved.solution is not None
    solution = solved.solution
    replayed, replayed_frames = fk(solution.states, raw["roll"], solution.base)
    assert tuple(replayed) == solution.path
    assert tuple(replayed_frames) == solution.frames
    assert set(replayed) == set(target)

    certificate = load_heart_certificate(HEART_PATH)
    pose = certificate.start
    assert len(certificate.moves) == 16
    for move in certificate.moves:
        before = pose
        pose = advance_pose(pose, move)
        changed = [
            index
            for index, (old, new) in enumerate(zip(before.states, pose.states, strict=True))
            if old != new
        ]
        assert changed == [move.joint]
        assert pose.states[move.joint] == before.states[move.joint] + move.delta
        assert all(state in (-1, 0, 1) for state in pose.states)
    assert pose == certificate.goal
    assert len(set(pose_cells(pose))) == 27


def test_general_folder_rediscovers_a_distinct_loose_heart_within_60_seconds() -> None:
    certificate = load_heart_certificate(HEART_PATH)
    result = fold(
        certificate.start,
        certificate.goal,
        time_budget_s=60.0,
        node_budget=200_000,
        detour_budget=0,
        search_lying_faces=True,
        max_candidates=1,
    )
    passing = [
        candidate
        for candidate in result.candidates
        if candidate.complete and candidate.hard_ok
    ]
    assert result.status is SearchStatus.FOUND
    assert passing
    assert result.elapsed_s <= 60.5
    assert [
        (move.joint, move.delta, move.side) for move in passing[0].moves
    ] != [
        (move.joint, move.delta, move.side) for move in certificate.moves
    ]

def test_heart_integer_fk_matches_independent_float_fk() -> None:
    certificate = load_heart_certificate(HEART_PATH)
    cells, frames = fk(
        certificate.goal.states,
        certificate.goal.roll,
        certificate.goal.base,
    )
    angles = np.deg2rad(np.asarray(certificate.goal.states, dtype=float) * 120.0)
    centres, rotations = continuous_frames(
        angles,
        certificate.goal.roll,
        82.0,
        certificate.goal.base,
    )

    np.testing.assert_allclose(centres / 82.0, np.asarray(cells), atol=2e-13, rtol=0)
    for rotation, frame in zip(rotations, frames, strict=True):
        np.testing.assert_allclose(rotation, ORIENTS[frame], atol=2e-14, rtol=0)


def test_exact_match_result_replays_to_its_reported_cells() -> None:
    machine = load_machine()
    results = match(get_icon("heart"), machine.roll, k=1, beam_width=8, seed=19)

    assert len(results) == 1
    result = results[0]
    assert result.method == "exact"
    assert len(result.cells) == len(set(result.cells)) == machine.modules
    assert tuple(pose_cells(result.pose)) == result.cells


def test_directed_unsat_requires_unpruned_forward_closure() -> None:
    machine = load_machine()
    start = Pose((0,) * machine.joints, machine.roll, lying=0)
    goal_states = [0] * machine.joints
    goal_states[0] = 1
    goal_states[1] = 1
    goal = Pose(tuple(goal_states), machine.roll, lying=0)

    exhaustive = fold(
        start,
        goal,
        checker=_reject,
        side_selector=_out_only,  # type: ignore[arg-type]
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=0,
        search_lying_faces=False,
        exhaustive=True,
    )
    assert exhaustive.status is SearchStatus.UNSAT
    assert exhaustive.proof is not None
    assert exhaustive.proof["kind"] == "exhaustive_forward_closure"
    assert exhaustive.proof["directed"] is True
    assert exhaustive.proof["start_side"] is True

    bounded = fold(
        start,
        goal,
        checker=_reject,
        side_selector=_out_only,  # type: ignore[arg-type]
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=0,
        search_lying_faces=False,
        exhaustive=False,
    )
    assert bounded.status is SearchStatus.TIMEOUT
    assert bounded.proof is None
    assert any("not an UNSAT proof" in diagnostic for diagnostic in bounded.diagnostics)

    # FOUND describes geometric completion, while hard_ok independently says
    # whether the directed move passed acceptance checks.  A rejected edge may
    # therefore be retained as a useful complete violating candidate.
    one_move_goal = Pose((1, *(0 for _ in range(machine.joints - 1))), machine.roll, lying=0)
    violating = fold(
        start,
        one_move_goal,
        checker=_reject,
        side_selector=_out_only,  # type: ignore[arg-type]
        node_budget=100,
        time_budget_s=2.0,
        detour_budget=0,
        search_lying_faces=False,
        exhaustive=True,
    )
    assert violating.status is SearchStatus.FOUND
    assert any(candidate.complete and not candidate.hard_ok for candidate in violating.candidates)


def test_pipeline_writes_self_contained_checked_plan_json(tmp_path: Path) -> None:
    machine = load_machine()
    target = get_icon("heart")
    matched = match(target, machine.roll, k=1, beam_width=8, seed=23)
    run = run_pipeline(
        target,
        tmp_path,
        machine=machine,
        match_results=matched,
        k=1,
        checker=_accept,
        time_budget_s=2.0,
        node_budget=128,
        detour_budget=0,
        max_candidates=1,
        include_heart_certificate=False,
        seed=23,
    )

    raw = json.loads(run.raw_plan_path.read_text())
    assert raw["schema"] == "cubot.checked-plan.v1"
    assert raw["status"] == "COMPLETE"
    assert len(raw["start"]["states"]) == machine.joints
    assert len(raw["goal"]["states"]) == machine.joints
    assert len(raw["moves"]) == 16
    assert {"loose", "strict"} == set(raw["profile_reports"])
    assert raw["profile_reports"]["loose"]["hard_ok"] is True
    assert raw["profile_reports"]["strict"]["hard_ok"] is True
    assert all(
        {"joint", "delta", "side", "duration_s", "checks"} <= move.keys()
        for move in raw["moves"]
    )

    meta = raw["meta"]
    assert meta["roll"] == machine.roll
    assert meta["pitch_mm"] == machine.pitch_mm
    assert meta["profile"] == "loose"
    assert meta["seed"] == 23
    assert meta["config_hash"]
    assert meta["source_hash"]
    assert meta["git_sha"]
    assert meta["created"]


def test_production_package_has_no_simulator_or_llm_imports() -> None:
    forbidden = {"anthropic", "mujoco", "openai"}
    violations: list[str] = []
    for source in sorted((ROOT / "cubot").rglob("*.py")):
        tree = ast.parse(source.read_text(), filename=str(source))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name.split(".", 1)[0].casefold() in forbidden:
                    violations.append(f"{source.relative_to(ROOT)}:{node.lineno}: {name}")
    assert violations == []


def test_cube_fixture_is_the_complete_3_by_3_by_3_pose() -> None:
    raw = json.loads(CUBE_PATH.read_text())
    machine = load_machine()
    states = tuple(-1 if state == 2 else int(state) for state in raw["states_mod3"])
    cells = pose_cells(Pose(states, machine.roll, base=0, lying=0))

    assert len(cells) == len(set(cells)) == 27
    assert set(cells) == {
        (x, y, z)
        for x in range(-1, 2)
        for y in range(-2, 1)
        for z in range(-1, 2)
    }


def test_cube_has_zero_of_52_strict_local_moves() -> None:
    raw = json.loads(CUBE_PATH.read_text())
    machine = load_machine()
    profile = load_profile("strict")
    states = tuple(-1 if state == 2 else int(state) for state in raw["states_mod3"])
    pose = Pose(states, machine.roll, base=0, lying=0)
    passing: list[tuple[int, int, str]] = []

    # Local import keeps the mechanics boundary explicit.
    from cubot.folder import check_move

    for joint in range(machine.joints):
        for delta in (-1, 1):
            side = moving_side(
                pose,
                joint,
                machine,
                ambiguity_ratio=profile.side_ambiguity_ratio,
            ).side
            report = check_move(pose, Move(joint, delta, side), machine, profile)
            if report.hard_ok:
                passing.append((joint, delta, side))

    assert passing == []
    assert len(passing) == int(raw["expected_strict_outgoing_moves"])
