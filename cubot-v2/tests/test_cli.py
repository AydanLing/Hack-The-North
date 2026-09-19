import json
from pathlib import Path

from cubot.cli import build_parser, main


def test_parser_exposes_the_complete_command_surface() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if action.dest == "command"  # noqa: SLF001
    )
    assert set(subparsers.choices) == {
        "screen",
        "solve",
        "family",
        "fold",
        "check",
        "match",
        "pipeline",
        "harvest",
        "render",
        "library",
    }


def test_small_offline_cli_commands(tmp_path: Path, capsys) -> None:
    assert main(["screen", "[[0,0,0]]", "--expected-count", "1", "--skip-threadability"]) == 0
    screen_payload = json.loads(capsys.readouterr().out)
    assert screen_payload["ok"]

    family_path = tmp_path / "tiny-family.npz"
    assert main(
        [
            "family",
            "--modules",
            "5",
            "--box",
            "4x4",
            "--limit",
            "3",
            "--out",
            str(family_path),
        ]
    ) == 0
    family_payload = json.loads(capsys.readouterr().out)
    assert family_payload["count"] == 3
    assert family_path.is_file()

    render_dir = tmp_path / "render"
    assert main(["render", "heart", "--out", str(render_dir), "--numbered"]) == 0
    render_payload = json.loads(capsys.readouterr().out)
    assert Path(render_payload["top"]).is_file()
    assert Path(render_payload["iso"]).is_file()


def test_library_import_is_always_untrusted(tmp_path: Path, capsys) -> None:
    source = tmp_path / "external.json"
    source.write_text(json.dumps({"name": "external-shape", "status": "checked", "plans": [{"trusted": True}]}))
    root = tmp_path / "library"
    assert main(["library", "import", str(source), "--root", str(root)]) == 0
    capsys.readouterr()
    assert main(["library", "list", "--root", str(root)]) == 0
    entries = json.loads(capsys.readouterr().out)
    assert entries[0]["status"] == "proposed"
    assert entries[0]["plans"] == []
    assert entries[0]["human_pick"] is None
