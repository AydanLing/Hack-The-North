from cubot.config import load_machine
from cubot.generate.demo_icons import DEMO_ICON_NAMES, get_demo
from cubot.lattice import fk
from cubot.shapes import canonical_planar


def test_demo_icons_are_exact_machine_size_and_physically_signed() -> None:
    assert DEMO_ICON_NAMES == ("arrow", "lightning", "plus")
    for name in DEMO_ICON_NAMES:
        demo = get_demo(name)
        assert len(demo.target.cells) == 27
        assert len(demo.states) == 26
        assert set(demo.states) <= {-1, 0, 1}


def test_demo_certificates_replay_to_the_exact_silhouettes() -> None:
    roll = load_machine().roll
    for name in DEMO_ICON_NAMES:
        demo = get_demo(name)
        cells, _ = fk(demo.states, roll, base=demo.base)
        assert len(set(cells)) == 27
        assert canonical_planar(cells) == canonical_planar(demo.target.cells)


def test_demo_aliases_resolve_to_lightning() -> None:
    assert get_demo("lightning bolt") is get_demo("bolt")
