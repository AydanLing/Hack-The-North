"""Unit tests for gentle stress gates and move-first ranking."""

from __future__ import annotations

from cubot.config import load_profile
from cubot.geometry import SweepReport, score_sweep
from cubot.loads import MomentReport, score
from cubot.records import PlanCandidate, Pose


def _pose() -> Pose:
    return Pose((0,) * 26, "12001300133101230333233210")


def _moment(*, holding_peak_nm: float) -> MomentReport:
    return MomentReport(
        joint=3,
        delta=1,
        side="out",
        moving_modules=(4, 5, 6),
        moment_in_nm=1.0,
        moment_out_nm=0.5,
        ambiguous=False,
        ambiguity_ratio=0.1,
        sample_angles_deg=(0.0, 60.0, 120.0),
        static_profile_nm=(1.0, 4.0, 2.0),
        static_peak_nm=4.0,
        peak_angle_deg=60.0,
        inertia_kgm2=0.01,
        inertial_peak_nm=0.5,
        peak_demand_nm=4.5,
        holding_peak_nm=holding_peak_nm,
        holding_joint=3,
        arc="positive",
        duration_s=2.0,
    )


def test_gentle_profile_caps() -> None:
    gentle = load_profile("gentle")
    loose = load_profile("loose")
    assert gentle.holding_hard_nm == 6.0
    assert gentle.pivot_dip_hard_mm == 25.0
    assert gentle.ground_hard_mm == 15.0
    assert gentle.balance_hard_mm == -50.0
    assert loose.holding_hard_nm >= 1e8
    assert loose.pivot_dip_hard_mm >= 1e8
    assert loose.balance_hard_mm <= -1e8


def test_holding_hard_rejects_above_cap() -> None:
    gentle = load_profile("gentle")
    assert score(_moment(holding_peak_nm=7.5), gentle).hard["holding_hard"][0] is False
    assert score(_moment(holding_peak_nm=7.5), gentle).hard_ok is False
    assert score(_moment(holding_peak_nm=5.0), gentle).hard["holding_hard"][0] is True


def test_pivot_dip_hard_rejects_above_cap() -> None:
    gentle = load_profile("gentle")
    bad = SweepReport(
        joint=3,
        delta=1,
        side="out",
        sampled_angles_deg=[0.0, 30.0, 60.0],
        max_pivot_dip_mm=30.0,
    )
    assert score_sweep(bad, gentle).hard["pivot_dip_hard"][0] is False
    assert score_sweep(bad, gentle).hard_ok is False
    ok = SweepReport(
        joint=3,
        delta=1,
        side="out",
        sampled_angles_deg=[0.0, 30.0, 60.0],
        max_pivot_dip_mm=24.0,
    )
    assert score_sweep(ok, gentle).hard["pivot_dip_hard"][0] is True


def test_rank_key_prefers_fewer_moves_among_passers() -> None:
    start = goal = _pose()
    short = PlanCandidate(
        start=start,
        goal=goal,
        moves=[None] * 12,  # type: ignore[list-item]
        complete=True,
        goal_progress=26,
        hard_ok=True,
        scores={"torque": 0.5, "holding_load": 0.4},
    )
    long = PlanCandidate(
        start=start,
        goal=goal,
        moves=[None] * 24,  # type: ignore[list-item]
        complete=True,
        goal_progress=26,
        hard_ok=True,
        scores={"torque": 0.9, "holding_load": 0.9},
    )
    assert short.rank_key < long.rank_key


def test_balance_hard_rejects_large_overhang(monkeypatch) -> None:
    from cubot import geometry

    gentle = load_profile("gentle")
    pose = _pose()
    machine = __import__("cubot.config", fromlist=["load_machine"]).load_machine()

    monkeypatch.setattr(geometry, "balance_margin", lambda *a, **k: -80.0)
    bad = geometry.score_balance(pose, machine, gentle)
    assert bad.hard["balance_hard"][0] is False

    monkeypatch.setattr(geometry, "balance_margin", lambda *a, **k: -10.0)
    ok = geometry.score_balance(pose, machine, gentle)
    assert ok.hard["balance_hard"][0] is True

    loose = load_profile("loose")
    monkeypatch.setattr(geometry, "balance_margin", lambda *a, **k: -80.0)
    assert geometry.score_balance(pose, machine, loose).hard["balance_hard"][0] is True


def test_easy_profile_caps_are_a_small_fraction_of_gearbox_stall() -> None:
    from cubot.config import load_machine

    easy = load_profile("easy")
    stall = load_machine().stall_torque_nm
    assert easy.torque_stall_nm <= 0.3 * stall
    assert easy.torque_cap_nm <= 0.15 * stall
    assert easy.holding_hard_nm <= 0.3 * stall
    assert easy.torque_cap_nm < easy.torque_stall_nm


def test_easy_hard_rejects_moves_loose_would_accept() -> None:
    from dataclasses import replace

    easy = load_profile("easy")
    loose = load_profile("loose")
    heavy = _moment(holding_peak_nm=1.0)  # static peak 4.0 N·m, demand 4.5 N·m
    assert score(heavy, loose).hard["torque_stall"][0] is True
    assert score(heavy, easy).hard["torque_stall"][0] is False
    assert score(replace(heavy, holding_peak_nm=4.0), easy).hard["holding_hard"][0] is False
    light = replace(heavy, static_peak_nm=1.0, peak_demand_nm=1.2)
    assert score(light, easy).hard_ok is True
