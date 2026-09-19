"""Shape authoring, canonicalization, and graph-level feasibility screens.

Cells use exact integer lattice coordinates.  ASCII input is written top row
first, while NumPy occupancy grids use row zero at the bottom.  The structural
screens deliberately know nothing about a CuBot roll word; the final
``hamiltonian`` stage answers whether *some* ordinary face-connected chain can
thread the cells.  :mod:`cubot.solver` applies the machine kinematics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import time
from typing import Iterable, Iterator, Mapping, Sequence

import numpy as np

from .records import Cell, SearchStatus


NEIGHBOURS: tuple[Cell, ...] = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
STAGES = (
    "duplicates",
    "count",
    "connected",
    "parity",
    "degree",
    "articulation",
    "hamiltonian",
)


def _cell(value: Sequence[int]) -> Cell:
    if len(value) != 3:
        raise ValueError(f"cell must have three coordinates, got {value!r}")
    return (int(value[0]), int(value[1]), int(value[2]))


def add(a: Cell, b: Cell) -> Cell:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def adjacent(a: Cell, b: Cell) -> bool:
    return sum(abs(a[i] - b[i]) for i in range(3)) == 1


def neighbours(cell: Cell) -> Iterator[Cell]:
    for delta in NEIGHBOURS:
        yield add(cell, delta)


def parity(cell: Cell) -> int:
    return sum(cell) & 1


def planar_projection(cells: Iterable[Sequence[int]]) -> tuple[tuple[int, int], ...]:
    """Project a flat/mostly-flat shape onto its two most informative axes.

    Reachable flat families are not necessarily stored in the world XY plane;
    for example, the shipped 8x8 family lies in XZ.  Selecting axes by span
    keeps matching and human-review renders independent of that world-frame
    convention while preserving input path order.
    """

    materialized = tuple(_cell(cell) for cell in cells)
    if not materialized:
        return ()
    values = np.asarray(materialized, dtype=int)
    spans = np.ptp(values, axis=0)
    axes = sorted(range(3), key=lambda axis: (-int(spans[axis]), axis))[:2]
    return tuple((int(cell[axes[0]]), int(cell[axes[1]])) for cell in values)


def adjacency(cells: Iterable[Sequence[int]]) -> dict[Cell, tuple[Cell, ...]]:
    unique = {_cell(cell) for cell in cells}
    return {
        cell: tuple(next_cell for next_cell in neighbours(cell) if next_cell in unique)
        for cell in sorted(unique)
    }


def components(cells: Iterable[Sequence[int]]) -> list[tuple[Cell, ...]]:
    """Return face-connected components, largest first."""

    remaining = {_cell(cell) for cell in cells}
    result: list[tuple[Cell, ...]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        seen = {start}
        stack = [start]
        while stack:
            for candidate in neighbours(stack.pop()):
                if candidate in remaining:
                    remaining.remove(candidate)
                    seen.add(candidate)
                    stack.append(candidate)
        result.append(tuple(sorted(seen)))
    result.sort(key=lambda item: (-len(item), item))
    return result


def parity_split(cells: Iterable[Sequence[int]]) -> tuple[int, int]:
    even = odd = 0
    for raw in cells:
        if parity(_cell(raw)):
            odd += 1
        else:
            even += 1
    return even, odd


def degrees(cells: Iterable[Sequence[int]]) -> dict[Cell, int]:
    return {cell: len(near) for cell, near in adjacency(cells).items()}


def articulation_components(cells: Iterable[Sequence[int]]) -> dict[Cell, int]:
    """Number of components left by removing each articulation vertex.

    This is the standard Tarjan low-link algorithm, so the complete screen is
    O(V + E), rather than removing every cell and repeatedly flood-filling.
    Only cells that actually increase the component count are returned.
    """

    graph = adjacency(cells)
    if len(graph) < 3:
        return {}
    discovery: dict[Cell, int] = {}
    low: dict[Cell, int] = {}
    parent: dict[Cell, Cell | None] = {}
    result: dict[Cell, int] = {}
    tick = 0

    def visit(vertex: Cell) -> None:
        nonlocal tick
        tick += 1
        discovery[vertex] = low[vertex] = tick
        children = 0
        separating_children = 0
        for nxt in graph[vertex]:
            if nxt not in discovery:
                parent[nxt] = vertex
                children += 1
                visit(nxt)
                low[vertex] = min(low[vertex], low[nxt])
                if low[nxt] >= discovery[vertex]:
                    separating_children += 1
            elif nxt != parent.get(vertex):
                low[vertex] = min(low[vertex], discovery[nxt])

        if parent.get(vertex) is None:
            if children > 1:
                result[vertex] = children
        elif separating_children:
            # One component contains the parent side; each separating child
            # subtree is another component.
            result[vertex] = separating_children + 1

    for root in graph:
        if root not in discovery:
            parent[root] = None
            visit(root)
    return result


@dataclass(frozen=True, slots=True)
class HamiltonianResult:
    status: SearchStatus
    path: tuple[Cell, ...] | None
    nodes: int
    deepest: int
    elapsed_s: float

    @property
    def found(self) -> bool:
        return self.status is SearchStatus.FOUND


def hamiltonian_path(
    cells: Iterable[Sequence[int]],
    *,
    budget_nodes: int = 4_000_000,
    deadline_s: float | None = None,
) -> HamiltonianResult:
    """Find an unconstrained Hamiltonian path in a lattice-cell set.

    ``UNSAT`` is returned only after exhaustive closure.  Reaching either the
    node or wall-clock budget returns ``TIMEOUT`` and never populates the
    failure memo with the abandoned node.
    """

    started = time.monotonic()
    target = tuple(sorted({_cell(cell) for cell in cells}))
    n_cells = len(target)
    if not target:
        return HamiltonianResult(SearchStatus.FOUND, (), 0, 0, 0.0)
    graph = adjacency(target)
    index = {cell: i for i, cell in enumerate(target)}
    graph_i = tuple(tuple(index[nxt] for nxt in graph[cell]) for cell in target)
    colors = tuple(parity(cell) for cell in target)
    even = colors.count(0)
    odd = n_cells - even
    if len(components(target)) != 1 or abs(even - odd) > 1:
        return HamiltonianResult(
            SearchStatus.UNSAT, None, 0, 0, time.monotonic() - started
        )

    majority = 0 if even > odd else 1 if odd > even else None
    all_mask = (1 << n_cells) - 1
    nodes = 0
    deepest = 1
    timed_out = False
    failed: set[tuple[int, int]] = set()
    chosen: list[int] = []
    deadline = started + deadline_s if deadline_s is not None else math.inf

    def remaining_ok(current: int, mask: int) -> bool:
        remaining_mask = all_mask ^ mask
        left = remaining_mask.bit_count()
        if not left:
            return True

        first_bit = remaining_mask & -remaining_mask
        seen = first_bit
        frontier = first_bit
        while frontier:
            bit = frontier & -frontier
            frontier ^= bit
            vertex = bit.bit_length() - 1
            for nxt in graph_i[vertex]:
                nxt_bit = 1 << nxt
                if remaining_mask & nxt_bit and not seen & nxt_bit:
                    seen |= nxt_bit
                    frontier |= nxt_bit
        if seen != remaining_mask:
            return False

        same = opposite = 0
        leaves = 0
        bits = remaining_mask
        while bits:
            bit = bits & -bits
            bits ^= bit
            vertex = bit.bit_length() - 1
            if colors[vertex] == colors[current]:
                same += 1
            else:
                opposite += 1
            available_degree = sum(
                1
                for nxt in graph_i[vertex]
                if nxt == current or remaining_mask & (1 << nxt)
            )
            if available_degree == 0:
                return False
            if available_degree == 1:
                leaves += 1
                if leaves > 1:
                    return False
        return opposite == (left + 1) // 2 and same == left // 2

    def walk(current: int, mask: int) -> bool:
        nonlocal nodes, deepest, timed_out
        if mask == all_mask:
            return True
        if nodes >= budget_nodes or time.monotonic() >= deadline:
            timed_out = True
            return False
        nodes += 1
        deepest = max(deepest, mask.bit_count())
        key = (current, mask)
        if key in failed:
            return False

        options: list[tuple[int, int]] = []
        for nxt in graph_i[current]:
            bit = 1 << nxt
            if mask & bit:
                continue
            freedom = sum(1 for q in graph_i[nxt] if not mask & (1 << q))
            options.append((freedom, nxt))
        options.sort()
        for _, nxt in options:
            bit = 1 << nxt
            next_mask = mask | bit
            if remaining_ok(nxt, next_mask):
                chosen.append(nxt)
                if walk(nxt, next_mask):
                    return True
                chosen.pop()
            if timed_out:
                return False
        failed.add(key)
        return False

    starts = range(n_cells)
    for start in starts:
        if majority is not None and colors[start] != majority:
            continue
        chosen[:] = [start]
        start_mask = 1 << start
        if remaining_ok(start, start_mask) and walk(start, start_mask):
            path = tuple(target[i] for i in chosen)
            return HamiltonianResult(
                SearchStatus.FOUND, path, nodes, n_cells, time.monotonic() - started
            )
        if timed_out:
            return HamiltonianResult(
                SearchStatus.TIMEOUT,
                None,
                nodes,
                deepest,
                time.monotonic() - started,
            )
    return HamiltonianResult(
        SearchStatus.UNSAT, None, nodes, deepest, time.monotonic() - started
    )


@dataclass(frozen=True, slots=True)
class ScreenCheck:
    passed: bool
    reason: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScreenReport:
    ok: bool
    stage: str | None
    reason: str
    checks: Mapping[str, ScreenCheck]
    unique_cells: tuple[Cell, ...]
    chain: tuple[Cell, ...] | None = None
    hamiltonian_status: SearchStatus | None = None

    def __bool__(self) -> bool:
        return self.ok

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "stage": self.stage,
            "reason": self.reason,
            "checks": {
                name: {
                    "passed": check.passed,
                    "reason": check.reason,
                    "details": dict(check.details),
                }
                for name, check in self.checks.items()
            },
            "hamiltonian_status": (
                self.hamiltonian_status.value if self.hamiltonian_status else None
            ),
        }


def screen(
    cells: Iterable[Sequence[int]],
    expected_count: int = 27,
    *,
    include_hamiltonian: bool = True,
    budget_nodes: int = 4_000_000,
    deadline_s: float | None = None,
) -> ScreenReport:
    """Run ordered shape screens and stop expensive work after first failure."""

    raw = tuple(_cell(cell) for cell in cells)
    unique = tuple(sorted(set(raw)))
    checks: dict[str, ScreenCheck] = {}
    duplicate_count = len(raw) - len(unique)
    checks["duplicates"] = ScreenCheck(
        duplicate_count == 0,
        "all cells are distinct"
        if duplicate_count == 0
        else f"{duplicate_count} duplicate cell(s); rest poses cannot overlap",
        {"input_count": len(raw), "unique_count": len(unique)},
    )
    checks["count"] = ScreenCheck(
        len(unique) == expected_count,
        f"{len(unique)} cells, need exactly {expected_count}",
        {"actual": len(unique), "expected": expected_count},
    )

    parts = components(unique)
    checks["connected"] = ScreenCheck(
        len(parts) == 1,
        "one face-connected component"
        if len(parts) == 1
        else f"{len(parts)} disconnected components with sizes "
        + ", ".join(str(len(part)) for part in parts),
        {"components": len(parts), "sizes": tuple(map(len, parts))},
    )

    degree_map = degrees(unique)
    isolated = tuple(cell for cell, degree in degree_map.items() if degree == 0)
    endpoints = tuple(cell for cell, degree in degree_map.items() if degree == 1)
    even, odd = parity_split(unique)
    majority = 0 if even > odd else 1 if odd > even else None
    bad_endpoints = (
        tuple(cell for cell in endpoints if parity(cell) != majority)
        if len(unique) % 2 and majority is not None
        else ()
    )
    split_ok = even == odd if len(unique) % 2 == 0 else abs(even - odd) == 1
    parity_ok = split_ok and not bad_endpoints
    if not split_ok:
        parity_reason = f"checkerboard split {even}/{odd}; " + (
            "need equal classes" if len(unique) % 2 == 0 else "need a 1-cell imbalance"
        )
    elif bad_endpoints:
        parity_reason = (
            f"checkerboard split {even}/{odd}, but odd-cell path endpoints must "
            f"have majority parity {majority}; bad endpoint(s): {bad_endpoints}"
        )
    else:
        parity_reason = f"checkerboard split {even}/{odd} and endpoint colors pass"
    checks["parity"] = ScreenCheck(
        parity_ok,
        parity_reason,
        {
            "even": even,
            "odd": odd,
            "majority": majority,
            "bad_endpoints": bad_endpoints,
        },
    )

    degree_ok = (len(unique) == 1 or not isolated) and len(endpoints) <= 2
    if isolated and len(unique) != 1:
        degree_reason = f"{len(isolated)} isolated cell(s): {isolated}"
    elif len(endpoints) > 2:
        degree_reason = f"{len(endpoints)} degree-1 cells {endpoints}; a path has at most 2 endpoints"
    else:
        degree_reason = f"{len(endpoints)} forced endpoint(s), degree constraints pass"
    checks["degree"] = ScreenCheck(
        degree_ok,
        degree_reason,
        {
            "endpoints": endpoints,
            "isolated": isolated,
            "bad_endpoints": bad_endpoints,
        },
    )

    cuts = articulation_components(unique) if len(parts) == 1 else {}
    bad_cuts = {cell: count for cell, count in cuts.items() if count >= 3}
    articulation_ok = not bad_cuts
    checks["articulation"] = ScreenCheck(
        articulation_ok,
        "no cell separates the shape into three or more pieces"
        if articulation_ok
        else "; ".join(
            f"removing {cell} creates {count} components"
            for cell, count in sorted(bad_cuts.items())
        ),
        {"component_counts": cuts},
    )

    first_failure = next(
        (name for name in STAGES[:-1] if not checks[name].passed), None
    )
    ham_result: HamiltonianResult | None = None
    if include_hamiltonian and first_failure is None:
        ham_result = hamiltonian_path(
            unique, budget_nodes=budget_nodes, deadline_s=deadline_s
        )
        if ham_result.status is SearchStatus.FOUND:
            ham_reason = f"Hamiltonian path found after {ham_result.nodes} nodes"
        elif ham_result.status is SearchStatus.TIMEOUT:
            ham_reason = (
                f"Hamiltonian search hit its budget after {ham_result.nodes} nodes; "
                "undecided, not proven impossible"
            )
        else:
            ham_reason = (
                f"no Hamiltonian path exists after exhaustive search of "
                f"{ham_result.nodes} nodes"
            )
        checks["hamiltonian"] = ScreenCheck(
            ham_result.status is SearchStatus.FOUND,
            ham_reason,
            {
                "status": ham_result.status.value,
                "nodes": ham_result.nodes,
                "deepest": ham_result.deepest,
            },
        )
        if ham_result.status is not SearchStatus.FOUND:
            first_failure = "hamiltonian"
    elif include_hamiltonian:
        checks["hamiltonian"] = ScreenCheck(
            False,
            f"not run because {first_failure} failed",
            {"status": "NOT_RUN"},
        )

    ok = first_failure is None
    reason = (
        "passes all requested screens"
        if ok
        else checks[first_failure].reason
    )
    return ScreenReport(
        ok=ok,
        stage=first_failure,
        reason=reason,
        checks=checks,
        unique_cells=unique,
        chain=ham_result.path if ham_result else None,
        hamiltonian_status=ham_result.status if ham_result else None,
    )


def parse_ascii(
    rows: str | Sequence[str], *, plane: str = "xy", filled: str | None = None
) -> tuple[Cell, ...]:
    """Parse top-first ASCII rows into cells.

    By default every character except ``.`` and whitespace is filled.  ``plane``
    may be ``xy``, ``xz``, or ``yz``.
    """

    if isinstance(rows, str):
        lines = tuple(line.rstrip("\n") for line in rows.strip("\n").splitlines())
    else:
        lines = tuple(str(line) for line in rows)
    if plane not in {"xy", "xz", "yz"}:
        raise ValueError("plane must be 'xy', 'xz', or 'yz'")
    result: list[Cell] = []
    height = len(lines)
    for row_index, line in enumerate(lines):
        vertical = height - row_index - 1
        for horizontal, char in enumerate(line):
            occupied = char in filled if filled is not None else char not in ". \t"
            if not occupied:
                continue
            if plane == "xy":
                result.append((horizontal, vertical, 0))
            elif plane == "xz":
                result.append((horizontal, 0, vertical))
            else:
                result.append((0, horizontal, vertical))
    return tuple(result)


from_ascii = parse_ascii


def parse_layers(text: str | Sequence[str], *, order: str = "top-first") -> tuple[Cell, ...]:
    """Parse a layered ASCII mask (z-slices) into 3D cells.

    Slices are separated by a blank line or a line starting with ``---``;
    ``//`` lines are comments.  Within a slice rows are top-first (``y`` grows
    upward) exactly like :func:`parse_ascii`; with ``order="top-first"`` the
    first slice is the *highest* layer, so every axis reads high→low down the
    file and a flat 2D mask is a valid one-layer file.  ``order="bottom-first"``
    reverses the slice order.  All slices must share one height and width.
    """

    if order not in {"top-first", "bottom-first"}:
        raise ValueError("order must be 'top-first' or 'bottom-first'")
    lines = text.splitlines() if isinstance(text, str) else [str(line) for line in text]
    slices: list[list[str]] = [[]]
    for raw in lines:
        line = raw.strip().replace(" ", "")
        if line.startswith("//"):
            continue
        if not line or line.startswith("---"):
            if slices[-1]:
                slices.append([])
            continue
        slices[-1].append(line)
    slices = [s for s in slices if s]
    if not slices:
        raise ValueError("layered mask is empty")
    height = len(slices[0])
    width = len(slices[0][0])
    for index, rows in enumerate(slices):
        if len(rows) != height or any(len(row) != width for row in rows):
            raise ValueError(f"layer {index} is not {width}x{height}; all layers must share one box")
        if any(ch not in ".#" for row in rows for ch in row):
            raise ValueError("layered masks use only '.' and '#'")
    if order == "bottom-first":
        slices = slices[::-1]
    depth = len(slices)
    cells: list[Cell] = []
    for layer_index, rows in enumerate(slices):
        z = depth - 1 - layer_index
        for row_index, row in enumerate(rows):
            y = height - 1 - row_index
            for x, ch in enumerate(row):
                if ch == "#":
                    cells.append((x, y, z))
    return tuple(cells)


def to_layers(
    cells: Iterable[Sequence[int]], *, filled: str = "#", empty: str = "."
) -> list[list[str]]:
    """Inverse of :func:`parse_layers`: one row list per z-slice, top layer first."""

    pts = [(int(c[0]), int(c[1]), int(c[2])) for c in cells]
    if not pts:
        return []
    xs, ys, zs = zip(*pts)
    occupied = set(pts)
    layers: list[list[str]] = []
    for z in range(max(zs), min(zs) - 1, -1):
        rows = []
        for y in range(max(ys), min(ys) - 1, -1):
            rows.append("".join(filled if (x, y, z) in occupied else empty for x in range(min(xs), max(xs) + 1)))
        layers.append(rows)
    return layers


def rotations_3d(cells: Iterable[Sequence[int]]) -> Iterator[tuple[Cell, ...]]:
    """The cell set under each of the 24 proper lattice rotations, moved to the origin corner."""

    from .lattice import ORIENTS

    arr = np.asarray([tuple(int(v) for v in c) for c in cells], dtype=int)
    if arr.size == 0:
        yield ()
        return
    for matrix in ORIENTS:
        rotated = (matrix @ arr.T).T
        rotated -= rotated.min(axis=0)
        yield tuple(sorted(tuple(int(v) for v in row) for row in rotated))


def canonical_3d(cells: Iterable[Sequence[int]], *, reflect: bool = False) -> tuple[Cell, ...]:
    """Canonical translation/rotation-invariant key for a 3D cell set (24 rotations; 48 with ``reflect``)."""

    pts = [tuple(int(v) for v in c) for c in cells]
    views = list(rotations_3d(pts))
    if reflect:
        views.extend(rotations_3d([(-x, y, z) for x, y, z in pts]))
    return min(views, default=())


def has_2x2x2_block(cells: Iterable[Sequence[int]]) -> bool:
    """True when any filled 2x2x2 block exists — a two-thick solid in disguise (docs/CUBE_FEASIBILITY.md)."""

    occupied = {tuple(int(v) for v in c) for c in cells}
    for x, y, z in occupied:
        if all((x + dx, y + dy, z + dz) in occupied for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)):
            return True
    return False


def dense_cell_count(cells: Iterable[Sequence[int]]) -> int:
    """Cells with no axis along which both face-neighbours are empty (report only, not a gate)."""

    occupied = {tuple(int(v) for v in c) for c in cells}
    count = 0
    for x, y, z in occupied:
        ridge = False
        for axis in range(3):
            plus = [x, y, z]; minus = [x, y, z]
            plus[axis] += 1; minus[axis] -= 1
            if tuple(plus) not in occupied and tuple(minus) not in occupied:
                ridge = True
                break
        if not ridge:
            count += 1
    return count


def _plane_axes(cells: Sequence[Cell], plane: str = "auto") -> tuple[int, int, int]:
    if plane != "auto":
        mapping = {"xy": (0, 1, 2), "xz": (0, 2, 1), "yz": (1, 2, 0)}
        try:
            return mapping[plane]
        except KeyError as exc:
            raise ValueError("plane must be auto, xy, xz, or yz") from exc
    if not cells:
        return (0, 1, 2)
    spans = [max(c[i] for c in cells) - min(c[i] for c in cells) for i in range(3)]
    constant = [axis for axis, span in enumerate(spans) if span == 0]
    if not constant:
        raise ValueError("cells are not planar")
    normal = constant[-1]
    axes = tuple(axis for axis in range(3) if axis != normal)
    return (axes[0], axes[1], normal)


def project_planar(
    cells: Iterable[Sequence[int]], plane: str = "auto"
) -> tuple[tuple[int, int], ...]:
    values = tuple(_cell(cell) for cell in cells)
    horizontal, vertical, _ = _plane_axes(values, plane)
    return tuple((cell[horizontal], cell[vertical]) for cell in values)


def planar_views(
    cells: Iterable[Sequence[int]], *, plane: str = "auto", reflect: bool = True
) -> Iterator[tuple[tuple[int, int], ...]]:
    """Yield normalized sorted views under the four rotations and mirrors."""

    base = project_planar(cells, plane)
    mirror_options = (False, True) if reflect else (False,)
    for mirrored in mirror_options:
        transformed = [(-x if mirrored else x, y) for x, y in base]
        for quarter_turns in range(4):
            rotated = list(transformed)
            for _ in range(quarter_turns):
                rotated = [(-y, x) for x, y in rotated]
            min_x = min((x for x, _ in rotated), default=0)
            min_y = min((y for _, y in rotated), default=0)
            yield tuple(sorted((x - min_x, y - min_y) for x, y in rotated))


def canonical_planar(
    cells: Iterable[Sequence[int]], *, plane: str = "auto", reflect: bool = True
) -> tuple[tuple[int, int], ...]:
    """Canonical translation/dihedral-invariant key for a planar cell set."""

    return min(planar_views(cells, plane=plane, reflect=reflect), default=())


def occupancy(cells: Iterable[Sequence[int]], *, plane: str = "auto") -> np.ndarray:
    raw = project_planar(cells, plane=plane)
    min_x = min((x for x, _ in raw), default=0)
    min_y = min((y for _, y in raw), default=0)
    points = tuple((x - min_x, y - min_y) for x, y in raw)
    if not points:
        return np.zeros((0, 0), dtype=bool)
    width = max(x for x, _ in points) + 1
    height = max(y for _, y in points) + 1
    grid = np.zeros((height, width), dtype=bool)
    for x, y in points:
        grid[y, x] = True
    return grid


def to_ascii(
    cells: Iterable[Sequence[int]],
    *,
    plane: str = "auto",
    filled: str = "#",
    empty: str = ".",
) -> str:
    grid = occupancy(cells, plane=plane)
    return "\n".join(
        "".join(filled if value else empty for value in row)
        for row in grid[::-1]
    )


_RUN_DIRECTIONS: dict[str, Cell] = {
    "E": (1, 0, 0),
    "W": (-1, 0, 0),
    "N": (0, 1, 0),
    "S": (0, -1, 0),
    "U": (0, 0, 1),
    "D": (0, 0, -1),
}


def runs_to_cells(runs: str, *, start: Cell = (0, 0, 0)) -> tuple[Cell, ...]:
    """Expand ``E6 S2 U1`` (commas optional) into an ordered path."""

    current = _cell(start)
    result = [current]
    tokens = re.findall(r"([EWNSUDewnsud])\s*(\d+)", runs.replace(",", " "))
    residue = re.sub(r"([EWNSUDewnsud])\s*(\d+)|[,\s]+", "", runs)
    if residue:
        raise ValueError(f"invalid compass runs near {residue!r}")
    for direction, raw_count in tokens:
        delta = _RUN_DIRECTIONS[direction.upper()]
        for _ in range(int(raw_count)):
            current = add(current, delta)
            result.append(current)
    return tuple(result)


def cells_to_runs(cells: Sequence[Sequence[int]]) -> str:
    values = tuple(_cell(cell) for cell in cells)
    if len(values) < 2:
        return ""
    names = {value: key for key, value in _RUN_DIRECTIONS.items()}
    directions: list[str] = []
    for before, after in zip(values, values[1:]):
        delta = tuple(after[i] - before[i] for i in range(3))
        if delta not in names:
            raise ValueError(f"cells are not a face-connected path at {before} -> {after}")
        directions.append(names[delta])
    runs: list[str] = []
    current = directions[0]
    count = 1
    for direction in directions[1:]:
        if direction == current:
            count += 1
        else:
            runs.append(f"{current}{count}")
            current, count = direction, 1
    runs.append(f"{current}{count}")
    return " ".join(runs)


def iou(a: Iterable[Sequence[int]], b: Iterable[Sequence[int]]) -> float:
    left = set(canonical_planar(a, reflect=False))
    right = set(canonical_planar(b, reflect=False))
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def chamfer_distance(a: Iterable[Sequence[int]], b: Iterable[Sequence[int]]) -> float:
    left = tuple(canonical_planar(a, reflect=False))
    right = tuple(canonical_planar(b, reflect=False))
    if not left or not right:
        return math.inf if left or right else 0.0

    def directed(source: Sequence[tuple[int, int]], target: Sequence[tuple[int, int]]) -> float:
        return sum(
            min(abs(x - u) + abs(y - v) for u, v in target)
            for x, y in source
        ) / len(source)

    return 0.5 * (directed(left, right) + directed(right, left))


__all__ = [
    "HamiltonianResult",
    "NEIGHBOURS",
    "STAGES",
    "ScreenCheck",
    "ScreenReport",
    "adjacency",
    "adjacent",
    "articulation_components",
    "canonical_planar",
    "cells_to_runs",
    "chamfer_distance",
    "components",
    "degrees",
    "from_ascii",
    "hamiltonian_path",
    "iou",
    "neighbours",
    "occupancy",
    "parity",
    "parity_split",
    "parse_ascii",
    "planar_views",
    "project_planar",
    "runs_to_cells",
    "screen",
    "to_ascii",
]
