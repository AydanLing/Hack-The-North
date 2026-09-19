from __future__ import annotations

import json
from pathlib import Path
import random

import numpy as np
import pytest

from cubot.lattice import (
    BASE_ORIENTS,
    DIRS,
    I3,
    J,
    ORIENTS,
    POST,
    RX,
    RX_POWERS,
    apply_detent,
    continuous_frames,
    escapes_a4,
    fk,
    geometry_states,
    group_closure,
    base_rot_orientation,
    lying_variants,
    parse_roll,
    reachable_orientation_count,
    self_avoiding,
    signed_representatives,
)
from cubot.records import Pose

ROOT = Path(__file__).resolve().parents[1]
HEART_PATH = ROOT / "data" / "golden" / "heart.json"


def _heart() -> dict:
    return json.loads(HEART_PATH.read_text())


def _mask(cells: list[tuple[int, int, int]]) -> list[str]:
    assert {cell[2] for cell in cells} == {0}
    min_x = min(cell[0] for cell in cells)
    max_x = max(cell[0] for cell in cells)
    min_y = min(cell[1] for cell in cells)
    max_y = max(cell[1] for cell in cells)
    occupied = set(cells)
    return [
        "".join("#" if (x, y, 0) in occupied else "." for x in range(min_x, max_x + 1))
        for y in range(max_y, min_y - 1, -1)
    ]


def test_rotation_group_and_a4_orders() -> None:
    assert len(ORIENTS) == 24
    assert len(group_closure((J, RX_POWERS[2]))) == 12
    assert len(group_closure((J,))) == 3
    assert reachable_orientation_count("02" * 13) == 12
    assert reachable_orientation_count("0" * 26) == 3
    assert reachable_orientation_count("12001300133101230333233210") == 24
    assert not escapes_a4("02" * 13)
    assert escapes_a4("0" * 25 + "1")

    keys = {tuple(int(value) for value in matrix.flat) for matrix in ORIENTS}
    assert len(keys) == 24
    for matrix in ORIENTS:
        np.testing.assert_array_equal(matrix.T @ matrix, I3)
        assert round(float(np.linalg.det(matrix))) == 1


def test_tables_have_the_spec_recurrence() -> None:
    assert DIRS.shape == (24, 3, 3)
    assert POST.shape == (24, 3, 4)
    assert not DIRS.flags.writeable
    assert not POST.flags.writeable
    index = {tuple(int(value) for value in matrix.flat): i for i, matrix in enumerate(ORIENTS)}
    for orientation, matrix in enumerate(ORIENTS):
        for state in range(3):
            after_joint = matrix @ np.linalg.matrix_power(J, state)
            np.testing.assert_array_equal(DIRS[orientation, state], after_joint[:, 0])
            for roll in range(4):
                expected = after_joint @ np.linalg.matrix_power(RX, roll)
                assert int(POST[orientation, state, roll]) == index[tuple(int(v) for v in expected.flat)]


def test_signed_state_helpers_preserve_geometry_and_bounds() -> None:
    assert geometry_states((0, -1, 1)) == [0, 2, 1]
    representatives = signed_representatives((0, 1, 2, 1), 6)
    assert representatives == [[0, 1, -1, 1]]
    assert all(geometry_states(word) == [0, 1, 2, 1] for word in representatives)
    assert apply_detent((0, -1, 1), 0, 1) == (1, -1, 1)
    with pytest.raises(ValueError, match="range"):
        apply_detent((0, -1, 1), 1, -1)
    with pytest.raises(ValueError, match="one detent"):
        apply_detent((0, 0), 0, 2)
    with pytest.raises(ValueError, match="physical positions"):
        apply_detent((2, 0), 1, 1)
    with pytest.raises(ValueError, match="physical positions"):
        apply_detent((0.0, 0), 1, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        signed_representatives((0, 1), -1)


def test_heart_golden_exact_design_frame_and_mask() -> None:
    heart = _heart()
    expected_cells = [tuple(cell) for cell in heart["cells"]]
    cells, orientations = fk(heart["signed"], heart["roll"])

    assert cells == expected_cells
    assert len(cells) == 27
    assert len(set(cells)) == 27
    assert len(orientations) == 27
    assert _mask(cells) == heart["drawing"]
    assert len(heart["drawing"]) == 6
    assert {len(row) for row in heart["drawing"]} == {7}


def test_heart_base_rot_is_not_an_orientation_index() -> None:
    heart = _heart()
    # `base_rot` is a quarter-turn count, not an orientation index.
    base_rot = heart["base_rot"]
    base = base_rot_orientation(base_rot)
    assert base_rot == 2
    assert base == BASE_ORIENTS[2] == 6
    assert base != base_rot

    world_cells, _ = fk(heart["signed"], heart["roll"], base)
    world = np.asarray(world_cells, dtype=int)
    # FK applies c_world = M c_design.  With row vectors the inverse mapping is
    # c_design = c_world M, proving the laid-down and stored paths are congruent.
    design = world @ ORIENTS[base]
    np.testing.assert_array_equal(design, np.asarray(heart["cells"], dtype=int))
    assert len({tuple(cell) for cell in world_cells}) == 27


def test_lying_variants_encode_the_transform_once() -> None:
    heart = _heart()
    pose = Pose(tuple(heart["signed"]), heart["roll"])
    variants = lying_variants(pose)
    assert [variant.lying for variant in variants] == [0, 1, 2, 3]
    assert [variant.base for variant in variants] == list(BASE_ORIENTS)
    expected = np.asarray(heart["cells"], dtype=int)
    for variant in variants:
        cells, _ = fk(variant.states, variant.roll, variant.base)
        recovered = np.asarray(cells, dtype=int) @ ORIENTS[variant.base]
        np.testing.assert_array_equal(recovered, expected)


def test_integer_fk_matches_independent_continuous_fk_randomized() -> None:
    rng = random.Random(0xC0B07)
    pitch = 82.0
    for _ in range(1_000):
        states = tuple(rng.randint(-1, 1) for _ in range(26))
        roll = tuple(rng.randrange(4) for _ in range(26))
        base = rng.randrange(24)
        cells, orientations = fk(states, roll, base)
        angles = np.deg2rad(np.asarray(states, dtype=float) * 120.0)
        centres, rotations = continuous_frames(angles, roll, pitch, base)

        np.testing.assert_allclose(centres / pitch, np.asarray(cells), atol=2e-13, rtol=0)
        for rotation, orientation in zip(rotations, orientations, strict=True):
            np.testing.assert_allclose(rotation, ORIENTS[orientation], atol=2e-14, rtol=0)

        # Module k+1's local incoming -x face points to module k.
        for index in range(1, len(cells)):
            towards_previous = np.asarray(cells[index - 1]) - np.asarray(cells[index])
            incoming_face = -(ORIENTS[orientations[index]][:, 0])
            np.testing.assert_array_equal(incoming_face, towards_previous)

        assert self_avoiding(states, roll, base) == (len(cells) == len(set(cells)))


def test_roll_and_fk_validation() -> None:
    assert parse_roll("1203", joints=4) == (1, 2, 0, 3)
    with pytest.raises(ValueError, match="digits"):
        parse_roll("12,03")
    with pytest.raises(ValueError, match="expected 3"):
        parse_roll("12", joints=3)
    with pytest.raises(ValueError, match="0..3"):
        parse_roll((0, 4))
    with pytest.raises(ValueError, match="expected 2"):
        fk((0, 1), "0")
    with pytest.raises(ValueError, match="0..23"):
        fk((0,), "0", base=24)
    with pytest.raises(ValueError, match="positive"):
        continuous_frames((0.0,), "0", 0.0)
