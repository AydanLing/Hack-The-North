from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class PixelTarget:
    grid: np.ndarray
    concept: str
    caption: str
    source: str = "parametric"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        grid = np.asarray(self.grid, dtype=bool)
        if grid.ndim != 2 or not grid.any():
            raise ValueError("a pixel target must be a non-empty 2D grid")
        object.__setattr__(self, "grid", grid)

    @property
    def cells(self) -> tuple[tuple[int, int, int], ...]:
        height = self.grid.shape[0]
        return tuple(
            (int(x), int(height - 1 - y), 0)
            for y, x in np.argwhere(self.grid)
        )

    @property
    def rows(self) -> list[str]:
        return ["".join("#" if value else "." for value in row) for row in self.grid]


def parse_grid(rows: list[str] | tuple[str, ...]) -> np.ndarray:
    cleaned = [row.replace(" ", "") for row in rows if row.strip()]
    if not cleaned or len({len(row) for row in cleaned}) != 1:
        raise ValueError("grid rows must be non-empty and have equal width")
    if any(character not in ".#" for row in cleaned for character in row):
        raise ValueError("grid uses only '.' and '#'")
    return np.asarray([[character == "#" for character in row] for row in cleaned], dtype=bool)

