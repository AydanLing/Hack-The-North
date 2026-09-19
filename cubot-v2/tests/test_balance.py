import pytest

from cubot.config import load_machine, load_profile
from cubot.geometry import balance_margin, score_balance
from cubot.records import Pose


def test_straight_chain_balance_margin_is_half_a_cube() -> None:
    machine = load_machine()
    pose = Pose((0,) * 26, machine.roll)
    assert balance_margin(pose, machine) == pytest.approx(40.0, abs=1e-6)
    report = score_balance(pose, machine, load_profile("strict"))
    assert report.soft["balance"][0] == pytest.approx(1.0)
    assert report.measurements["balance_margin_mm"] == pytest.approx(40.0)
