import json
from pathlib import Path
import sys
from types import SimpleNamespace

from cubot import discovery
from cubot.config import load_machine
from cubot.discovery import features_for, stage_atlas, stage_rank, stage_report, stage_thread
from cubot.folder import ends_flat_on_table, lattice_span, next_pose, replay_tracked
from cubot.generate.glyph_atlas import GLYPHS, rows_to_cells
from cubot.generate.parametric import _PATTERNS
from cubot.lattice import fk
from cubot.records import Move, Pose
from cubot.shapes import canonical_planar

_QUIET = lambda _message: None  # noqa: E731
_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from vision_judge import judge_silhouette, label_matches, normalise, parse_reply  # noqa: E402


def _atlas(tmp_path: Path, names=("h", "plus")) -> list[dict]:
    return stage_atlas([GLYPHS[n] for n in names], tmp_path, seed=3, max_per_base=25, log=_QUIET)


def test_thread_cache_resumes_without_new_solver_calls(tmp_path: Path) -> None:
    rows = _atlas(tmp_path)
    calls = {"n": 0}
    real = discovery.solve

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    first = stage_thread(rows, tmp_path, node_budget=20_000, solver=counting, log=_QUIET)
    assert calls["n"] == len({r["mask_hash"] for r in rows})
    calls["n"] = 0
    second = stage_thread(rows, tmp_path, node_budget=20_000, solver=counting, log=_QUIET)
    assert calls["n"] == 0
    assert second.keys() == first.keys()
    statuses = {entry["status"] for entry in first.values()}
    assert statuses <= {"FOUND", "UNSAT", "TIMEOUT", "SCREEN_FAIL"}


def test_found_threadings_replay_to_their_masks(tmp_path: Path) -> None:
    rows = _atlas(tmp_path, names=("h",))
    threads = stage_thread(rows, tmp_path, node_budget=20_000, log=_QUIET)
    roll = load_machine().roll
    found = [entry for entry in threads.values() if entry["status"] == "FOUND"]
    assert found, "the shipped H mask alone guarantees at least one threading"
    for entry in found:
        for pose in entry["poses"]:
            cells, _ = fk(tuple(pose["states"]), roll, base=pose["base"])
            assert len(set(cells)) == 27
            assert canonical_planar(cells) == canonical_planar(rows_to_cells(entry["rows"]))


def test_rank_selects_and_writes_slugs(tmp_path: Path) -> None:
    rows = _atlas(tmp_path, names=("h",))
    threads = stage_thread(rows, tmp_path, node_budget=20_000, log=_QUIET)
    chosen = stage_rank(rows, threads, tmp_path, per_concept=2, top_n=5, render=False, log=_QUIET)
    assert 1 <= len(chosen) <= 2
    ranked = json.loads((tmp_path / "ranked.json").read_text())
    assert all(item["slug"].startswith("h-v") for item in ranked["candidates"])
    assert ranked["concept_counts"]["h"]["FOUND"] >= 1


def test_features_of_the_shipped_h_against_itself() -> None:
    rows = tuple(_PATTERNS["h"])
    feats = features_for(rows, rows, GLYPHS["h"])
    assert feats.fidelity < 1e-6
    assert feats.nubs == 0
    assert feats.thick_fraction >= 0.5
    assert feats.hole_mismatch == 0


def test_tracked_replay_and_flat_finish() -> None:
    roll = load_machine().roll
    straight = Pose((0,) * 26, roll)
    assert ends_flat_on_table(straight)
    assert lattice_span(straight) == (26, 0, 0)
    moves = [Move(5, 1, "out"), Move(12, -1, "in")]
    expected = straight
    for move in moves:
        expected = next_pose(expected, move)
    tracked = replay_tracked(straight, moves)
    assert tracked == expected
    assert tracked.states[5] == 1 and tracked.states[12] == -1


def test_report_without_folds_is_empty_but_valid(tmp_path: Path) -> None:
    rows = _atlas(tmp_path, names=("h",))
    threads = stage_thread(rows, tmp_path, node_budget=20_000, log=_QUIET)
    stage_rank(rows, threads, tmp_path, per_concept=1, top_n=1, render=False, log=_QUIET)
    summary = stage_report(tmp_path, log=_QUIET)
    assert summary["folded"] == 0
    assert (tmp_path / "SUMMARY.md").is_file()


def test_judge_matching_and_fake_client(tmp_path: Path) -> None:
    assert normalise("A Check-Mark!") == "check mark"
    assert label_matches("checkmark", ("check", "check mark", "tick"))
    assert label_matches("the letter H", ("h",))
    assert not label_matches("unclear", ("h",))
    assert parse_reply('{"label": "Heart", "confidence": 0.9, "alternatives": ["love"]}') == ("Heart", 0.9, ["love"])
    assert parse_reply("no json here")[0] == "no json here"

    png = tmp_path / "top.png"
    from cubot.viz import render_silhouette

    render_silhouette(rows_to_cells(_PATTERNS["h"]), png)
    block = SimpleNamespace(type="text", text='{"label": "letter H", "confidence": 0.8, "alternatives": []}')
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: SimpleNamespace(content=[block])))
    judgement = judge_silhouette(client, png, aliases=("h",), cache_path=tmp_path / "cache.jsonl")
    assert judgement is not None and judgement.matched and judgement.confidence == 0.8
    calls = {"n": 0}

    def fail(**_):
        calls["n"] += 1
        raise RuntimeError("should be served from cache")

    client = SimpleNamespace(messages=SimpleNamespace(create=fail))
    again = judge_silhouette(client, png, aliases=("h",), cache_path=tmp_path / "cache.jsonl")
    assert again is not None and again.label == "letter H" and calls["n"] == 0


def test_judge_stage_is_a_no_op_without_the_sdk(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)
    from vision_judge import judge_factory

    assert judge_factory(log=_QUIET) is None
    from cubot.discovery import stage_judge

    state = {"h-v01": {"concept": "h", "top": str(tmp_path / "missing.png")}}
    assert stage_judge(state, tmp_path, judge=None, log=_QUIET) == {}
