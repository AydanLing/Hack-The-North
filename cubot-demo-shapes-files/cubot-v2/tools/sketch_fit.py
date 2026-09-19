"""Snap a rough ASCII sketch to a foldable 27-cell CuBot target.

Drawing a legal target by hand is unreasonable: it has to be exactly 27 cells,
face-connected, checkerboard-split 14/13 with both path endpoints on the
majority colour, have at most two degree-1 cells, and then still thread on the
shipped roll -- and that last filter is brutal (the shipped arrow came from 68
threadings out of 15,099 contour variants).

So this walks the neighbourhood of a sketch instead.  A simulated-annealing
walk over cell sets keeps size and connectivity as hard invariants and is
steered by overlap with the sketch; every legal mask it passes through is
collected, ranked by IoU against the sketch, and handed to the exact roll
solver best-first until one threads.

    uv run python tools/sketch_fit.py sketches.txt --out fitted.txt

The input is one or more blocks::

    === maple-leaf
    ...###.
    .###.#.

Output is the same format, carrying only the masks that thread.  A threadable
mask is still only a *goal*: it has no fold order yet.  Run `cubot fold` next.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cubot.config import load_machine
from cubot.solver import solve

N_CELLS = 27


# --------------------------------------------------------------------------- io

def parse_blocks(path: Path) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    name: str | None = None
    rows: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith("==="):
            if name is not None:
                blocks.append((name, rows))
            name, rows = line[3:].strip(), []
        elif line.strip():
            rows.append(line.strip())
    if name is not None:
        blocks.append((name, rows))
    return blocks


def cells_of(rows: list[str]) -> set[tuple[int, int]]:
    height = len(rows)
    return {
        (x, height - 1 - y)
        for y, row in enumerate(rows)
        for x, char in enumerate(row)
        if char == "#"
    }


def render(cells: set[tuple[int, int]]) -> list[str]:
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return [
        "".join("#" if (x, y) in cells else "." for x in range(min(xs), max(xs) + 1))
        for y in range(max(ys), min(ys) - 1, -1)
    ]


# ------------------------------------------------------------------- geometry

def neighbours(cell, cells):
    x, y = cell
    return [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if n in cells]


def connected(cells) -> bool:
    if not cells:
        return False
    start = next(iter(cells))
    seen = {start}
    queue = deque([start])
    while queue:
        for n in neighbours(queue.popleft(), cells):
            if n not in seen:
                seen.add(n)
                queue.append(n)
    return len(seen) == len(cells)


def articulations(cells) -> set:
    """Cells whose removal would disconnect the set (iterative Tarjan)."""
    if not cells:
        return set()
    adjacency = {c: neighbours(c, cells) for c in cells}
    root = next(iter(cells))
    order: dict = {}
    low: dict = {}
    parent: dict = {root: None}
    out: set = set()
    counter = 0
    root_children = 0
    stack = [(root, iter(adjacency[root]))]
    order[root] = low[root] = counter
    counter += 1
    while stack:
        node, children = stack[-1]
        advanced = False
        for child in children:
            if child not in order:
                parent[child] = node
                if node is root:
                    root_children += 1
                order[child] = low[child] = counter
                counter += 1
                stack.append((child, iter(adjacency[child])))
                advanced = True
                break
            if child is not parent[node]:
                low[node] = min(low[node], order[child])
        if not advanced:
            stack.pop()
            if stack:
                up = stack[-1][0]
                low[up] = min(low[up], low[node])
                if up is not root and low[node] >= order[up]:
                    out.add(up)
    if root_children > 1:
        out.add(root)
    return out


def violations(cells) -> int:
    """Weighted count of cheap-screen breaches: parity, endpoint colour, tips."""
    even = sum(1 for (x, y) in cells if (x + y) % 2 == 0)
    odd = len(cells) - even
    majority = 0 if even > odd else 1
    tips = [c for c in cells if len(neighbours(c, cells)) == 1]
    return (
        4 * abs(abs(even - odd) - 1)
        + 2 * max(0, len(tips) - 2)
        + 2 * sum(1 for c in tips if (c[0] + c[1]) % 2 != majority)
    )


def legal(cells) -> bool:
    """The cheap screens: parity split, endpoint colour, degree-1 budget."""
    return violations(cells) == 0


def iou(a, b) -> float:
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------- search

def frontier(cells, box):
    x0, y0, x1, y1 = box
    out = set()
    for (x, y) in cells:
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in cells and x0 <= n[0] <= x1 and y0 <= n[1] <= y1:
                out.add(n)
    return out


def largest_component(cells):
    """The biggest face-connected piece of a sketch that may be disconnected."""
    remaining = set(cells)
    best: set = set()
    while remaining:
        start = next(iter(remaining))
        seen = {start}
        queue = deque([start])
        while queue:
            for n in neighbours(queue.popleft(), remaining):
                if n not in seen:
                    seen.add(n)
                    queue.append(n)
        remaining -= seen
        if len(seen) > len(best):
            best = seen
    return best


def seeded(want, box, rng):
    """A connected 27-cell set close to the sketch, to start a walk from.

    Sketches are allowed to be disconnected -- a dotted eye, a detached bar --
    so the walk starts from the largest connected piece and grows back toward
    the rest of the drawing.
    """
    cells = largest_component(want)
    while len(cells) > N_CELLS:
        movable = [c for c in cells if c not in articulations(cells)]
        if not movable:
            return None
        cells.remove(min(movable, key=lambda c: (len(neighbours(c, cells)), rng.random())))
    while len(cells) < N_CELLS:
        options = frontier(cells, box)
        if not options:
            return None
        cells.add(max(options, key=lambda c: (c in want, len(neighbours(c, cells)), rng.random())))
    return cells if connected(cells) else None


def collect(want, *, walks: int, steps: int, pad: int, seed: int) -> dict:
    """Return {frozenset: iou} for every legal mask the walks pass through."""
    xs = [c[0] for c in want]
    ys = [c[1] for c in want]
    box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    found: dict[frozenset, float] = {}
    for walk in range(walks):
        rng = random.Random(seed * 1000 + walk)
        cells = seeded(want, box, rng)
        if cells is None:
            continue
        current = violations(cells) - 3.0 * iou(cells, want)
        for step in range(steps):
            temperature = 1.5 * (0.02 / 1.5) ** (step / steps)
            movable = [c for c in cells if c not in articulations(cells)]
            if not movable:
                break
            trial = cells - {rng.choice(movable)}
            options = sorted(frontier(trial, box))
            if not options:
                continue
            trial.add(rng.choice(options))
            if not connected(trial):
                continue
            score = violations(trial) - 3.0 * iou(trial, want)
            if score <= current or rng.random() < math.exp(-(score - current) / temperature):
                cells, current = trial, score
                if legal(cells):
                    found.setdefault(frozenset(cells), iou(cells, want))
    return found


def thread(cells, roll: str, budget: int):
    """Exact shipped-roll threading for one mask."""
    result = solve([(x, y, 0) for (x, y) in cells], roll, budget_nodes=budget)
    return result if result.solutions else None


def fit(name: str, rows: list[str], *, roll: str, walks: int, steps: int,
        pad: int, tests: int, budget: int, seed: int, verbose=sys.stderr):
    want = cells_of(rows)
    pool = collect(want, walks=walks, steps=steps, pad=pad, seed=seed)
    ranked = sorted(pool.items(), key=lambda kv: -kv[1])
    print(f"  {name}: {len(ranked)} legal variants from {walks} walks", file=verbose)
    for index, (cells, overlap) in enumerate(ranked[:tests]):
        result = thread(set(cells), roll, budget)
        if result is not None:
            print(f"  {name}: THREADS at rank {index + 1}/{len(ranked)}, iou={overlap:.2f}",
                  file=verbose)
            return set(cells), overlap, index + 1
    print(f"  {name}: no threading in the top {min(tests, len(ranked))} variants",
          file=verbose)
    return None, 0.0, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sketches", type=Path, help="ASCII sketch file, '=== name' blocks")
    parser.add_argument("--out", type=Path, help="write threadable masks here")
    parser.add_argument("--roll", help="override the machine roll word")
    parser.add_argument("--walks", type=int, default=12, help="annealing restarts per sketch")
    parser.add_argument("--steps", type=int, default=4000, help="steps per walk")
    parser.add_argument("--pad", type=int, default=1, help="cells of slack around the sketch box")
    parser.add_argument("--tests", type=int, default=400, help="variants to roll-test, best IoU first")
    parser.add_argument("--budget-nodes", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    roll = args.roll or load_machine().roll
    blocks = parse_blocks(args.sketches)
    lines: list[str] = []
    hits = 0
    for name, rows in blocks:
        cells, overlap, rank = fit(
            name, rows, roll=roll, walks=args.walks, steps=args.steps,
            pad=args.pad, tests=args.tests, budget=args.budget_nodes, seed=args.seed,
        )
        if cells is None:
            continue
        hits += 1
        lines.append(f"=== {name}  (iou {overlap:.2f}, variant rank {rank})")
        lines.extend(render(cells))
        lines.append("")
    print(f"{hits}/{len(blocks)} sketches produced a threadable 27-cell target", file=sys.stderr)
    text = "\n".join(lines) + ("\n" if lines else "")
    if args.out:
        args.out.write_text(text)
    else:
        sys.stdout.write(text)
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
