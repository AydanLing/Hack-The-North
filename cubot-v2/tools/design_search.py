#!/usr/bin/env python3
"""Find the roll-feasible 27-cell drawings nearest to an ideal sketch.

The mask-first method (``docs/METHOD.md``) draws recognizable masks and gates
them in milliseconds.  When every hand-drawn variant of a concept is roll-UNSAT
this tool is the *repair* step: sketch the ideal once, mark which cells are
negotiable, and let the gate enumerate the nearby drawings that the chain can
actually be.

Ideal files use ``#`` for required cells, ``?`` for optional cells, ``+`` for
optional cells you would rather keep, and ``.`` for empty, top row first.

The default ``walk`` mode is exhaustive: it walks the 27-module chain under the
real roll kinematics (``cubot.lattice.DIRS``/``POST``, the same tables ``fk``
uses) inside the required+optional region, in-plane, from every start cell and
base orientation, and keeps every drawing that covers all required cells.  Each
hit is then confirmed through the official gate (``cubot.shapes.screen`` +
``cubot.solver.solve``).  ``combos`` mode instead enumerates 27-cell subsets
of the region and gates each one; it is the fallback when the region is huge.
Threadable drawings are ranked by Hamming distance to the ideal (``#`` and
``+`` cells), deduplicated up to rotation/mirror, and written as
``<out>/<name>-vN.txt`` candidate files ready for ``tools/explore_shape.py``.

Usage (from ``cubot-v2/``)::

    uv run python tools/design_search.py --name crown data/ideals/crown.txt --out data/candidates/objects
    uv run python tools/design_search.py --name crown data/ideals/crown.txt --dry-run --max 10
    uv run python tools/design_search.py --name crown data/ideals/crown.txt --mode combos --cap 5000

``--ring`` marks every empty cell touching a required cell as optional so a
plain 27-cell sketch can be repaired without hand-annotating; ``--nudge N``
(combos mode) also samples random perturbations of the ``#`` cells
(``cubot.generate.glyph_atlas.perturb_to_target``).  The walk was written by
the nature worker of the 2026-09-19 library run after the sampled combos
search missed drawings the exhaustive walk finds in under a second.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import itertools
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.config import load_machine  # noqa: E402
from cubot.generate.glyph_atlas import perturb_to_target  # noqa: E402
from cubot.lattice import DIRS, POST  # noqa: E402
from cubot.shapes import canonical_planar, screen  # noqa: E402
from cubot.solver import solve  # noqa: E402

Cell2 = tuple[int, int]
TARGET = 27


def read_ideal(path: Path, *, preferred: set[Cell2] | None = None) -> tuple[set[Cell2], set[Cell2], tuple[int, int]]:
    """Return ``(required, optional, (width, height))`` in top-first image coordinates.

    ``+`` cells are optional; when ``preferred`` is given they are added to it
    so the ranking can favour drawings that keep them.
    """

    rows = [line.rstrip("\n").replace(" ", "") for line in path.read_text().splitlines()]
    rows = [row for row in rows if row and not row.startswith("//")]
    if not rows or len({len(row) for row in rows}) != 1:
        raise ValueError(f"{path}: rows must be non-empty and equal width")
    required: set[Cell2] = set()
    optional: set[Cell2] = set()
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == "#":
                required.add((x, y))
            elif char == "?":
                optional.add((x, y))
            elif char == "+":
                optional.add((x, y))
                if preferred is not None:
                    preferred.add((x, y))
            elif char != ".":
                raise ValueError(f"{path}: unexpected character {char!r}")
    return required, optional, (len(rows[0]), len(rows))


def ring(cells: set[Cell2]) -> set[Cell2]:
    """Empty cells 4-adjacent to ``cells``."""

    out: set[Cell2] = set()
    for x, y in cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in cells:
                out.add((x + dx, y + dy))
    return out


def to_rows(cells: set[Cell2]) -> tuple[str, ...]:
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    x0, y0 = min(xs), min(ys)
    width, height = max(xs) - x0 + 1, max(ys) - y0 + 1
    grid = [["."] * width for _ in range(height)]
    for x, y in cells:
        grid[y - y0][x - x0] = "#"
    return tuple("".join(row) for row in grid)


def to_cells3(cells: set[Cell2]) -> tuple[tuple[int, int, int], ...]:
    """Image coordinates (y down) to lattice coordinates (y up), as ``PixelTarget.cells`` does."""

    height = max(y for _, y in cells) + 1
    return tuple((x, height - 1 - y, 0) for x, y in sorted(cells))


def gate(task: tuple[frozenset, str] | tuple[frozenset, str, bool]) -> tuple[frozenset, str, int]:
    """Screen + thread one completion; returns ``(cells, status, threadings)`` (-1 = structural fail).

    ``task`` is ``(cells, roll[, tether])``; the tether keep-out
    (``docs/TETHER.md``) is applied exactly as ``tools/explore_shape.py`` does.
    """

    cells, roll = task[0], task[1]
    tether = bool(task[2]) if len(task) > 2 else False
    lattice = to_cells3(set(cells))
    report = screen(lattice, TARGET)
    if not report.ok:
        return cells, report.stage or "screen", -1
    result = solve(lattice, roll, all_solutions=True, max_solutions=64, tether=tether)
    return cells, result.status.value, len(result.solutions)


def completions(required: set[Cell2], optional: set[Cell2], *, cap: int, rng: random.Random):
    """Yield candidate 27-cell sets: all required cells plus a choice of optional ones."""

    need = TARGET - len(required)
    pool = sorted(optional - required)
    if need < 0 or need > len(pool):
        return
    total = math.comb(len(pool), need)
    if total <= cap:
        for chosen in itertools.combinations(pool, need):
            yield required | set(chosen)
        return
    seen: set[frozenset] = set()
    attempts = 0
    while len(seen) < cap and attempts < cap * 20:
        attempts += 1
        chosen = frozenset(rng.sample(pool, need))
        if chosen in seen:
            continue
        seen.add(chosen)
        yield required | set(chosen)


def walk_region(
    required: set[Cell2],
    optional: set[Cell2],
    roll: str,
    *,
    node_cap: int = 3_000_000,
) -> tuple[list[frozenset], int, bool]:
    """Exhaustively walk the chain inside ``required | optional`` under the roll word.

    Returns ``(drawings, nodes, capped)``: every distinct 27-cell in-plane chain
    footprint that covers all required cells, up to rotation/mirror.  Image
    coordinates map to the lattice as ``(x, y) -> (x, -y, 0)``.
    """

    roll_digits = [int(c) for c in roll]
    allowed = sorted(required | optional)
    index = {cell: i for i, cell in enumerate(allowed)}
    neighbours = {
        cell: [index[(cell[0] + dx, cell[1] + dy)] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
               if (cell[0] + dx, cell[1] + dy) in index]
        for cell in allowed
    }
    required_mask = sum(1 << index[cell] for cell in required)
    found: dict[tuple, frozenset] = {}
    failed: set[tuple] = set()
    nodes = 0
    sys.setrecursionlimit(10_000)

    def reachable(visited: int, current: int, steps_left: int) -> bool:
        need = required_mask & ~visited
        if need == 0:
            return True
        if bin(need).count("1") > steps_left:
            return False
        seen = 1 << current
        frontier = [current]
        while frontier:
            v = frontier.pop()
            for w in neighbours[allowed[v]]:
                bit = 1 << w
                if not (visited & bit) and not (seen & bit):
                    seen |= bit
                    frontier.append(w)
        return (need & ~seen) == 0

    def dfs(cell: Cell2, orientation: int, joint: int, visited: int, count: int, path: list[Cell2]) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > node_cap:
            return
        if count == TARGET:
            if (visited & required_mask) == required_mask:
                key = canonical_planar(to_cells3(set(path)))
                found.setdefault(key, frozenset(path))
            return
        state_key = (cell, orientation, joint, visited)
        if state_key in failed:
            return
        before = len(found)
        if reachable(visited, index[cell], TARGET - count):
            for state in (0, 1, 2):
                direction = DIRS[orientation, state]
                if direction[2] != 0:
                    continue
                nxt = (cell[0] + int(direction[0]), cell[1] - int(direction[1]))
                if nxt not in index:
                    continue
                bit = 1 << index[nxt]
                if visited & bit:
                    continue
                path.append(nxt)
                dfs(nxt, int(POST[orientation, state, roll_digits[joint]]), joint + 1, visited | bit, count + 1, path)
                path.pop()
                if nodes > node_cap:
                    return
        if len(found) == before:
            failed.add(state_key)

    for start in allowed:
        for base in range(24):
            dfs(start, base, 0, 1 << index[start], 1, [start])
            if nodes > node_cap:
                return list(found.values()), nodes, True
    return list(found.values()), nodes, False


def next_index(out: Path, name: str) -> int:
    existing = [int(p.stem.rsplit("-v", 1)[1]) for p in out.glob(f"{name}-v*.txt") if p.stem.rsplit("-v", 1)[1].isdigit()]
    return max(existing, default=0) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ideal", type=Path, help="ideal sketch: '#' required, '?' optional, '.' empty")
    parser.add_argument("--name", required=True, help="concept name used for the output files")
    parser.add_argument("--out", type=Path, help="candidate directory to write <name>-vN.txt files into")
    parser.add_argument("--max", type=int, default=6, help="how many ranked drawings to write")
    parser.add_argument("--mode", choices=("walk", "combos"), default="walk",
                        help="walk: exhaustive chain walk inside the region (default); combos: gate 27-cell subsets")
    parser.add_argument("--nodes", type=int, default=3_000_000, help="walk mode: DFS node cap")
    parser.add_argument("--cap", type=int, default=20_000, help="combos mode: max completions to gate (sampled beyond this)")
    parser.add_argument("--ring", action="store_true", help="treat every empty cell touching a required cell as optional")
    parser.add_argument("--nudge", type=int, default=0, help="also sample N random perturbations of the '#' cells")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="print the ranking; write nothing")
    args = parser.parse_args()

    preferred: set[Cell2] = set()
    required, optional, box = read_ideal(args.ideal, preferred=preferred)
    if args.ring:
        optional |= ring(required)
    rng = random.Random(args.seed)
    machine = load_machine()
    roll = machine.roll
    tether = bool(getattr(machine, "has_tether", False))
    ideal = set(required) | preferred

    candidates: dict[frozenset, None] = {}
    if len(required) > TARGET:
        print(f"{len(required)} required cells exceed {TARGET}; mark some as '?' or '+'")
        return 2
    if args.mode == "walk":
        drawings, nodes, capped = walk_region(required, optional, roll, node_cap=args.nodes)
        for cells in drawings:
            candidates.setdefault(cells, None)
        print(f"{args.name}: {len(required)} required + {len(optional - required)} optional cells in {box[0]}x{box[1]}; "
              f"walk visited {nodes} nodes{' (CAP HIT: raise --nodes or shrink the region)' if capped else ''}, "
              f"{len(candidates)} distinct chain footprints; confirming through the gate")
        if not candidates:
            return 1
    else:
        for cells in completions(required, optional, cap=args.cap, rng=rng):
            candidates.setdefault(frozenset(cells), None)
        if args.nudge:
            for _, cells in perturb_to_target(set(required), rng=rng, cap=args.nudge, expected_holes=None):
                candidates.setdefault(frozenset(cells), None)
        if not candidates:
            need = TARGET - len(required)
            print(f"no completions: {len(required)} required cells, {len(optional - required)} optional, need {need}")
            return 2
        print(f"{args.name}: {len(required)} required + {len(optional - required)} optional cells in {box[0]}x{box[1]}; "
              f"gating {len(candidates)} completions")

    tasks = [(cells, roll, tether) for cells in candidates]
    if args.workers > 1 and len(tasks) > 8:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(gate, tasks, chunksize=32))
    else:
        results = [gate(task) for task in tasks]

    counts: dict[str, int] = {}
    ranked: list[tuple[int, int, frozenset]] = []
    seen_keys: set = set()
    for cells, status, threadings in results:
        counts[status] = counts.get(status, 0) + 1
        if threadings <= 0:
            continue
        key = canonical_planar(to_cells3(set(cells)))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        distance = len(set(cells) ^ ideal)
        ranked.append((distance, -threadings, cells))
    ranked.sort(key=lambda item: (item[0], item[1], sorted(item[2])))
    print(f"gate: {counts}; {len(ranked)} distinct threadable drawings")

    written: list[Path] = []
    index = next_index(args.out, args.name) if args.out and not args.dry_run else 1
    for distance, neg_threadings, cells in ranked[: args.max]:
        rows = to_rows(set(cells))
        print(f"\n# distance {distance}, {-neg_threadings} threadings")
        print("\n".join(rows))
        if args.out and not args.dry_run:
            args.out.mkdir(parents=True, exist_ok=True)
            path = args.out / f"{args.name}-v{index}.txt"
            header = f"// design_search: from {args.ideal.name}, distance {distance}, {-neg_threadings} threadings\n"
            path.write_text(header + "\n".join(rows) + "\n")
            written.append(path)
            index += 1
    if written:
        print(f"\nwrote {len(written)} candidate files: {', '.join(p.name for p in written)}")
    return 0 if ranked else 1


if __name__ == "__main__":
    raise SystemExit(main())
