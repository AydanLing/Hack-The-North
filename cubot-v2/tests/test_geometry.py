from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from cubot.config import load_machine, load_profile
from cubot.geometry import Transform, advance_pose, ground_depth, overlap_depth, score_sweep, sweep
from cubot.lattice import base_rot_orientation
from cubot.loads import move_moment, score
from cubot.records import Move, Pose
from cubot.solid import DEFAULT_SOLID_PATH, MODULE_SOLID, analytic_module_solid, load_module_solid


def test_committed_cad_solid_provenance_and_envelope() -> None:
    raw = json.loads(DEFAULT_SOLID_PATH.read_text())
    assert raw["source"]["filename"] == "CuBot_Top_Alt_V2.stl"
    assert raw["source"]["sha256"] == "10ad4469b1c6546dde9d74678ba7e170f69ac3971cb24864be26363ea2f2eb7d"
    assert raw["bbox_mm"] == [[-40.0, -40.0, -40.0], [40.0, 40.0, 40.0]]
    assert raw["r111_mm"] == pytest.approx(58.787754, abs=1e-6)
    assert MODULE_SOLID.r111_mm == pytest.approx(58.787754, abs=1e-6)
    assert np.allclose(MODULE_SOLID.joint_axis, np.ones(3) / np.sqrt(3.0))
    for piece in (MODULE_SOLID.moving, MODULE_SOLID.still, MODULE_SOLID.full):
        assert len(piece.vertices) >= 8
        assert piece.radius_mm == pytest.approx(40.0 * np.sqrt(3.0), abs=1e-5)


def test_missing_generated_data_uses_analytic_fallback(tmp_path: Path) -> None:
    fallback = load_module_solid(tmp_path / "missing.json", fallback=True)
    assert fallback.source_hash == "analytic-corner-chamfer"
    assert fallback.provenance["side_mm"] == 80.0
    with pytest.raises(FileNotFoundError):
        load_module_solid(tmp_path / "missing.json")


@pytest.mark.parametrize("factory", [lambda: MODULE_SOLID, analytic_module_solid])
def test_sat_overlap_depth_for_axis_aligned_modules(factory) -> None:
    solid = factory()
    origin = Transform.identity()
    assert overlap_depth(solid, origin, solid, Transform.identity((82.0, 0.0, 0.0))) == 0.0
    assert overlap_depth(solid, origin, solid, Transform.identity((80.0, 0.0, 0.0))) == 0.0
    assert overlap_depth(solid, origin, solid, Transform.identity((79.0, 0.0, 0.0))) == pytest.approx(1.0)
    assert overlap_depth(solid, origin, solid, Transform.identity((78.0, 0.0, 0.0))) == pytest.approx(2.0)


def test_ground_depth_is_metric_and_nonnegative() -> None:
    assert ground_depth(MODULE_SOLID, Transform.identity((0.0, 0.0, 41.0))) == 0.0
    assert ground_depth(MODULE_SOLID, Transform.identity((0.0, 0.0, 40.0))) == 0.0
    assert ground_depth(MODULE_SOLID, Transform.identity((0.0, 0.0, 39.0))) == pytest.approx(1.0)


def test_last_joint_sweep_includes_hinge_piece_and_refines_contact() -> None:
    machine = load_machine()
    pose = Pose((0,) * 26, machine.roll, base=0, lying=0)
    move = Move(25, 1, "out")
    report = sweep(pose, move, machine, load_profile("loose"))
    # 4-degree coarse sampling is refined to 1 degree around contact-bearing
    # intervals.  The rotating CAD hinge half, not the whole out-side cube,
    # creates the shallow adjacent-module contact in this fixture.
    assert report.samples > 31
    assert report.first_contact_angle_deg is not None
    assert report.max_pair == (25, 26)
    assert 0.0 < report.max_depth_mm < 1.0
    assert report.max_ground_depth_mm == 0.0
    assert report.max_pivot_dip_mm > 0.0
    checks = score_sweep(report, load_profile("loose"))
    assert checks.hard_ok
    assert checks.measurements["max_penetration_mm"] == pytest.approx(report.max_depth_mm)


def test_strict_profile_rejects_positive_cad_penetration() -> None:
    machine = load_machine()
    pose = Pose((0,) * 26, machine.roll, base=0, lying=0)
    report = sweep(pose, Move(25, 1, "out"), machine, load_profile("strict"))
    checks = score_sweep(report, load_profile("strict"))
    assert report.max_depth_mm > 0.0
    assert not checks.hard["cad_penetration"][0]


def test_known_heart_certificate_replays_under_loose_profile() -> None:
    golden = json.loads((DEFAULT_SOLID_PATH.parents[1] / "golden" / "heart.json").read_text())
    machine = load_machine()
    profile = load_profile("loose")
    pose = Pose(
        (0,) * 26,
        machine.roll,
        base=base_rot_orientation(golden["base_rot"]),
        lying=golden["lying"],
    )
    for joint, delta, side in golden["moves"]:
        move = Move(joint, delta, side)
        geometry_checks = score_sweep(sweep(pose, move, machine, profile), profile)
        load_checks = score(
            move_moment(
                pose,
                joint,
                delta,
                side,
                machine,
                duration_s=move.duration_s,
                ambiguity_ratio=profile.side_ambiguity_ratio,
            ),
            profile,
        )
        assert geometry_checks.hard_ok, geometry_checks.violations
        assert load_checks.hard_ok, load_checks.violations
        pose = advance_pose(pose, move)
    assert pose.states == tuple(golden["signed"])
