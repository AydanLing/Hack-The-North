"""Manifest plumbing between ``tools/explore_summary.py`` and ``tools/export_handoff.py``.

The mask-first exploration method (``docs/METHOD.md``) hands its winners to the
handoff exporter through a ``cubot.handoff.manifest.v1`` file.  These tests pin
the contract without needing a fold run: relative run dirs resolve against the
manifest, numbering continues after the demo seven, and duplicate names fail.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import discovery_manifest  # noqa: E402
import explore_summary  # noqa: E402
import export_handoff  # noqa: E402


def _row(name: str, variant: str, record: Path, passing: bool = True) -> dict:
    return {
        "name": name,
        "variant": variant,
        "complete": True,
        "hard_ok": passing,
        "record_json": str(record),
        "moves": 5,
        "ends_flat": True,
    }


def test_summary_manifest_round_trips_into_exporter(tmp_path: Path) -> None:
    out = tmp_path / "explore"
    rocket = out / "verify/icons/runs/rocket-v4/rocket"
    bell = out / "icons/runs/bell-v4/bell"
    for run in (rocket, bell):
        run.mkdir(parents=True)
        (run / "record.json").write_text("{}")
    rows = [
        _row("rocket", "rocket-v4", rocket / "record.json"),
        _row("bell", "bell-v4", bell / "record.json"),
        _row("z", "z-v5", out / "letters-a/runs/z-v5/z/record.json", passing=False),
    ]

    manifest_path = explore_summary.write_manifest(rows, out)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema"] == export_handoff.MANIFEST_SCHEMA
    assert [s["name"] for s in manifest["shapes"]] == ["rocket", "bell"]
    assert manifest["shapes"][0]["run"] == "verify/icons/runs/rocket-v4/rocket"

    entries = export_handoff.load_manifest(manifest_path)
    assert [e["run"] for e in entries] == [rocket.resolve(), bell.resolve()]
    assert entries[0]["variant"] == "rocket-v4"


def test_summary_manifest_only_filter(tmp_path: Path) -> None:
    out = tmp_path / "explore"
    out.mkdir()
    rows = [_row("rocket", "rocket-v4", out / "r/record.json"), _row("bell", "bell-v4", out / "b/record.json")]
    manifest = json.loads(explore_summary.write_manifest(rows, out, only={"bell"}).read_text())
    assert [s["name"] for s in manifest["shapes"]] == ["bell"]
    with pytest.raises(SystemExit, match="mug"):
        explore_summary.write_manifest(rows, out, only={"mug"})


def test_exports_number_after_demo_seven_and_reject_duplicates(tmp_path: Path) -> None:
    demo = [{"name": n, "run": tmp_path / n, "variant": None} for n in export_handoff.SHAPES]
    extra = [export_handoff.parse_shape_arg(f"rocket={tmp_path / 'rocket'}")]
    planned = export_handoff.plan_exports(demo, extra)
    assert [p["number"] for p in planned] == list(range(1, 9))
    assert planned[-1]["name"] == "rocket"

    with pytest.raises(ValueError, match="duplicate"):
        export_handoff.plan_exports(demo, [export_handoff.parse_shape_arg(f"h={tmp_path / 'h2'}")])
    with pytest.raises(ValueError, match="NAME=RUN_DIR"):
        export_handoff.parse_shape_arg("rocket")


def test_manifest_schema_is_checked(tmp_path: Path) -> None:
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"schema": "something-else", "shapes": []}))
    with pytest.raises(ValueError, match="schema"):
        export_handoff.load_manifest(bad)


def _candidate(slug: str, record: Path, complete: bool = True, loose: bool = True) -> dict:
    return {"slug": slug, "concept": slug.rsplit("-v", 1)[0], "complete": complete, "loose_hard_ok": loose,
            "record": str(record), "moves": 4, "ends_flat": False}


def test_discovery_summary_manifest_keeps_loose_passing_slugs(tmp_path: Path) -> None:
    out = tmp_path / "discovery"
    for slug in ("hook-v01", "hook-v02", "plus-v01", "x-v01"):
        (out / "runs" / slug).mkdir(parents=True)
        (out / "runs" / slug / "record.json").write_text("{}")
    summary = {"candidates": [
        _candidate("hook-v01", out / "runs/hook-v01/record.json"),
        _candidate("hook-v02", out / "runs/hook-v02/record.json"),
        _candidate("plus-v01", out / "runs/plus-v01/record.json", loose=False),
        _candidate("x-v01", out / "runs/x-v01/record.json", complete=False),
    ]}

    manifest_path = discovery_manifest.write_manifest(summary, out)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema"] == export_handoff.MANIFEST_SCHEMA
    assert [s["name"] for s in manifest["shapes"]] == ["hook-v01", "hook-v02"]
    assert manifest["shapes"][0]["run"] == "runs/hook-v01"
    assert manifest["shapes"][0]["variant"] == "hook-v01"

    entries = export_handoff.load_manifest(manifest_path)
    assert [e["run"] for e in entries] == [(out / "runs/hook-v01").resolve(), (out / "runs/hook-v02").resolve()]
    demo = [{"name": n, "run": tmp_path / n, "variant": None} for n in export_handoff.SHAPES]
    planned = export_handoff.plan_exports(demo, entries)
    assert [(p["number"], p["name"]) for p in planned[7:]] == [(8, "hook-v01"), (9, "hook-v02")]

    with pytest.raises(SystemExit, match="plus-v01"):
        discovery_manifest.write_manifest(summary, out, only={"hook-v01", "plus-v01"})
