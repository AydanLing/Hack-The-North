"""The cable bundle leaving module 0 is a rigid keep-out on its mount face."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from cubot.config import load_machine, load_profile
from cubot.folder import _rest_report, check_move, tether_cell
from cubot.geometry import tether_rest_depth
from cubot.lattice import DIRS, pose_cells
from cubot.records import Move, Pose
from cubot.solid import tether_piece
from cubot.solver import solve


def _straight(machine):
    return Pose((0,) * machine.joints, machine.roll, base=0)


def test_machine_config_carries_a_tether():
    machine = load_machine()
    assert machine.has_tether
    assert machine.tether_length_mm > 0.0
    assert 0.0 < machine.tether_width_mm <= machine.side_mm


def test_tether_piece_sits_flush_on_the_mount_face():
    piece = tether_piece(80.0, 82.0, 40.0)
    low, high = piece.vertices.min(axis=0), piece.vertices.max(axis=0)
    assert np.allclose(high, (-40.0, 20.0, 20.0))
    assert np.allclose(low, (-122.0, -20.0, -20.0))


def test_tether_cell_is_behind_module_zero():
    machine = load_machine()
    pose = _straight(machine)
    cells = pose_cells(pose)
    mount = DIRS[pose.base, 0]
    assert tether_cell(pose) == tuple(int(cells[0][i] - mount[i]) for i in range(3))
    assert tether_cell(pose) == (-1, 0, 0)


def test_solver_rejects_threadings_that_occupy_the_tether_cell():
    machine = load_machine()
    # A 3x9 plate: every threading has its module 0 on the boundary; with the
    # keep-out only threadings whose mount face points outward survive.
    plate = [(x, y, 0) for x in range(9) for y in range(3)]
    free = solve(plate, machine.roll, all_solutions=True, max_solutions=64)
    kept = solve(plate, machine.roll, all_solutions=True, max_solutions=64, tether=True)
    target = set(plate)
    for threading in kept.solutions:
        mount = DIRS[threading.base, 0]
        keep_out = tuple(int(threading.path[0][i] - mount[i]) for i in range(3))
        assert keep_out not in target
    assert len(kept.solutions) <= len(free.solutions)


def test_rest_report_flags_a_module_in_the_tether_cell():
    machine = load_machine()
    profile = load_profile("loose")
    # (-1, -1, +1, ...) curls the chain back into the cell behind module 0.
    curled = Pose((-1, -1, 1, 0) + (0,) * 22, machine.roll, base=0)
    assert tether_cell(curled) in set(pose_cells(curled))
    assert not _rest_report(curled, machine, profile).hard["tether_cell"][0]
    clear = Pose((1, 1, -1, -1) + (0,) * 22, machine.roll, base=0)
    assert tether_cell(clear) not in set(pose_cells(clear))
    assert _rest_report(clear, machine, profile).hard["tether_cell"][0]
    bare = replace(machine, tether_length_mm=0.0)
    assert "tether_cell" not in _rest_report(_straight(machine), bare, profile).hard


def test_flat_start_keeps_the_tether_off_the_table():
    machine = load_machine()
    assert tether_rest_depth(_straight(machine), machine) == 0.0


def test_rolling_module_zero_onto_its_cable_is_a_hard_violation():
    machine = load_machine()
    profile = load_profile("loose")
    start = _straight(machine)
    verdicts = {}
    for delta in (-1, 1):
        report = check_move(start, Move(0, delta, "in"), machine, profile)
        verdicts[delta] = (report.hard["tether_ground"][0], report.hard["ground"][0])
    # One sense of the flip turns the mount face sideways, the other into the table.
    assert any(not ok for ok, _ in verdicts.values())
    bare = replace(machine, tether_length_mm=0.0)
    for delta in (-1, 1):
        report = check_move(start, Move(0, delta, "in"), bare, profile)
        assert "tether_ground" not in report.hard
        assert report.hard["ground"][0]
