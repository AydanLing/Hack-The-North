"""Command-line interface for the offline CuBot V2 pre-simulation tools."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
import gzip
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

import numpy as np

from .config import load_machine, load_profile
from .family import Family, enumerate_flat, load_family
from .folder import fold as search_fold
from .folder import load_heart_certificate, replay, replay_heart
from .generate import DEMO_NAMES, ICON_NAMES, get_icon
from .harvest import harvest
from .lattice import fk
from .library import Library
from .match import MatchResult, match
from .pipeline import run_pipeline
from .records import Move, Pose, dump_json
from .shapes import parse_ascii, screen
from .solver import solve
from .viz import render_iso, render_top


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _emit(value: Any) -> None:
    print(json.dumps(_jsonable(value), indent=2, sort_keys=True))


def _read_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def _pose(raw: dict[str, Any], *, default_roll: str) -> Pose:
    if "pose" in raw and isinstance(raw["pose"], dict):
        raw = raw["pose"]
    return Pose(
        tuple(int(value) for value in raw["states"]),
        str(raw.get("roll", default_roll)),
        int(raw.get("base", 0)),
        None if raw.get("lying") is None else int(raw["lying"]),
    )


def _cells(source: str) -> tuple[tuple[int, int, int], ...]:
    try:
        return tuple(get_icon(source).cells)
    except KeyError:
        pass
    path = Path(source)
    if path.is_file():
        if path.suffix in {".json", ".gz"}:
            raw = _read_json(path)
            if isinstance(raw, dict):
                if "cells" in raw:
                    raw = raw["cells"]
                elif "drawing" in raw:
                    return parse_ascii(raw["drawing"])
                elif "target" in raw:
                    return parse_ascii(raw["target"])
                elif "pose" in raw or "states" in raw:
                    machine = load_machine()
                    value = _pose(raw, default_roll=machine.roll)
                    return tuple(fk(value.states, value.roll, value.base)[0])
            return tuple(tuple(int(v) for v in cell) for cell in raw)
        return parse_ascii(path.read_text())
    if source.lstrip().startswith("["):
        raw = json.loads(source)
        return tuple(tuple(int(v) for v in cell) for cell in raw)
    if "\n" in source or set(source) <= set(".# \t"):
        return parse_ascii(source)
    raise ValueError(f"unknown icon or shape source {source!r}")


def _goal_pose(source: str, *, roll: str, k: int, beam_width: int, seed: int) -> Pose:
    if source.casefold() == "heart":
        return load_heart_certificate().goal
    path = Path(source)
    if path.is_file() and path.suffix in {".json", ".gz"}:
        raw = _read_json(path)
        if isinstance(raw, dict):
            if "goal" in raw and isinstance(raw["goal"], dict):
                return _pose(raw["goal"], default_roll=roll)
            if "pose" in raw or "states" in raw:
                return _pose(raw, default_roll=roll)
    target = get_icon(source)
    results = match(target, roll, k=k, beam_width=beam_width, seed=seed)
    if not results:
        raise RuntimeError(f"no roll-compatible match found for {source!r}")
    return results[0].pose


def _box(value: str) -> int | tuple[int, int]:
    normalized = value.lower().replace("×", "x")
    if "x" not in normalized:
        return int(normalized)
    left, right = normalized.split("x", 1)
    return int(left), int(right)


def _family_matches(family: Family) -> Iterable[tuple[Pose, Sequence[tuple[int, int, int]]]]:
    axes = tuple(axis for axis in range(3) if axis != family.plane_axis)
    for states, flat_cells in zip(family.states, family.cells, strict=True):
        if len(states) != 26:
            continue
        cells: list[tuple[int, int, int]] = []
        for first, second in flat_cells:
            cell = [0, 0, 0]
            cell[axes[0]], cell[axes[1]] = int(first), int(second)
            cells.append(tuple(cell))  # type: ignore[arg-type]
        physical = tuple(-1 if int(value) == 2 else int(value) for value in states)
        yield Pose(physical, family.roll, family.base), cells


def _cmd_screen(args: argparse.Namespace) -> int:
    machine = load_machine()
    cells = _cells(args.source)
    report = screen(
        cells,
        args.expected_count,
        include_hamiltonian=not args.no_hamiltonian,
        budget_nodes=args.budget_nodes,
        deadline_s=args.deadline,
    )
    payload: dict[str, Any] = report.to_dict()
    payload["chain"] = report.chain
    if report.ok and not args.skip_threadability:
        threaded = solve(
            cells,
            args.roll or machine.roll,
            budget_nodes=args.thread_budget_nodes,
            deadline_s=args.deadline,
        )
        payload["threadability"] = threaded
        payload["ok"] = threaded.found
    _emit(payload)
    return 0 if payload["ok"] else 2


def _cmd_solve(args: argparse.Namespace) -> int:
    machine = load_machine()
    result = solve(
        _cells(args.source),
        args.roll or machine.roll,
        budget_nodes=args.budget_nodes,
        deadline_s=args.deadline,
        all_solutions=args.all,
        max_solutions=args.max_solutions,
    )
    _emit(result)
    return 0 if result.found else 2


def _cmd_family(args: argparse.Namespace) -> int:
    machine = load_machine()
    family = enumerate_flat(
        args.roll or machine.roll,
        _box(args.box),
        args.plane,
        base=args.base,
        modules=args.modules,
        limit=args.limit,
        budget_nodes=args.budget_nodes,
        deadline_s=args.deadline,
        cache_path=args.out,
        use_cache=not args.no_cache,
        save_cache=True,
    )
    _emit(
        {
            "out": str(args.out) if args.out else None,
            "count": len(family),
            "complete": family.complete,
            "nodes": family.nodes,
            "elapsed_s": family.elapsed_s,
            "box": family.box,
            "plane_axis": family.plane_axis,
            "unique_drawings": len(family.unique_indices()),
        }
    )
    return 0


def _cmd_fold(args: argparse.Namespace) -> int:
    machine = load_machine()
    profile = load_profile(args.profile)
    goal = _goal_pose(
        args.goal,
        roll=args.roll or machine.roll,
        k=args.k,
        beam_width=args.beam_width,
        seed=args.seed,
    )
    start = Pose((0,) * machine.joints, goal.roll, base=args.base, lying=None)
    result = search_fold(
        start,
        goal,
        machine=machine,
        profile=profile,
        node_budget=args.node_budget,
        time_budget_s=args.time_budget,
        detour_budget=args.detour_budget,
        max_candidates=args.max_candidates,
        exhaustive=args.exhaustive,
    )
    if args.out:
        dump_json(result, args.out)
    _emit(result)
    return 0 if result.status.value == "FOUND" else 2


def _moves(raw: Sequence[Any]) -> list[Move]:
    result: list[Move] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(
                Move(
                    int(item["joint"]),
                    int(item["delta"]),
                    str(item["side"]),  # type: ignore[arg-type]
                    float(item.get("duration_s", 2.0)),
                )
            )
        else:
            result.append(Move(int(item[0]), int(item[1]), str(item[2])))  # type: ignore[arg-type]
    return result


def _cmd_check(args: argparse.Namespace) -> int:
    machine = load_machine()
    profile = load_profile(args.profile)
    if args.plan.casefold() == "heart":
        candidate = replay_heart(machine=machine, profile=profile)
    else:
        raw = _read_json(Path(args.plan))
        if isinstance(raw, dict) and raw.get("plans"):
            raw = raw["plans"][args.candidate]
        if not isinstance(raw, dict) or not {"start", "goal", "moves"} <= raw.keys():
            raise ValueError("plan JSON needs start, goal, and moves")
        start = _pose(raw["start"], default_roll=machine.roll)
        goal = _pose(raw["goal"], default_roll=start.roll)
        candidate = replay(
            start,
            _moves(raw["moves"]),
            goal=goal,
            machine=machine,
            profile=profile,
        )
    _emit(candidate)
    return 0 if candidate.complete and candidate.hard_ok else 2


def _cmd_match(args: argparse.Namespace) -> int:
    machine = load_machine()
    target = get_icon(args.icon)
    family = load_family(args.family) if args.family else None
    results = match(
        target,
        args.roll or machine.roll,
        k=args.k,
        family=family,
        beam_width=args.beam_width,
        seed=args.seed,
    )
    if args.out:
        dump_json(results, args.out)
    if args.render_dir:
        directory = Path(args.render_dir)
        for index, result in enumerate(results, start=1):
            render_top(result.cells, directory / f"{target.concept}-{index:02d}.png", numbered=True)
    _emit(results)
    return 0 if results else 2


def _cmd_pipeline(args: argparse.Namespace) -> int:
    run = run_pipeline(
        args.icon,
        args.out,
        profile=args.profile,
        strict_profile=args.strict_profile,
        seed=args.seed,
        k=args.k,
        beam_width=args.beam_width,
        family=args.family,
        proposals=args.proposals,
        time_budget_s=args.time_budget,
        node_budget=args.node_budget,
        detour_budget=args.detour_budget,
        max_candidates=args.max_candidates,
        include_heart_certificate=not args.no_certificate,
        library_root=args.library,
    )
    _emit(run)
    return 0


def _cmd_harvest(args: argparse.Namespace) -> int:
    result = harvest(
        args.out,
        icons=args.icons or DEMO_NAMES,
        seed=args.seed,
        duration_s=args.duration,
        profile=args.profile,
        strict_profile=args.strict_profile,
        k=args.k,
        beam_width=args.beam_width,
        node_budget=args.node_budget,
        detour_budget=args.detour_budget,
        max_candidates=args.max_candidates,
        family=args.family,
        proposals=args.proposals,
        library_root=args.library,
        resume=not args.no_resume,
    )
    _emit(result)
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    cells = _cells(args.source)
    directory = Path(args.out)
    top = render_top(cells, directory / "top.png", numbered=args.numbered)
    iso = render_iso(cells, directory / "iso.png")
    _emit({"top": top, "iso": iso})
    return 0


def _import_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".gz" or path.suffix == ".jsonl":
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
            return [json.loads(line) for line in handle if line.strip()]
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        return [dict(item) for item in raw]
    return [dict(raw)]


def _cmd_library_import(args: argparse.Namespace) -> int:
    library = Library(args.root)
    added: list[str] = []
    for source in args.files:
        for row in _import_rows(Path(source)):
            row["status"] = "proposed"
            row["human_pick"] = None
            row["plans"] = []
            row.setdefault("aliases", [])
            row.setdefault("notes", []).append("imported as untrusted; revalidation required")
            path = library.add(row, replace=args.replace)
            added.append(str(path))
    _emit({"added": added, "count": len(added)})
    return 0


def _cmd_library_list(args: argparse.Namespace) -> int:
    entries = Library(args.root).entries()
    if args.status:
        entries = [entry for entry in entries if entry.get("status") == args.status]
    _emit(entries)
    return 0


def _cmd_library_pick(args: argparse.Namespace) -> int:
    paths = Library(args.root).pick(args.names, replace=args.replace)
    _emit({"updated": paths})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cubot", description=__doc__)
    parser.add_argument("--version", action="version", version="cubot-v2 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("screen", help="run ordered shape feasibility screens")
    command.add_argument("source", help="icon name, ASCII/JSON file, or JSON cell list")
    command.add_argument("--expected-count", type=int, default=27)
    command.add_argument("--roll")
    command.add_argument("--budget-nodes", type=int, default=4_000_000)
    command.add_argument("--thread-budget-nodes", type=int, default=2_000_000)
    command.add_argument("--deadline", type=float)
    command.add_argument("--no-hamiltonian", action="store_true")
    command.add_argument("--skip-threadability", action="store_true")
    command.set_defaults(handler=_cmd_screen)

    command = commands.add_parser("solve", help="solve exact roll-aware threadability")
    command.add_argument("source")
    command.add_argument("--roll")
    command.add_argument("--budget-nodes", type=int, default=2_000_000)
    command.add_argument("--deadline", type=float)
    command.add_argument("--all", action="store_true")
    command.add_argument("--max-solutions", type=int, default=64)
    command.set_defaults(handler=_cmd_solve)

    command = commands.add_parser("family", help="enumerate a flat shipped-roll family")
    command.add_argument("--roll")
    command.add_argument("--box", default="8x8")
    command.add_argument("--plane", default="auto")
    command.add_argument("--base", type=int, default=0)
    command.add_argument("--modules", type=int)
    command.add_argument("--limit", type=int)
    command.add_argument("--budget-nodes", type=int)
    command.add_argument("--deadline", type=float)
    command.add_argument("--out", type=Path)
    command.add_argument("--no-cache", action="store_true")
    command.set_defaults(handler=_cmd_family)

    command = commands.add_parser("fold", help="search a checked fold order")
    command.add_argument("goal", help="icon name or pose JSON")
    command.add_argument("--profile", default="loose")
    command.add_argument("--roll")
    command.add_argument("--base", type=int, default=0)
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("-k", type=int, default=1)
    command.add_argument("--beam-width", type=int, default=1200)
    command.add_argument("--node-budget", type=int)
    command.add_argument("--time-budget", type=float)
    command.add_argument("--detour-budget", type=int)
    command.add_argument("--max-candidates", type=int, default=8)
    command.add_argument("--exhaustive", action="store_true")
    command.add_argument("--out", type=Path)
    command.set_defaults(handler=_cmd_fold)

    command = commands.add_parser("check", help="replay and recheck an explicit plan")
    command.add_argument("plan", help="heart or checked-plan/record JSON")
    command.add_argument("--profile", default="loose")
    command.add_argument("--candidate", type=int, default=0)
    command.set_defaults(handler=_cmd_check)

    command = commands.add_parser("match", help="match an icon to roll-compatible flat paths")
    command.add_argument("icon", choices=ICON_NAMES)
    command.add_argument("--roll")
    command.add_argument("-k", type=int, default=5)
    command.add_argument("--beam-width", type=int, default=1200)
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("--family", type=Path)
    command.add_argument("--out", type=Path)
    command.add_argument("--render-dir", type=Path)
    command.set_defaults(handler=_cmd_match)

    command = commands.add_parser("pipeline", help="run one complete offline icon pipeline")
    command.add_argument("icon", choices=ICON_NAMES)
    command.add_argument("--out", type=Path, default=Path("runs"))
    command.add_argument("--profile", default="loose")
    command.add_argument("--strict-profile", default="strict")
    command.add_argument(
        "--strict-report",
        action="store_true",
        help="compatibility flag; strict reports are always written",
    )
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("-k", type=int, default=5)
    command.add_argument("--beam-width", type=int, default=1200)
    command.add_argument("--family", type=Path)
    command.add_argument("--proposals", type=Path)
    command.add_argument("--time-budget", type=float)
    command.add_argument("--node-budget", type=int)
    command.add_argument("--detour-budget", type=int)
    command.add_argument("--max-candidates", type=int, default=8)
    command.add_argument("--no-certificate", action="store_true")
    command.add_argument("--library", type=Path)
    command.set_defaults(handler=_cmd_pipeline)

    command = commands.add_parser("harvest", help="run or resume the seeded icon harvest")
    command.add_argument("--out", type=Path, default=Path("harvest"))
    command.add_argument("--icons", nargs="*", choices=ICON_NAMES)
    command.add_argument("--duration", type=float, default=1800.0)
    command.add_argument("--profile", default="loose")
    command.add_argument("--strict-profile", default="strict")
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("-k", type=int, default=5)
    command.add_argument("--beam-width", type=int, default=1200)
    command.add_argument("--family", type=Path)
    command.add_argument("--proposals", type=Path)
    command.add_argument("--node-budget", type=int)
    command.add_argument("--detour-budget", type=int)
    command.add_argument("--max-candidates", type=int, default=8)
    command.add_argument("--library", type=Path)
    command.add_argument("--no-resume", action="store_true")
    command.set_defaults(handler=_cmd_harvest)

    command = commands.add_parser("render", help="render top and isometric shape views")
    command.add_argument("source")
    command.add_argument("--out", type=Path, default=Path("renders"))
    command.add_argument("--numbered", action="store_true")
    command.set_defaults(handler=_cmd_render)

    command = commands.add_parser("library", help="manage the checked shape library")
    library_commands = command.add_subparsers(dest="library_command", required=True)
    action = library_commands.add_parser("import", help="import proposals as untrusted")
    action.add_argument("files", nargs="+", type=Path)
    action.add_argument("--root", type=Path, default=Path("library"))
    action.add_argument("--replace", action="store_true")
    action.set_defaults(handler=_cmd_library_import)
    action = library_commands.add_parser("list", help="list library records")
    action.add_argument("--root", type=Path, default=Path("library"))
    action.add_argument("--status")
    action.set_defaults(handler=_cmd_library_list)
    action = library_commands.add_parser("pick", help="record explicit human picks")
    action.add_argument("names", nargs="+")
    action.add_argument("--root", type=Path, default=Path("library"))
    action.add_argument("--replace", action="store_true")
    action.set_defaults(handler=_cmd_library_pick)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"cubot: error: {exc}\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
