import gzip
import json

import numpy as np

from cubot.config import load_machine
from cubot.family import enumerate_flat
from cubot.generate import ICON_NAMES, get_icon
from cubot.generate.base import PixelTarget, parse_grid
from cubot.match import chamfer_distance, proposal_matches, match, recognition_score


def test_icon_registry_is_complete() -> None:
    from cubot.generate.parametric import DEMO_NAMES, EXPLORED_NAMES, REJECTED_NAMES

    assert ICON_NAMES[:14] == (
        "heart",
        "arrow",
        "lightning",
        "plus",
        "h",
        "t",
        "n",
        "house",
        "fish",
        "star",
        "music-note",
        "key",
        "question-mark",
        "smiley",
    )
    assert ICON_NAMES == DEMO_NAMES + REJECTED_NAMES + EXPLORED_NAMES
    assert all(get_icon(name).grid.dtype == np.bool_ for name in ICON_NAMES)


def test_explored_glyphs_are_exact_shipped_roll_targets() -> None:
    """Exploration winners share the demo-glyph contract: 27 cells, exact threading."""

    from cubot.generate.parametric import EXPLORED_NAMES
    from cubot.shapes import screen
    from cubot.solver import solve

    roll = load_machine().roll
    assert len(EXPLORED_NAMES) >= 20
    for name in EXPLORED_NAMES:
        target = get_icon(name)
        assert len(target.cells) == 27, name
        assert screen(target.cells, 27).ok, name
        result = solve(target.cells, roll, budget_nodes=250_000)
        assert result.found, (name, result.diagnostics)
        assert result.solution is not None
        assert set(result.solution.states) <= {-1, 0, 1}


def test_explored_glyph_aliases() -> None:
    assert get_icon("zero").concept == "0"
    assert get_icon("letter-k").concept == "k"
    assert get_icon("wave").concept == "square-wave"
    assert get_icon("barbell").concept == "dumbbell"


def test_demo_glyphs_are_exact_shipped_roll_targets() -> None:
    """Demo glyphs must not depend on similarity matching to stay legible."""

    from cubot.solver import solve

    roll = load_machine().roll
    for name in ("plus", "h", "t", "n"):
        target = get_icon(name)
        assert len(target.cells) == 27
        result = solve(target.cells, roll, budget_nodes=250_000)
        assert result.found, (name, result.diagnostics)
        assert result.solution is not None
        assert set(result.solution.states) <= {-1, 0, 1}


def test_demo_glyph_aliases() -> None:
    assert get_icon("cross").concept == "plus"
    assert get_icon("letter H").concept == "h"
    assert get_icon("letter-T").concept == "t"
    assert get_icon("letter_n").concept == "n"


def test_distance_is_zero_for_same_drawing() -> None:
    target = get_icon("heart")
    distance, _ = chamfer_distance(target.cells, target)
    assert distance < 1e-12


def test_compact_family_lookup_returns_replayable_paths() -> None:
    machine = load_machine()
    family = enumerate_flat(machine.roll, box=(8, 8), modules=27, limit=32, use_cache=False)
    results = match(get_icon("arrow"), machine.roll, family=family, k=2, beam_width=4)
    assert results
    # The demo arrow now has an exact shipped-roll solution, correctly ranked
    # ahead of explicit family entries.  Keep asserting that the compact-family
    # branch contributes a replayable result as well.
    family_results = [result for result in results if result.method == "family"]
    assert family_results
    assert all(len(result.pose.states) == 26 for result in family_results)


def test_chamfer_projects_flat_shapes_from_their_actual_plane() -> None:
    target = get_icon("heart")
    xz_cells = tuple((x, 0, y) for x, y, _ in target.cells)
    distance, _ = chamfer_distance(xz_cells, target)
    assert distance < 1e-12


def test_recognition_score_is_exact_and_explainable() -> None:
    target = get_icon("arrow")
    score = recognition_score(target.cells, target)
    assert score.distance < 1e-12
    assert score.silhouette == 0.0
    assert score.landmarks == 0.0
    assert score.topology == 0.0


def test_recognition_score_penalizes_destroyed_negative_space() -> None:
    target = PixelTarget(parse_grid(("###", "#.#", "###")), "ring", "ring")
    opened_ring = tuple(cell for cell in target.cells if cell != (1, 2, 0))
    score = recognition_score(opened_ring, target)
    assert score.topology >= 0.4
    assert score.distance > 0.05


def test_recognition_score_handles_shape_plane_and_rotation() -> None:
    target = PixelTarget(parse_grid(("###", ".#.", ".#.")), "tee", "T")
    rotated_xz = tuple((y, 0, -x) for x, y, _ in target.cells)
    score = recognition_score(rotated_xz, target)
    assert score.distance < 1e-12
    assert score.transform in {"rot90", "rot270", "mirror-rot90", "mirror-rot270"}


def test_tall_target_transform_preserves_authored_upright_orientation() -> None:
    target = get_icon("n")
    score = recognition_score(target.cells, target)
    assert score.distance < 1e-12
    # Auto-projecting by largest span swaps axes for tall drawings.  Matching
    # must return the compensating transform rather than displaying N sideways.
    assert score.transform in {"rot90", "rot270", "mirror-rot90", "mirror-rot270"}


def test_proposals_are_rebuilt_and_marked_untrusted(tmp_path) -> None:
    machine = load_machine()
    source = tmp_path / "proposals.jsonl.gz"
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": "line", "states": [0] * 26, "validated": True}) + "\n")
    results = proposal_matches(get_icon("arrow"), machine.roll, path=source, k=1)
    assert len(results) == 1
    assert results[0].method == "proposed"
    assert len(set(results[0].cells)) == 27
