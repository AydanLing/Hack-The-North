from cubot.generate.glyph_atlas import (
    GLYPHS,
    MAX_BASE_CELLS,
    MIN_BASE_CELLS,
    TARGET_CELLS,
    Stroke,
    base_masks,
    canonical_key,
    cells_to_rows,
    count_holes,
    line_cells,
    mask_hash,
    render_strokes,
    rows_to_cells,
    variants,
)
from cubot.generate.parametric import _PATTERNS
from cubot.shapes import components, screen

_SAMPLE = ("h", "t", "n", "plus", "staircase", "o", "8", "house")


def test_every_glyph_has_a_base_mask_in_the_perturbation_window() -> None:
    from cubot.generate.glyph_atlas import _connected

    for name, glyph in GLYPHS.items():
        assert any(
            MIN_BASE_CELLS <= len(points) <= MAX_BASE_CELLS and _connected(points)
            for _, points in base_masks(glyph)
        ), f"{name} never lands near 27 cells"


def test_variants_are_exact_connected_screened_and_unique() -> None:
    for name in _SAMPLE:
        seen: set[str] = set()
        for variant in variants(GLYPHS[name], seed=1, max_per_base=40):
            cells = variant.cells
            assert len(cells) == TARGET_CELLS
            assert len(components(cells)) == 1
            assert screen(cells, TARGET_CELLS, include_hamiltonian=False).ok
            assert variant.mask_hash == mask_hash(canonical_key({(x, y) for x, y, _ in cells}))
            assert variant.mask_hash not in seen, f"duplicate variant for {name}"
            seen.add(variant.mask_hash)
        assert seen, f"{name} produced no variants"


def test_variants_are_deterministic_per_seed() -> None:
    first = [v.mask_hash for v in variants(GLYPHS["c"], seed=1, max_per_base=60)]
    second = [v.mask_hash for v in variants(GLYPHS["c"], seed=1, max_per_base=60)]
    other = [v.mask_hash for v in variants(GLYPHS["c"], seed=2, max_per_base=60)]
    assert first == second
    assert first != other


def test_shipped_masks_are_regenerated() -> None:
    for name in ("h", "t", "n", "plus"):
        wanted = mask_hash(canonical_key({(x, y) for x, y, _ in rows_to_cells(_PATTERNS[name])}))
        assert any(v.mask_hash == wanted for v in variants(GLYPHS[name], seed=0, max_per_base=100)), name


def test_line_cells_are_face_connected() -> None:
    for end in ((5, 2), (2, 5), (-4, 3), (0, 6), (6, 0), (3, -3)):
        cells = line_cells((0, 0), end)
        assert cells[0] == (0, 0) and cells[-1] == end
        for a, b in zip(cells, cells[1:]):
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def test_thick_vertical_stroke_is_two_wide() -> None:
    bar = render_strokes([Stroke(((0.0, 0.0), (0.0, 1.0)))], (4, 6), "thick")
    assert bar == {(x, y) for x in (0, 1) for y in range(6)}
    thin = render_strokes([Stroke(((0.0, 0.0), (0.0, 1.0)))], (4, 6), "thin")
    assert thin == {(0, y) for y in range(6)}


def test_holes_and_row_round_trip() -> None:
    rows = ("###", "#.#", "###")
    points = {(x, y) for x, y, _ in rows_to_cells(rows)}
    assert count_holes(points) == 1
    assert cells_to_rows(rows_to_cells(rows)) == rows
    assert count_holes({(0, 0), (1, 0), (2, 0)}) == 0
