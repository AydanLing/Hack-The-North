from pathlib import Path

from PIL import Image
import numpy as np
import pytest

from cubot.library import Library
from cubot.viz import BACKGROUND, SILHOUETTE, contact_sheet, render_iso, render_silhouette, render_top


def test_renders_and_contact_sheet(tmp_path: Path) -> None:
    cells = [(index, 0, 0) for index in range(4)]
    top = render_top(cells, tmp_path / "top.png")
    iso = render_iso(cells, tmp_path / "iso.png")
    sheet = contact_sheet([("top", top), ("iso", iso)], tmp_path / "sheet.png", columns=2)
    assert Image.open(sheet).size[0] == 640


def test_top_render_uses_the_shape_plane_not_fixed_xy(tmp_path: Path) -> None:
    cells = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (1, 0, 2)]
    image = Image.open(render_top(cells, tmp_path / "xz-top.png", cell_px=20, margin=5))
    assert image.width > 20
    assert image.height > 20


def test_silhouette_render_has_no_per_module_visual_clutter(tmp_path: Path) -> None:
    cells = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 2, 0)]
    image = Image.open(render_silhouette(cells, tmp_path / "silhouette.png", cell_px=20, margin=5))
    assert {tuple(color) for color in np.asarray(image).reshape(-1, 3)} == {BACKGROUND, SILHOUETTE}
    with pytest.raises(ValueError, match="per-cell numbers"):
        render_top(cells, tmp_path / "invalid.png", style="silhouette", numbered=True)


def test_silhouette_can_use_matcher_orientation(tmp_path: Path) -> None:
    cells = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0)]
    original = Image.open(render_silhouette(cells, tmp_path / "original.png", cell_px=20, margin=5))
    rotated = Image.open(
        render_silhouette(cells, tmp_path / "rotated.png", cell_px=20, margin=5, transform="rot90")
    )
    assert original.size == tuple(reversed(rotated.size))


def test_contact_sheet_supports_blind_number_only_review(tmp_path: Path) -> None:
    cells = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
    rendered = render_silhouette(cells, tmp_path / "candidate.png")
    sheet = contact_sheet(
        [("do-not-reveal-concept", rendered)],
        tmp_path / "blind-sheet.png",
        show_labels=False,
    )
    assert Image.open(sheet).size == (1280, 360)


def test_library_alias_and_status_rules(tmp_path: Path) -> None:
    library = Library(tmp_path)
    base = {
        "name": "heart",
        "aliases": ["love"],
        "status": "proposed",
        "human_pick": None,
    }
    library.add(base)
    assert library.get("LOVE")["name"] == "heart"
    with pytest.raises(ValueError):
        library.set_status("heart", "checked")
    library.set_status("heart", "threadable")
    with pytest.raises(ValueError):
        library.add({"name": "romance", "aliases": ["love"], "status": "proposed"})
