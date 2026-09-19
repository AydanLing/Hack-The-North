from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from cubot.config import load_machine, load_profile
from cubot.loads import holding_loads, hump_moment, move_moment, moving_side, score
from cubot.records import Pose


def _uniform_machine():
    return replace(load_machine(), roll="0" * 26)


def test_closed_form_hump_moments_match_design_values() -> None:
    assert hump_moment(8) == pytest.approx(3.72846, abs=1e-5)
    assert hump_moment(13) == pytest.approx(9.42472, abs=1e-5)


@pytest.mark.parametrize("joint,n", [(18, 8), (13, 13)])
def test_sampled_real_com_moment_matches_straight_closed_form(joint: int, n: int) -> None:
    machine = _uniform_machine()
    pose = Pose((0,) * 26, machine.roll, base=0, lying=0)
    report = move_moment(pose, joint, 1, "out", machine, samples=121)
    assert len(report.moving_modules) == n
    assert report.static_peak_nm == pytest.approx(hump_moment(n), rel=2e-6)
    assert report.peak_angle_deg in (0.0, 120.0)


def test_moving_side_flips_across_middle_and_marks_tie() -> None:
    machine = _uniform_machine()
    pose = Pose((0,) * 26, machine.roll, base=0, lying=0)
    before = moving_side(pose, 12, machine)
    middle = moving_side(pose, 13, machine)
    after = moving_side(pose, 14, machine)
    assert before.side == "in"
    assert not before.ambiguous
    assert middle.ambiguous and middle.ratio == pytest.approx(1.0)
    assert after.side == "out"
    assert not after.ambiguous


def test_curling_the_long_side_reduces_real_peak_moment() -> None:
    machine = _uniform_machine()
    straight = Pose((0,) * 26, machine.roll, base=0, lying=0)
    curled_states = [0] * 26
    curled_states[17] = 1
    curled = Pose(tuple(curled_states), machine.roll, base=0, lying=0)
    straight_report = move_moment(straight, 13, 1, "out", machine, samples=61)
    curled_report = move_moment(curled, 13, 1, "out", machine, samples=61)
    assert curled_report.static_peak_nm < 0.65 * straight_report.static_peak_nm


def test_holding_loads_are_zero_when_every_cube_is_grounded() -> None:
    modules = 5
    centers = np.zeros((1, modules, 3), dtype=float)
    centers[0, :, 0] = np.arange(modules) * 82.0
    centers[0, :, 2] = 40.0
    axes = np.tile(np.ones(3) / np.sqrt(3.0), (1, modules - 1, 1))
    loads = holding_loads(centers, axes, 0.223)
    assert loads.shape == (1, modules - 1)
    assert np.allclose(loads, 0.0)


def test_torque_score_is_hard_only_at_stall() -> None:
    machine = _uniform_machine()
    profile = load_profile("loose")
    pose = Pose((0,) * 26, machine.roll, base=0, lying=0)
    under_stall = move_moment(pose, 13, 1, "out", machine, samples=61)
    over_stall = move_moment(pose, 12, 1, "out", machine, samples=61)
    under_checks = score(under_stall, profile)
    over_checks = score(over_stall, profile)
    assert under_checks.hard["torque_stall"][0]
    assert under_checks.soft["torque"][0] < 1.0
    assert over_stall.static_peak_nm > profile.torque_stall_nm
    assert not over_checks.hard["torque_stall"][0]
