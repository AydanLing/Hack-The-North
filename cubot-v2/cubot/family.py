"""Enumeration and persistent caching of roll-specific flat drawings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterable

import numpy as np

from .lattice import DIRS, ORIENTS, POST


FORMAT_VERSION = 1
DEFAULT_PLANE_AXIS = 1  # y=0; the shipped-family plane


def _box(value: int | tuple[int, int]) -> tuple[int, int]:
    if isinstance(value, int):
        result = (value, value)
    else:
        result = (int(value[0]), int(value[1]))
    if min(result) < 2:
        raise ValueError("both flat-family box dimensions must be at least 2")
    return result


def _plane_axis(plane: str | int) -> int:
    if plane == "auto":
        return DEFAULT_PLANE_AXIS
    if isinstance(plane, int) and plane in (0, 1, 2):
        return plane
    mapping = {"yz": 0, "xz": 1, "xy": 2}
    try:
        return mapping[str(plane)]
    except KeyError as exc:
        raise ValueError("plane must be auto, xy, xz, yz, or an axis 0..2") from exc


def _canonical_2d(cells: np.ndarray) -> tuple[tuple[int, int], ...]:
    points = [(int(x), int(y)) for x, y in cells]
    views: list[tuple[tuple[int, int], ...]] = []
    for mirror in (False, True):
        base = [(-x if mirror else x, y) for x, y in points]
        for turns in range(4):
            rotated = list(base)
            for _ in range(turns):
                rotated = [(-y, x) for x, y in rotated]
            lo_x = min(x for x, _ in rotated)
            lo_y = min(y for _, y in rotated)
            views.append(tuple(sorted((x - lo_x, y - lo_y) for x, y in rotated)))
    return min(views)


@dataclass(slots=True)
class Family:
    roll: str
    box: tuple[int, int]
    plane_axis: int
    base: int
    modules: int
    states: np.ndarray
    cells: np.ndarray
    complete: bool
    nodes: int = 0
    elapsed_s: float = 0.0

    def __post_init__(self) -> None:
        self.states = np.asarray(self.states, dtype=np.uint8)
        self.cells = np.asarray(self.cells, dtype=np.int8)
        expected_states = (len(self.cells), max(0, self.modules - 1))
        expected_cells = (len(self.states), self.modules, 2)
        if self.states.shape != expected_states:
            raise ValueError(
                f"states has shape {self.states.shape}, expected {expected_states}"
            )
        if self.cells.shape != expected_cells:
            raise ValueError(f"cells has shape {self.cells.shape}, expected {expected_cells}")

    def __len__(self) -> int:
        return len(self.states)

    @property
    def normalized_cells(self) -> np.ndarray:
        if not len(self):
            return self.cells.copy()
        values = self.cells.astype(np.int16)
        return (values - values.min(axis=1, keepdims=True)).astype(np.int8)

    @property
    def widths(self) -> np.ndarray:
        if not len(self):
            return np.zeros(0, dtype=np.int16)
        cells = self.normalized_cells
        return cells[:, :, 0].max(axis=1).astype(np.int16) + 1

    @property
    def heights(self) -> np.ndarray:
        if not len(self):
            return np.zeros(0, dtype=np.int16)
        cells = self.normalized_cells
        return cells[:, :, 1].max(axis=1).astype(np.int16) + 1

    def canonical_keys(self) -> tuple[tuple[tuple[int, int], ...], ...]:
        return tuple(_canonical_2d(cells) for cells in self.cells)

    def unique_indices(self) -> np.ndarray:
        seen: set[tuple[tuple[int, int], ...]] = set()
        result: list[int] = []
        for index, key in enumerate(self.canonical_keys()):
            if key not in seen:
                seen.add(key)
                result.append(index)
        return np.asarray(result, dtype=np.int64)

    def occupancy(self, index: int) -> np.ndarray:
        cells = self.normalized_cells[int(index)]
        width = int(cells[:, 0].max()) + 1
        height = int(cells[:, 1].max()) + 1
        result = np.zeros((height, width), dtype=bool)
        result[cells[:, 1], cells[:, 0]] = True
        return result

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            target,
            format=np.int16(FORMAT_VERSION),
            roll=np.str_(self.roll),
            box=np.asarray(self.box, dtype=np.int16),
            plane_axis=np.int8(self.plane_axis),
            base=np.int8(self.base),
            modules=np.int16(self.modules),
            states=self.states,
            cells=self.cells,
            complete=np.bool_(self.complete),
            nodes=np.int64(self.nodes),
            elapsed_s=np.float64(self.elapsed_s),
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "Family":
        with np.load(Path(path), allow_pickle=False) as data:
            if int(data["format"]) != FORMAT_VERSION:
                raise ValueError("unsupported flat-family cache format")
            return cls(
                roll=str(data["roll"]),
                box=tuple(int(v) for v in data["box"]),
                plane_axis=int(data["plane_axis"]),
                base=int(data["base"]),
                modules=int(data["modules"]),
                states=data["states"].copy(),
                cells=data["cells"].copy(),
                complete=bool(data["complete"]),
                nodes=int(data["nodes"]),
                elapsed_s=float(data["elapsed_s"]),
            )

    def matches(
        self,
        *,
        roll: str,
        box: tuple[int, int],
        plane_axis: int,
        base: int,
        modules: int,
        require_complete: bool,
    ) -> bool:
        return (
            self.roll == roll
            and self.box == box
            and self.plane_axis == plane_axis
            and self.base == base
            and self.modules == modules
            and (self.complete or not require_complete)
        )


def enumerate_flat(
    roll: str,
    box: int | tuple[int, int] = (8, 8),
    plane: str | int = "auto",
    *,
    base: int = 0,
    modules: int | None = None,
    limit: int | None = None,
    budget_nodes: int | None = None,
    deadline_s: float | None = None,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
    save_cache: bool = True,
) -> Family:
    """Enumerate oriented, self-avoiding flat walks within ``box``.

    No canonical deduplication happens during enumeration: the 8x8 family
    count is an *oriented walk* count.  Call
    :meth:`Family.unique_indices` when a drawing-only catalogue is desired.
    Tests should set ``modules`` and/or ``limit``; the complete 27-module 8x8
    family is intentionally not built by ordinary test runs.
    """

    started = time.monotonic()
    dimensions = _box(box)
    axis = _plane_axis(plane)
    if modules is None:
        modules = len(roll) + 1
    modules = int(modules)
    if modules < 1:
        raise ValueError("modules must be positive")
    if len(roll) < modules - 1:
        raise ValueError(f"roll has {len(roll)} digits; need {modules - 1}")
    if any(char not in "0123" for char in roll[: modules - 1]):
        raise ValueError("roll must contain only digits 0..3")
    if not 0 <= base < len(ORIENTS):
        raise ValueError(f"base must be in 0..{len(ORIENTS) - 1}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if budget_nodes is not None and budget_nodes < 0:
        raise ValueError("budget_nodes must be non-negative")

    require_complete = limit is None and budget_nodes is None and deadline_s is None
    if cache_path is not None and use_cache and Path(cache_path).exists():
        try:
            cached = Family.load(cache_path)
            if cached.matches(
                roll=roll,
                box=dimensions,
                plane_axis=axis,
                base=base,
                modules=modules,
                require_complete=require_complete,
            ):
                if limit is None:
                    return cached
                if cached.complete or len(cached) >= limit:
                    return Family(
                        cached.roll,
                        cached.box,
                        cached.plane_axis,
                        cached.base,
                        cached.modules,
                        cached.states[:limit],
                        cached.cells[:limit],
                        cached.complete and len(cached) <= limit,
                        cached.nodes,
                        cached.elapsed_s,
                    )
        except (OSError, ValueError, KeyError):
            pass

    axes = tuple(index for index in range(3) if index != axis)
    horizontal, vertical = axes
    width, height = dimensions
    deadline = started + deadline_s if deadline_s is not None else float("inf")
    roll_digits = tuple(int(char) for char in roll[: modules - 1])
    path_states = [0] * max(0, modules - 1)
    path_cells = [(0, 0)] * modules
    occupied = {(0, 0)}
    output_states: list[tuple[int, ...]] = []
    output_cells: list[tuple[tuple[int, int], ...]] = []
    nodes = 0
    stopped = False

    def walk(
        joint: int,
        orient: int,
        x: int,
        y: int,
        min_x: int,
        max_x: int,
        min_y: int,
        max_y: int,
    ) -> None:
        nonlocal nodes, stopped
        if stopped:
            return
        if joint == modules - 1:
            output_states.append(tuple(path_states))
            output_cells.append(tuple(path_cells))
            if limit is not None and len(output_states) >= limit:
                stopped = True
            return
        if budget_nodes is not None and nodes >= budget_nodes:
            stopped = True
            return
        if time.monotonic() >= deadline:
            stopped = True
            return
        nodes += 1
        for state in range(3):
            direction = DIRS[orient][state]
            if int(direction[axis]) != 0:
                continue
            dx = int(direction[horizontal])
            dy = int(direction[vertical])
            next_x, next_y = x + dx, y + dy
            next_cell = (next_x, next_y)
            if next_cell in occupied:
                continue
            lo_x = min(min_x, next_x)
            hi_x = max(max_x, next_x)
            lo_y = min(min_y, next_y)
            hi_y = max(max_y, next_y)
            if hi_x - lo_x >= width or hi_y - lo_y >= height:
                continue
            occupied.add(next_cell)
            path_states[joint] = state
            path_cells[joint + 1] = next_cell
            next_orient = int(POST[orient][state][roll_digits[joint]])
            walk(
                joint + 1,
                next_orient,
                next_x,
                next_y,
                lo_x,
                hi_x,
                lo_y,
                hi_y,
            )
            occupied.remove(next_cell)
            if stopped:
                return

    walk(0, base, 0, 0, 0, 0, 0, 0)
    state_array = (
        np.asarray(output_states, dtype=np.uint8).reshape(-1, modules - 1)
        if output_states
        else np.zeros((0, modules - 1), dtype=np.uint8)
    )
    cell_array = (
        np.asarray(output_cells, dtype=np.int8).reshape(-1, modules, 2)
        if output_cells
        else np.zeros((0, modules, 2), dtype=np.int8)
    )
    family = Family(
        roll=roll,
        box=dimensions,
        plane_axis=axis,
        base=base,
        modules=modules,
        states=state_array,
        cells=cell_array,
        complete=not stopped,
        nodes=nodes,
        elapsed_s=time.monotonic() - started,
    )
    if cache_path is not None and save_cache:
        family.save(cache_path)
    return family


def load_family(path: str | Path) -> Family:
    return Family.load(path)


__all__ = [
    "DEFAULT_PLANE_AXIS",
    "FORMAT_VERSION",
    "Family",
    "enumerate_flat",
    "load_family",
]
