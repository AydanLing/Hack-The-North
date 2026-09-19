"""Exact roll-aware threading search for CuBot lattice shapes.

The Hamiltonian and kinematic searches are fused: a DFS node carries the
current cell, module orientation, and occupied-cell bit mask.  Only the three
directions the next diagonal joint can physically select are expanded.  A
failed-state memo includes the occupancy mask; omitting it is unsound because
the same head cell and frame can have different usable remainders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Integral
import time
from typing import Iterable, Sequence

from .lattice import DIRS, ORIENTS, POST, fk
from .records import Cell, Pose, SearchStatus
from .shapes import adjacency, components, parity, parity_split


@dataclass(frozen=True, slots=True)
class Threading:
    """One exact realization of a target cell set."""

    states: tuple[int, ...]
    base: int
    path: tuple[Cell, ...]
    frames: tuple[int, ...]

    def __post_init__(self) -> None:
        if any(
            isinstance(state, bool)
            or not isinstance(state, Integral)
            or int(state) not in (-1, 0, 1)
            for state in self.states
        ):
            raise ValueError("threading states must be physical positions in {-1, 0, +1}")

    def as_pose(self, roll: str, *, lying: int | None = None) -> Pose:
        if len(self.states) != 26:
            raise ValueError("only a 27-module threading can be converted to Pose")
        return Pose(states=self.states, roll=roll, base=self.base, lying=lying)


@dataclass(frozen=True, slots=True)
class SolveResult:
    status: SearchStatus
    solutions: tuple[Threading, ...]
    nodes: int
    deepest: int
    elapsed_s: float
    exhaustive: bool
    diagnostics: tuple[str, ...] = field(default_factory=tuple)
    roll: str = ""

    @property
    def found(self) -> bool:
        return self.status is SearchStatus.FOUND

    @property
    def solution(self) -> Threading | None:
        return self.solutions[0] if self.solutions else None

    @property
    def poses(self) -> tuple[Pose, ...]:
        """Machine-size solutions as public :class:`~cubot.records.Pose`s."""

        if not self.solutions or len(self.solutions[0].states) != 26:
            return ()
        return tuple(solution.as_pose(self.roll) for solution in self.solutions)


def _direction(orient: int, state: int) -> Cell:
    value = DIRS[orient][state]
    return (int(value[0]), int(value[1]), int(value[2]))


def _post(orient: int, state: int, roll: int) -> int:
    return int(POST[orient][state][roll])


def _validate_roll(roll: str, joints: int) -> tuple[int, ...]:
    if len(roll) < joints:
        raise ValueError(f"roll has {len(roll)} digits; need at least {joints}")
    prefix = roll[:joints]
    if any(char not in "0123" for char in prefix):
        raise ValueError("roll must contain only digits 0..3")
    return tuple(int(char) for char in prefix)


def _prepare(cells: Iterable[Sequence[int]]) -> tuple[tuple[Cell, ...], tuple[tuple[int, ...], ...]]:
    raw_list: list[Cell] = []
    for cell in cells:
        if len(cell) != 3:
            raise ValueError("cells must be integer triples")
        raw_list.append((int(cell[0]), int(cell[1]), int(cell[2])))
    raw = tuple(raw_list)
    if len(set(raw)) != len(raw):
        raise ValueError("target cells must be distinct")
    values = tuple(sorted(raw))
    by_cell = adjacency(values)
    index = {cell: i for i, cell in enumerate(values)}
    graph = tuple(tuple(index[nxt] for nxt in by_cell[cell]) for cell in values)
    return values, graph


def solve(
    cells: Iterable[Sequence[int]],
    roll: str,
    *,
    budget_nodes: int = 2_000_000,
    deadline_s: float | None = None,
    all_solutions: bool = False,
    max_solutions: int = 64,
    tether: bool = False,
) -> SolveResult:
    """Thread ``cells`` under ``roll`` with exact integer kinematics.

    With ``tether`` the cell outside module 0's mount face (where the cable
    bundle leaves) must not belong to the target.

    A budget stop is always ``TIMEOUT`` unless a complete solution was already
    found, in which case the result is ``FOUND`` but ``exhaustive`` is false.
    ``UNSAT`` is reserved for a completed forward search.
    """

    started = time.monotonic()
    target, graph = _prepare(cells)
    n_cells = len(target)
    roll_digits = _validate_roll(roll, max(0, n_cells - 1))
    if budget_nodes < 0:
        raise ValueError("budget_nodes must be non-negative")
    if max_solutions < 1:
        raise ValueError("max_solutions must be positive")
    if not target:
        threading = Threading((), 0, (), ())
        return SolveResult(
            SearchStatus.FOUND,
            (threading,),
            0,
            0,
            time.monotonic() - started,
            True,
            roll=roll,
        )
    if len(components(target)) != 1:
        return SolveResult(
            SearchStatus.UNSAT,
            (),
            0,
            0,
            time.monotonic() - started,
            True,
            ("target is not face-connected",),
            roll,
        )
    even, odd = parity_split(target)
    if abs(even - odd) > 1:
        return SolveResult(
            SearchStatus.UNSAT,
            (),
            0,
            0,
            time.monotonic() - started,
            True,
            (f"checkerboard split {even}/{odd} cannot be a path",),
            roll,
        )

    cell_index = {cell: i for i, cell in enumerate(target)}
    colors = tuple(parity(cell) for cell in target)
    majority = 0 if even > odd else 1 if odd > even else None
    all_mask = (1 << n_cells) - 1
    deadline = started + deadline_s if deadline_s is not None else math.inf
    nodes = 0
    deepest = 1
    timed_out = False
    stopped_at_cap = False
    failed: set[tuple[int, int, int]] = set()
    solutions: list[Threading] = []
    seen_solutions: set[tuple[int, tuple[int, ...], tuple[Cell, ...]]] = set()
    state_path: list[int] = []
    cell_path: list[int] = []
    frame_path: list[int] = []

    def remaining_ok(current: int, occupied: int) -> bool:
        remaining = all_mask ^ occupied
        left = remaining.bit_count()
        if not left:
            return True

        # The unvisited set must be one connected component: the chain can
        # leave the current endpoint only once.
        first = remaining & -remaining
        seen = first
        frontier = first
        while frontier:
            bit = frontier & -frontier
            frontier ^= bit
            vertex = bit.bit_length() - 1
            for nxt in graph[vertex]:
                nxt_bit = 1 << nxt
                if remaining & nxt_bit and not seen & nxt_bit:
                    seen |= nxt_bit
                    frontier |= nxt_bit
        if seen != remaining:
            return False

        same = opposite = 0
        forced_ends = 0
        bits = remaining
        while bits:
            bit = bits & -bits
            bits ^= bit
            vertex = bit.bit_length() - 1
            if colors[vertex] == colors[current]:
                same += 1
            else:
                opposite += 1
            available = sum(
                1
                for nxt in graph[vertex]
                if nxt == current or remaining & (1 << nxt)
            )
            if available == 0:
                return False
            if available == 1:
                forced_ends += 1
                if forced_ends > 1:
                    return False
        return opposite == (left + 1) // 2 and same == left // 2

    def emit(base: int) -> None:
        nonlocal stopped_at_cap
        # The DFS indexes the three geometry residues as 0/1/2.  Public poses
        # use the hardware's unique physical representatives 0/+1/-1.
        states = tuple(-1 if state == 2 else state for state in state_path)
        path = tuple(target[i] for i in cell_path)
        frames = tuple(frame_path)
        key = (base, states, path)
        if key in seen_solutions:
            return
        # An independent replay guards table/index mistakes in the DFS.
        replay_cells, replay_frames = fk(states, roll[: len(states)], base=base)
        replay = tuple(tuple(map(int, cell)) for cell in replay_cells)
        offset = tuple(path[0][axis] - replay[0][axis] for axis in range(3))
        translated = tuple(
            tuple(cell[axis] + offset[axis] for axis in range(3)) for cell in replay
        )
        if translated != path or tuple(map(int, replay_frames)) != frames:
            raise AssertionError("solver solution failed exact FK replay")
        seen_solutions.add(key)
        solutions.append(Threading(states, base, path, frames))
        if len(solutions) >= max_solutions:
            stopped_at_cap = True

    def walk(current: int, orient: int, occupied: int, base: int) -> bool:
        """Return whether this state has at least one complete continuation."""

        nonlocal nodes, deepest, timed_out
        if occupied == all_mask:
            emit(base)
            return True
        if nodes >= budget_nodes or time.monotonic() >= deadline:
            timed_out = True
            return False
        nodes += 1
        depth = occupied.bit_count()
        deepest = max(deepest, depth)
        key = (current, orient, occupied)
        if key in failed:
            return False

        candidates: list[tuple[int, int, int, int]] = []
        for state in range(3):
            direction = _direction(orient, state)
            next_cell = (
                target[current][0] + direction[0],
                target[current][1] + direction[1],
                target[current][2] + direction[2],
            )
            nxt = cell_index.get(next_cell)
            if nxt is None or occupied & (1 << nxt):
                continue
            freedom = sum(1 for q in graph[nxt] if not occupied & (1 << q))
            next_orient = _post(orient, state, roll_digits[depth - 1])
            candidates.append((freedom, state, nxt, next_orient))
        candidates.sort()

        any_found = False
        for _, state, nxt, next_orient in candidates:
            next_occupied = occupied | (1 << nxt)
            if not remaining_ok(nxt, next_occupied):
                continue
            state_path.append(state)
            cell_path.append(nxt)
            frame_path.append(next_orient)
            branch_found = walk(nxt, next_orient, next_occupied, base)
            frame_path.pop()
            cell_path.pop()
            state_path.pop()
            any_found |= branch_found
            if branch_found and not all_solutions:
                return True
            if timed_out or stopped_at_cap:
                return any_found
        if not any_found and not timed_out and not stopped_at_cap:
            failed.add(key)
        return any_found

    stop = False
    for start in range(n_cells):
        if majority is not None and colors[start] != majority:
            continue
        for base in range(len(ORIENTS)):
            if tether:
                mount = _direction(base, 0)
                keep_out = (target[start][0] - mount[0], target[start][1] - mount[1], target[start][2] - mount[2])
                if keep_out in cell_index:
                    continue
            cell_path[:] = [start]
            frame_path[:] = [base]
            state_path.clear()
            occupied = 1 << start
            if remaining_ok(start, occupied):
                found = walk(start, base, occupied, base)
                if found and not all_solutions:
                    stop = True
            if stop or timed_out or stopped_at_cap:
                break
        if stop or timed_out or stopped_at_cap:
            break

    elapsed = time.monotonic() - started
    if solutions:
        diagnostics: list[str] = []
        if timed_out:
            diagnostics.append("solution found; additional enumeration hit a budget")
        if stopped_at_cap:
            diagnostics.append(f"solution enumeration stopped at cap {max_solutions}")
        return SolveResult(
            SearchStatus.FOUND,
            tuple(solutions),
            nodes,
            n_cells,
            elapsed,
            all_solutions and not timed_out and not stopped_at_cap,
            tuple(diagnostics),
            roll,
        )
    if timed_out:
        return SolveResult(
            SearchStatus.TIMEOUT,
            (),
            nodes,
            deepest,
            elapsed,
            False,
            ("node or wall-clock budget exhausted",),
            roll,
        )
    return SolveResult(
        SearchStatus.UNSAT, (), nodes, deepest, elapsed, True, roll=roll
    )


def brute_force_solve(cells: Iterable[Sequence[int]], roll: str) -> SolveResult:
    """Small, deliberately unpruned reference solver used by differential tests."""

    started = time.monotonic()
    target, _ = _prepare(cells)
    n_cells = len(target)
    roll_digits = _validate_roll(roll, max(0, n_cells - 1))
    if not target:
        return SolveResult(
            SearchStatus.FOUND,
            (Threading((), 0, (), ()),),
            0,
            0,
            time.monotonic() - started,
            True,
        )
    cell_index = {cell: i for i, cell in enumerate(target)}
    all_mask = (1 << n_cells) - 1
    nodes = 0
    deepest = 1
    states: list[int] = []
    path: list[int] = []
    frames: list[int] = []

    def walk(current: int, orient: int, occupied: int) -> bool:
        nonlocal nodes, deepest
        nodes += 1
        deepest = max(deepest, occupied.bit_count())
        if occupied == all_mask:
            return True
        depth = occupied.bit_count()
        for state in range(3):
            direction = _direction(orient, state)
            next_cell = tuple(target[current][axis] + direction[axis] for axis in range(3))
            nxt = cell_index.get(next_cell)
            if nxt is None or occupied & (1 << nxt):
                continue
            next_orient = _post(orient, state, roll_digits[depth - 1])
            states.append(state)
            path.append(nxt)
            frames.append(next_orient)
            if walk(nxt, next_orient, occupied | (1 << nxt)):
                return True
            frames.pop()
            path.pop()
            states.pop()
        return False

    for start in range(n_cells):
        for base in range(len(ORIENTS)):
            states.clear()
            path[:] = [start]
            frames[:] = [base]
            if walk(start, base, 1 << start):
                solution = Threading(
                    tuple(-1 if state == 2 else state for state in states),
                    base,
                    tuple(target[i] for i in path),
                    tuple(frames),
                )
                return SolveResult(
                    SearchStatus.FOUND,
                    (solution,),
                    nodes,
                    n_cells,
                    time.monotonic() - started,
                    True,
                )
    return SolveResult(
        SearchStatus.UNSAT,
        (),
        nodes,
        deepest,
        time.monotonic() - started,
        True,
    )


def explain_unreachable(cells: Iterable[Sequence[int]], roll: str, **kwargs: object) -> str:
    result = solve(cells, roll, **kwargs)
    if result.status is SearchStatus.FOUND:
        return f"threadable: found a {len(result.solution.states) + 1}-module path"
    if result.status is SearchStatus.TIMEOUT:
        return (
            f"undecided: budget ended after {result.nodes} nodes; "
            f"deepest module reached was {result.deepest}"
        )
    return (
        f"unthreadable under this roll: exhaustive closure visited {result.nodes} nodes; "
        f"deepest module reached was {result.deepest}"
    )


__all__ = [
    "SolveResult",
    "Threading",
    "brute_force_solve",
    "explain_unreachable",
    "solve",
]
