"""Layered (3D) mask parsing, canonical form, two-thick screen and the platform profile."""

from __future__ import annotations

import numpy as np

from cubot.config import load_machine, load_profile
from cubot.lattice import ORIENTS, pose_cells
from cubot.shapes import (
    canonical_3d,
    dense_cell_count,
    has_2x2x2_block,
    parse_ascii,
    parse_layers,
    screen,
    to_layers,
)
from cubot.solver import solve

L_CORNER = "\n".join(
    ["// L-corner: 3x5 floor + 3x4 wall"]
    + ["###", "...", "...", "...", "...", "---"] * 4
    + ["###"] * 5
)
L_CORNER_CELLS = tuple((x, y, 0) for x in range(3) for y in range(5)) + tuple(
    (x, 4, z) for x in range(3) for z in range(1, 5)
)


def test_parse_layers_matches_hand_built_cells_and_round_trips() -> None:
    cells = parse_layers(L_CORNER)
    assert len(cells) == 27
    assert set(cells) == set(L_CORNER_CELLS)
    rebuilt = "\n".join(row for index, layer in enumerate(to_layers(cells)) for row in (["---"] if index else []) + layer)
    assert set(parse_layers(rebuilt)) == set(cells)


def test_one_layer_file_equals_parse_ascii_and_blank_line_separates_layers() -> None:
    rows = ["###", "#..", "###"]
    assert set(parse_layers(rows)) == set(parse_ascii(rows))
    two = parse_layers("#..\n...\n\n###\n###")
    assert two == ((0, 1, 1), (0, 1, 0), (1, 1, 0), (2, 1, 0), (0, 0, 0), (1, 0, 0), (2, 0, 0))


def test_parse_layers_rejects_ragged_layers_and_bad_characters() -> None:
    for text in ("###\n---\n##", "#x#"):
        try:
            parse_layers(text)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {text!r}")


def test_canonical_3d_is_rotation_and_translation_invariant() -> None:
    arr = np.asarray(L_CORNER_CELLS)
    for index in (0, 5, 11, 23):
        rotated = (ORIENTS[index] @ arr.T).T + np.array([3, -2, 7])
        assert canonical_3d(tuple(map(tuple, rotated.tolist()))) == canonical_3d(L_CORNER_CELLS)
    mirrored = tuple((-x, y, z) for x, y, z in L_CORNER_CELLS)
    assert canonical_3d(mirrored, reflect=True) == canonical_3d(L_CORNER_CELLS, reflect=True)


def test_two_thick_screen_and_dense_count() -> None:
    assert not has_2x2x2_block(L_CORNER_CELLS)
    assert dense_cell_count(L_CORNER_CELLS) == 3
    block = [(x, y, z) for x in range(2) for y in range(2) for z in range(2)]
    assert has_2x2x2_block(block + [(5, 5, 5)])


def test_platform_profile_is_loose_without_the_table() -> None:
    loose = load_profile("loose")
    platform = load_profile("platform")
    assert platform.ground_hard_mm >= 1e9
    assert platform.pivot_dip_exempt_mm >= 1e9
    for field in ("sweep_step_deg", "hard_penetration_mm", "torque_stall_nm", "detour_budget", "ground_soft_mm"):
        assert getattr(platform, field) == getattr(loose, field)


def test_l_corner_threads_and_every_threading_is_the_drawing() -> None:
    cells = parse_layers(L_CORNER)
    assert screen(cells, 27).ok
    result = solve(cells, load_machine().roll, all_solutions=True, max_solutions=64)
    assert result.found and len(result.solutions) == 6
    for pose in result.poses:
        assert canonical_3d(pose_cells(pose)) == canonical_3d(cells)
