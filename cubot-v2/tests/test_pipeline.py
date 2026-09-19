import json
from pathlib import Path

from cubot.config import load_machine
from cubot.generate import get_icon
from cubot.harvest import harvest
from cubot.lattice import pose_cells
from cubot.library import Library
from cubot.match import MatchResult
from cubot.pipeline import run_pipeline
from cubot.records import CheckReport, Pose


def _passing_checker(pose, move, machine, profile):
    return CheckReport(
        hard={"fixture": (True, "test checker passes")},
        soft={"fixture": (1.0, "test checker passes")},
        measurements={"profile": profile.name},
    )


def _rejecting_checker(pose, move, machine, profile):
    return CheckReport(
        hard={"fixture": (False, "test checker blocks the route")},
        soft={"fixture": (0.0, "test checker blocks the route")},
    )


def _straight_match() -> MatchResult:
    machine = load_machine()
    pose = Pose((0,) * machine.joints, machine.roll)
    return MatchResult(
        pose=pose,
        cells=tuple(pose_cells(pose)),
        distance=1.0,
        method="fixture",
        transform="identity",
    )


def test_pipeline_writes_checked_records_and_both_profiles(tmp_path: Path) -> None:
    run = run_pipeline(
        get_icon("arrow"),
        tmp_path,
        match_results=[_straight_match()],
        checker=_passing_checker,
        include_heart_certificate=False,
        time_budget_s=0.25,
        node_budget=50,
        max_candidates=2,
    )

    for path in (
        run.record_path,
        run.raw_plan_path,
        run.loose_report_path,
        run.strict_report_path,
        run.top_path,
        run.iso_path,
        run.contact_sheet_path,
    ):
        assert path.is_file()
    assert run.record.plans[0].complete
    assert run.record.plans[0].hard_ok

    loose = json.loads(run.loose_report_path.read_text())
    strict = json.loads(run.strict_report_path.read_text())
    checked = json.loads(run.raw_plan_path.read_text())
    assert loose["profile"] == "loose"
    assert strict["profile"] == "strict"
    assert loose["summary"]["complete_passing"] >= 1
    assert checked["schema"] == "cubot.checked-plan.v1"
    assert set(checked["profile_reports"]) == {"loose", "strict"}


def test_harvest_is_seeded_and_resumes_completed_icons(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    def runner(icon, out_dir, **kwargs):
        calls.append((icon, kwargs["seed"]))
        return run_pipeline(
            icon,
            out_dir,
            seed=kwargs["seed"],
            match_results=[_straight_match()],
            checker=_passing_checker,
            include_heart_certificate=False,
            time_budget_s=0.2,
            node_budget=50,
            max_candidates=1,
        )

    first = harvest(
        tmp_path,
        icons=("arrow", "key"),
        seed=17,
        duration_s=5.0,
        pipeline_runner=runner,
        k=1,
        beam_width=2,
    )
    assert first.completed == ("arrow", "key")
    assert calls == [("arrow", 17), ("key", 18)]
    assert first.contact_sheet_path and first.contact_sheet_path.is_file()

    second = harvest(
        tmp_path,
        icons=("arrow", "key"),
        seed=17,
        duration_s=5.0,
        pipeline_runner=runner,
        k=1,
        beam_width=2,
    )
    assert second.completed == first.completed
    assert second.attempted == ()
    assert calls == [("arrow", 17), ("key", 18)]


def test_partial_only_pipeline_is_planned_not_checked(tmp_path: Path) -> None:
    machine = load_machine()
    states = [0] * machine.joints
    states[:4] = [1, 1, 1, 1]
    goal = Pose(tuple(states), machine.roll)
    matched = MatchResult(goal, tuple(pose_cells(goal)), 0.0, "fixture", "identity")
    run = run_pipeline(
        get_icon("arrow"),
        tmp_path,
        match_results=[matched],
        checker=_passing_checker,
        include_heart_certificate=False,
        time_budget_s=0.01,
        node_budget=1,
        max_candidates=2,
    )
    assert run.record.plans
    assert not any(candidate.complete for candidate in run.record.plans)
    assert run.record.status == "planned"


def test_hard_blocked_pipeline_preserves_complete_violating_fallback(tmp_path: Path) -> None:
    machine = load_machine()
    states = [0] * machine.joints
    states[:2] = [1, 1]
    goal = Pose(tuple(states), machine.roll)
    matched = MatchResult(goal, tuple(pose_cells(goal)), 0.0, "fixture", "identity")
    run = run_pipeline(
        get_icon("arrow"),
        tmp_path,
        match_results=[matched],
        checker=_rejecting_checker,
        include_heart_certificate=False,
        time_budget_s=0.1,
        node_budget=20,
        max_candidates=2,
    )
    complete = [candidate for candidate in run.record.plans if candidate.complete]
    assert complete
    assert not complete[0].hard_ok
    assert "deterministic complete kinematic fallback" in complete[0].notes
    assert set(complete[0].goal.states) <= {-1, 0, 1}


def test_pipeline_geometry_tracks_ranked_primary_and_preserves_pick(tmp_path: Path) -> None:
    machine = load_machine()
    longer_states = [0] * machine.joints
    longer_states[0] = longer_states[1] = 1
    shorter_states = [0] * machine.joints
    shorter_states[4] = 1
    longer = Pose(tuple(longer_states), machine.roll)
    shorter = Pose(tuple(shorter_states), machine.roll)
    matches = [
        MatchResult(longer, tuple(pose_cells(longer)), 0.0, "fixture", "identity"),
        MatchResult(shorter, tuple(pose_cells(shorter)), 0.1, "fixture", "identity"),
    ]
    library_root = tmp_path / "library"
    run = run_pipeline(
        get_icon("arrow"),
        tmp_path / "runs",
        match_results=matches,
        checker=_passing_checker,
        include_heart_certificate=False,
        time_budget_s=0.5,
        node_budget=50,
        max_candidates=2,
        library_root=library_root,
    )
    assert run.record.pose == run.record.plans[0].goal
    assert run.record.cells == list(pose_cells(run.record.plans[0].goal))
    Library(library_root).pick(["arrow"])
    rerun = run_pipeline(
        get_icon("arrow"),
        tmp_path / "runs",
        match_results=matches,
        checker=_passing_checker,
        include_heart_certificate=False,
        time_budget_s=0.5,
        node_budget=50,
        max_candidates=2,
        library_root=library_root,
    )
    assert rerun.record.human_pick is True
    assert rerun.record.status == "picked"


def test_harvest_does_not_count_partial_artifacts_as_completed(tmp_path: Path) -> None:
    machine = load_machine()
    states = [0] * machine.joints
    states[:4] = [1, 1, 1, 1]
    goal = Pose(tuple(states), machine.roll)
    matched = MatchResult(goal, tuple(pose_cells(goal)), 0.0, "fixture", "identity")

    def runner(icon, out_dir, **kwargs):
        return run_pipeline(
            icon,
            out_dir,
            match_results=[matched],
            checker=_passing_checker,
            include_heart_certificate=False,
            time_budget_s=0.01,
            node_budget=1,
            max_candidates=2,
        )

    result = harvest(
        tmp_path,
        icons=("arrow",),
        duration_s=2.0,
        pipeline_runner=runner,
    )
    assert result.completed == ()
    state = json.loads(result.state_path.read_text())
    assert state["attempts"]["arrow"]["status"] == "partial"
    assert state["archive"]["arrow"]
