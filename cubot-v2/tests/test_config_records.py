from dataclasses import replace

import pytest

from cubot.config import config_hash, load_machine, load_profile
from cubot.records import Move, Pose


def test_default_config() -> None:
    machine = load_machine()
    profile = load_profile()
    assert machine.modules == 27
    assert machine.pitch_mm == 82.0
    assert machine.joint_angle_deg == 120.0
    assert (machine.joint_min_position, machine.joint_max_position) == (-1, 1)
    assert profile.name == "loose"
    assert len(config_hash(machine, profile)) == 16


def test_hash_changes_with_value() -> None:
    machine = load_machine()
    profile = load_profile()
    assert config_hash(machine, profile) != config_hash(replace(machine, gap_mm=2.1), profile)


def test_pose_and_move_validation() -> None:
    machine = load_machine()
    pose = Pose((0,) * 26, machine.roll)
    assert pose.residues == (0,) * 26
    assert Pose((-1, 1) * 13, machine.roll).residues == (2, 1) * 13
    assert Move(1, -1, "in").joint == 1
    with pytest.raises(ValueError):
        Pose((0,) * 25, machine.roll)
    with pytest.raises(ValueError, match=r"-1, 0, or \+1"):
        Pose((2,) + (0,) * 25, machine.roll)
    with pytest.raises(ValueError, match=r"-1, 0, or \+1"):
        Pose((-2,) + (0,) * 25, machine.roll)
    with pytest.raises(ValueError, match=r"-1, 0, or \+1"):
        Pose((1.0,) + (0,) * 25, machine.roll)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"-1, 0, or \+1"):
        Pose((True,) + (0,) * 25, machine.roll)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Move(1, 2, "out")
    with pytest.raises(ValueError):
        Move(1, 1.0, "out")  # type: ignore[arg-type]
