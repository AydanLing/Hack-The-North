from __future__ import annotations

from cubot.records import SearchStatus
from cubot.shapes import (
    articulation_components,
    canonical_planar,
    cells_to_runs,
    components,
    hamiltonian_path,
    parse_ascii,
    runs_to_cells,
    screen,
    to_ascii,
)


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

# Unlike SNEAKY, this counterexample also satisfies the endpoint-colour
# theorem.  Every cheap screen passes, but no Hamiltonian path exists.
FULL_SEARCH_COUNTEREXAMPLE = [
    (-1, 0, -1),
    (0, -1, -1),
    (0, -1, 0),
    (0, 0, -1),
    (0, 0, 0),
    (0, 1, -1),
    (0, 1, 0),
    (1, 0, 0),
]


def test_ascii_runs_and_planar_canonicalization() -> None:
    drawing = [".##", "###"]
    cells = parse_ascii(drawing)
    assert to_ascii(cells) == ".##\n###"

    ordered = runs_to_cells("E1 N2 W1 D1")
    assert cells_to_runs(ordered) == "E1 N2 W1 D1"

    shifted_mirrored = [(-x + 11, y - 7, z) for x, y, z in cells]
    assert canonical_planar(cells) == canonical_planar(shifted_mirrored)


def test_screen_reports_duplicate_count_connectivity_and_degree_reasons() -> None:
    duplicate = screen([(0, 0, 0), (0, 0, 0)], 1)
    assert duplicate.stage == "duplicates"
    assert "duplicate" in duplicate.reason

    wrong_count = screen([(0, 0, 0)], 2)
    assert wrong_count.stage == "count"
    assert "need exactly 2" in wrong_count.reason

    disconnected = screen([(0, 0, 0), (2, 0, 0)], 2)
    assert disconnected.stage == "connected"
    assert "2 disconnected components" in disconnected.reason

    tee = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 1, 0)]
    report = screen(tee, 4)
    assert not report.checks["degree"].passed
    assert "3 degree-1 cells" in report.checks["degree"].reason


def test_parity_hand_cases_and_single_cell() -> None:
    cube = [(x, y, z) for x in range(3) for y in range(3) for z in range(3)]
    assert screen(cube, 27, include_hamiltonian=False).checks["parity"].passed

    minus_centre = [cell for cell in cube if cell != (1, 1, 1)]
    centre_report = screen(minus_centre, 26, include_hamiltonian=False)
    assert not centre_report.checks["parity"].passed
    assert centre_report.checks["parity"].details["even"] in (12, 14)

    minus_corner = [cell for cell in cube if cell != (0, 0, 0)]
    corner_report = screen(minus_corner, 26, include_hamiltonian=False)
    assert corner_report.checks["parity"].passed
    assert screen([(0, 0, 0)], 1).ok


def test_tarjan_articulation_names_three_way_split() -> None:
    tee = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 1, 0)]
    cuts = articulation_components(tee)
    assert cuts[(1, 0, 0)] == 3
    report = screen(tee, 4, include_hamiltonian=False)
    assert not report.checks["articulation"].passed
    assert "creates 3 components" in report.checks["articulation"].reason


def test_sneaky_fixture_and_true_full_search_counterexample() -> None:
    assert len(components(SNEAKY)) == 1
    sneaky = screen(SNEAKY, 9, include_hamiltonian=False)
    # The endpoint-colour theorem in the cheap screens rejects the fixture
    # before the Hamiltonian search, but it remains Hamiltonian-UNSAT.
    assert sneaky.stage == "parity"
    assert "majority parity" in sneaky.reason
    assert hamiltonian_path(SNEAKY).status is SearchStatus.UNSAT

    report = screen(FULL_SEARCH_COUNTEREXAMPLE, 8)
    assert report.stage == "hamiltonian"
    assert all(report.checks[name].passed for name in (
        "duplicates", "count", "connected", "parity", "degree", "articulation"
    ))
    assert report.hamiltonian_status is SearchStatus.UNSAT
    assert "no Hamiltonian path" in report.reason


def test_hamiltonian_timeout_is_not_unsat() -> None:
    result = hamiltonian_path(FULL_SEARCH_COUNTEREXAMPLE, budget_nodes=0)
    assert result.status is SearchStatus.TIMEOUT
    report = screen(FULL_SEARCH_COUNTEREXAMPLE, 8, budget_nodes=0)
    assert report.hamiltonian_status is SearchStatus.TIMEOUT
    assert "undecided" in report.reason

