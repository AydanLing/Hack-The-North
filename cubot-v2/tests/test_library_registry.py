"""The file-backed icon library and the library-scale exploration tools.

``docs/METHOD.md`` ("at scale"): winners of a mask-first run are registered as
``data/library/<category>/<name>.txt`` files, the fold queue is driven by
``tools/explore_batch.py`` and recognizability is prefiltered by
``tools/blind_judge.py``.  These tests pin the registry contract and the
plumbing without a fold run.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from cubot.generate import ICON_NAMES, get_icon
from cubot.generate import parametric

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import blind_judge  # noqa: E402
import design_search  # noqa: E402
import explore_batch  # noqa: E402
import explore_summary  # noqa: E402

ANCHOR = ("..###...", "..#.#...", "..###...", "...##...", "...##...", "...##..#", "#..##..#", "########")


def _write_mask(path: Path, rows: tuple[str, ...], header: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(rows) + "\n")
    return path


def test_library_loader_reads_headers_and_orders_by_category(tmp_path: Path) -> None:
    _write_mask(tmp_path / "nature" / "sun.txt", ANCHOR, "// aliases: sunshine, Sunny Day\n// variant: sun-v3\n")
    _write_mask(tmp_path / "animals" / "cat.txt", ANCHOR, "// aliases:\n")
    patterns, aliases, categories = parametric.load_library(tmp_path)
    assert list(patterns) == ["cat", "sun"]
    assert patterns["sun"] == ANCHOR
    assert aliases == {"sunshine": "sun", "sunny-day": "sun"}
    assert categories == {"cat": "animals", "sun": "nature"}


def test_library_loader_rejects_alias_shared_by_two_shapes(tmp_path: Path) -> None:
    _write_mask(tmp_path / "a" / "one.txt", ANCHOR, "// aliases: hook\n")
    _write_mask(tmp_path / "a" / "two.txt", ANCHOR, "// aliases: hook\n")
    with pytest.raises(ValueError, match="hook"):
        parametric.load_library(tmp_path)


def test_library_loader_tolerates_a_missing_directory(tmp_path: Path) -> None:
    assert parametric.load_library(tmp_path / "nowhere") == ({}, {}, {})


def test_registry_order_contract_holds_with_the_library() -> None:
    assert ICON_NAMES == parametric.DEMO_NAMES + parametric.REJECTED_NAMES + parametric.EXPLORED_NAMES
    assert ICON_NAMES[len(ICON_NAMES) - len(parametric.LIBRARY_NAMES) :] == parametric.LIBRARY_NAMES
    for name in parametric.LIBRARY_NAMES:
        assert len(get_icon(name).cells) == 27, name
        assert parametric.LIBRARY_CATEGORIES[name]


def test_registered_library_shapes_have_a_concept_entry() -> None:
    concepts = blind_judge.load_aliases()
    missing = [name for name in parametric.LIBRARY_NAMES if name not in concepts]
    assert not missing, missing


def test_design_search_finds_the_anchor_from_an_annotated_ideal(tmp_path: Path) -> None:
    ideal = tmp_path / "anchor.txt"
    # The two shank-side cells of the anchor's crossbar are negotiable; the exact drawing threads.
    ideal.write_text("\n".join(("..###...", "..#.#...", "..###...", "...##...", "...##...", "...##..?", "#..##..#", "#?######")) + "\n")
    required, optional, box = design_search.read_ideal(ideal)
    assert box == (8, 8) and len(required) == 25 and len(optional) == 2
    import random

    found = list(design_search.completions(required, optional, cap=100, rng=random.Random(0)))
    assert len(found) == 1
    roll = __import__("cubot.config", fromlist=["load_machine"]).load_machine().roll
    _, status, threadings = design_search.gate((frozenset(found[0]), roll))
    assert status == "FOUND" and threadings > 0
    assert design_search.to_rows(found[0]) == ANCHOR
    # A sketch with more optional cells than needed enumerates the choices.
    ideal.write_text("\n".join(("..###..?", "..#.#...", "..###...", "...##...", "...##...", "...##..?", "#..##..#", "#?######")) + "\n")
    required, optional, _ = design_search.read_ideal(ideal)
    assert len(list(design_search.completions(required, optional, cap=100, rng=random.Random(0)))) == 3
    # The exhaustive walk finds the same drawing without gating every subset.
    drawings, nodes, capped = design_search.walk_region(required, optional, roll)
    assert not capped and nodes < 50_000
    assert [design_search.to_rows(d) for d in drawings] == [ANCHOR]
    # A region that only allows a 3x9 bar has no in-plane chain under the shipped roll.
    bar_required = {(x, y) for x in range(9) for y in range(3)}
    assert design_search.walk_region(bar_required, set(), roll)[0] == []


def test_batch_runner_skips_folded_items_and_retries_non_passing(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "icons").mkdir(parents=True)
    rows = [
        {"name": "flag", "variant": "flag-v2", "mask": "data/candidates/icons/flag-v2.txt", "threadings": 6,
         "complete": True, "hard_ok": True, "goal_is_mask": True},
        {"name": "mug", "variant": "mug-v2", "mask": "data/candidates/icons/mug-v2.txt", "threadings": 6,
         "complete": True, "hard_ok": False, "goal_is_mask": True},
        {"name": "mug", "variant": "mug-v1", "mask": "data/candidates/icons/mug-v1.txt", "threadings": 0,
         "complete": None, "hard_ok": None, "goal_is_mask": None},
    ]
    (out / "icons" / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    done = explore_batch.existing_rows(out)
    assert set(done) == {("flag", "flag-v2"), ("mug", "mug-v2"), ("mug", "mug-v1")}
    retry = explore_batch.retry_items(out, only_unpassed_concepts=False)
    assert [(i["name"], Path(i["mask"]).stem, i["category"]) for i in retry] == [("mug", "mug-v2", "icons")]
    queue = tmp_path / "queue.jsonl"
    queue.write_text(json.dumps({"name": "flag", "mask": "data/candidates/icons/flag-v2.txt"}) + "\n"
                     + json.dumps({"name": "boat", "mask": "data/candidates/icons/boat-v6.txt"}) + "\n")
    items = explore_batch.read_queue(queue)
    assert [i["category"] for i in items] == ["icons", "icons"]
    pending = [i for i in items if (i["name"], Path(i["mask"]).stem) not in done]
    assert [i["name"] for i in pending] == ["boat"]


def test_summary_prefer_overrides_the_mechanics_best_variant(tmp_path: Path) -> None:
    def row(variant: str, moves: int) -> dict:
        return {"name": "j", "variant": variant, "mask": f"x/{variant}.txt", "mask_rows": ["#"], "box": [1, 1],
                "cells": 27, "screen_ok": True, "threadings": 3, "complete": True, "hard_ok": True,
                "goal_is_mask": True, "violations": [], "moves": moves, "worst_soft": 0.4, "ends_flat": True,
                "top_png": None, "record_json": None}
    (tmp_path / "results.jsonl").write_text(json.dumps(row("j-v4", 5)) + "\n" + json.dumps(row("j-v3", 9)) + "\n")
    assert explore_summary.load_rows(tmp_path)[0]["variant"] == "j-v4"
    preferred = explore_summary.load_rows(tmp_path, {"j": "j-v3"})
    assert preferred[0]["variant"] == "j-v3" and preferred[0]["variants_tried"] == 2
    with pytest.raises(SystemExit, match="j=j-v9"):
        explore_summary.load_rows(tmp_path, {"j": "j-v9"})


def test_blind_judge_import_matches_aliases_and_builds_the_queue(tmp_path: Path) -> None:
    assert blind_judge.concept_of("rain-cloud-v12") == "rain-cloud"
    assert blind_judge.concept_of("anchor") == "anchor"
    key = [
        {"sheet": "blind-01", "tile": 1, "name": "rain-cloud", "variant": "rain-cloud-v1", "mask": "c/nature/rain-cloud-v1.txt", "png": "a.png"},
        {"sheet": "blind-01", "tile": 2, "name": "rain-cloud", "variant": "rain-cloud-v2", "mask": "c/nature/rain-cloud-v2.txt", "png": "b.png"},
        {"sheet": "blind-01", "tile": 3, "name": "cat", "variant": "cat-v1", "mask": "c/animals/cat-v1.txt", "png": "c.png"},
    ]
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"blind-01": {
        "1": {"label": "storm cloud", "confidence": 0.5, "alternatives": ["raining"]},
        "2": {"label": "rain", "confidence": 0.9},
        "3": {"label": "dog", "confidence": 0.6, "alternatives": ["fox"]},
    }}))
    aliases = {"rain-cloud": ["rain", "raining"], "cat": ["kitten"]}
    rows = blind_judge.judge_import(key, labels, aliases)
    assert [(r["variant"], r["matched"], r["matched_alternative"]) for r in rows] == [
        ("rain-cloud-v1", False, True), ("rain-cloud-v2", True, False), ("cat-v1", False, False)]
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    blind_judge.write_judgements(rows, judge_dir)
    assert (judge_dir / "report.md").read_text().startswith("1 of 2 concepts named")
    queue = tmp_path / "queue.jsonl"
    blind_judge.write_queue(judge_dir, queue, per_concept=1, include_unmatched=False)
    items = [json.loads(line) for line in queue.read_text().splitlines()]
    assert [(i["name"], Path(i["mask"]).stem, i["category"]) for i in items] == [("rain-cloud", "rain-cloud-v2", "nature")]
