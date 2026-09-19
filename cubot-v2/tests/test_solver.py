from __future__ import annotations

import json
from pathlib import Path
import random

import numpy as np

from cubot.family import Family, enumerate_flat
from cubot.lattice import fk
from cubot.records import SearchStatus
from cubot.shapes import neighbours
from cubot.solver import brute_force_solve, solve


ROOT = Path(__file__).resolve().parents[1]
HEART = json.loads((ROOT / "data" / "golden" / "heart.json").read_text())
SNEAKY = [
    (0, 0, 1),
    (1, 0, 0),
    (1, 0, 1),
    (1, 1, 0),
    (1, 1, 1),
    (2, 0, 0),
    (2, 0, 1),
    (2, 1, 0),
    (3, 0, 1),
]


def _random_blob(size: int, rng: random.Random) -> set[tuple[int, int, int]]:
    cells = {(0, 0, 0)}
    while len(cells) < size:
        frontier = sorted({
            candidate
            for cell in cells
            for candidate in neighbours(cell)
            if candidate not in cells
        })
        cells.add(rng.choice(frontier))
    return cells


def test_fused_solver_matches_brute_force_on_small_random_shapes() -> None:
    rng = random.Random(0xC0B07)
    found = {SearchStatus.FOUND: 0, SearchStatus.UNSAT: 0}
    for _ in range(80):
        size = rng.randint(2, 8)
        cells = _random_blob(size, rng)
        roll = "".join(str(rng.randrange(4)) for _ in range(size - 1))
        reference = brute_force_solve(cells, roll)
        pruned = solve(cells, roll, budget_nodes=1_000_000)
        assert pruned.status is reference.status, (sorted(cells), roll)
        assert pruned.status is not SearchStatus.TIMEOUT
        assert all(
            state in (-1, 0, 1)
            for solution in (*reference.solutions, *pruned.solutions)
            for state in solution.states
        )
        found[pruned.status] += 1
    assert found[SearchStatus.FOUND] > 10
    assert found[SearchStatus.UNSAT] > 10


def test_heart_threads_under_shipped_roll_and_replays_exactly() -> None:
    target = {tuple(cell) for cell in HEART["cells"]}
    result = solve(HEART["cells"], HEART["roll"], budget_nodes=2_000_000)
    assert result.status is SearchStatus.FOUND
    assert result.solution is not None
    assert len(result.poses) == 1
    cells, frames = fk(result.solution.states, HEART["roll"], result.solution.base)
    assert set(cells) == target
    assert tuple(frames) == result.solution.frames
    assert result.nodes < 2_000_000


def test_unsat_and_timeout_are_distinct() -> None:
    exhausted = solve(SNEAKY, "0" * 8, budget_nodes=1_000_000)
    assert exhausted.status is SearchStatus.UNSAT
    assert exhausted.exhaustive

    line = [(index, 0, 0) for index in range(4)]
    timed_out = solve(line, "000", budget_nodes=0)
    assert timed_out.status is SearchStatus.TIMEOUT
    assert not timed_out.exhaustive


def test_all_solution_cap_is_found_but_not_exhaustive() -> None:
    line = [(index, 0, 0) for index in range(4)]
    result = solve(
        line,
        "000",
        all_solutions=True,
        max_solutions=3,
        budget_nodes=100_000,
    )
    assert result.status is SearchStatus.FOUND
    assert len(result.solutions) == 3
    assert not result.exhaustive
    assert "cap 3" in result.diagnostics[0]


def test_small_flat_family_replays_and_npz_round_trips(tmp_path: Path) -> None:
    roll = "1200130"
    path = tmp_path / "small-family.npz"
    family = enumerate_flat(
        roll,
        box=(6, 6),
        modules=8,
        limit=40,
        cache_path=path,
    )
    assert len(family) == 40
    assert not family.complete
    assert family.states.shape == (40, 7)
    assert family.cells.shape == (40, 8, 2)
    assert path.exists()

    axes = [axis for axis in range(3) if axis != family.plane_axis]
    for states, expected in zip(family.states, family.cells, strict=True):
        cells, _ = fk(states, roll, base=family.base)
        actual = np.asarray([[cell[axes[0]], cell[axes[1]]] for cell in cells])
        np.testing.assert_array_equal(actual, expected)
        assert len({tuple(cell) for cell in cells}) == 8

    loaded = Family.load(path)
    np.testing.assert_array_equal(loaded.states, family.states)
    np.testing.assert_array_equal(loaded.cells, family.cells)
    assert loaded.roll == family.roll
    assert loaded.box == family.box
    assert len(loaded.unique_indices()) <= len(loaded)


def test_complete_tiny_family_cache_is_reused(tmp_path: Path) -> None:
    path = tmp_path / "complete-family.npz"
    built = enumerate_flat("120", box=5, modules=4, cache_path=path)
    assert built.complete
    loaded = enumerate_flat("120", box=5, modules=4, cache_path=path)
    assert loaded.complete
    np.testing.assert_array_equal(loaded.states, built.states)
    np.testing.assert_array_equal(loaded.cells, built.cells)
