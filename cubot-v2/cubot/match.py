"""Match an arbitrary pixel target to a flat path held by a roll word."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import random
from typing import Any, Iterable, Sequence

import numpy as np

from .generate.base import PixelTarget
from .records import Cell, Pose
from .shapes import planar_projection

_SOURCE_PROPOSALS = Path(__file__).resolve().parent.parent / "data" / "imported" / "proposals.jsonl.gz"
_WHEEL_PROPOSALS = Path(__file__).resolve().parent / "_assets" / "data" / "imported" / "proposals.jsonl.gz"
DEFAULT_PROPOSALS = (
    _SOURCE_PROPOSALS
    if _SOURCE_PROPOSALS.is_file()
    else _WHEEL_PROPOSALS
)


@dataclass(frozen=True, slots=True)
class MatchResult:
    pose: Pose
    cells: tuple[Cell, ...]
    distance: float
    method: str
    transform: str


@dataclass(frozen=True, slots=True)
class RecognitionScore:
    """Explainable visual distance for a completed flat candidate.

    Each component is normalized to roughly ``[0, 1]``.  In contrast to a
    point-cloud-only metric, this score makes it expensive to erase a hole,
    branch, balanced stroke, or other large-scale landmark merely to move a
    few module centres closer to the drawing.
    """

    distance: float
    transform: str
    silhouette: float
    landmarks: float
    topology: float
    proportions: float
    symmetry: float
    chamfer: float


def proposal_matches(
    target: PixelTarget,
    roll: str,
    *,
    path: str | Path = DEFAULT_PROPOSALS,
    k: int = 5,
) -> list[MatchResult]:
    """Re-score cached signed words as untrusted geometric proposals.

    Feasibility flags stored alongside them are never read.  Every returned pose is
    reconstructed with current integer FK and still has to pass the current
    forward folder/checker before it can become a checked library entry.
    """

    from .lattice import fk

    source = Path(path)
    opener = gzip.open if source.suffix == ".gz" else open
    ranked: list[MatchResult] = []
    with opener(source, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            raw_states = row.get("states")
            if not isinstance(raw_states, list) or len(raw_states) != len(roll):
                continue
            try:
                # Cached proposals are geometric only.  Revalidate them using
                # the unique legal physical representative for each residue.
                states = tuple((int(value) + 1) % 3 - 1 for value in raw_states)
                pose = Pose(states, roll)
            except (TypeError, ValueError):
                continue
            cells, _ = fk(pose.states, pose.roll, pose.base)
            if len(cells) != 27 or len(set(cells)) != 27:
                continue
            distance, transform = recognition_distance(cells, target)
            ranked.append(
                MatchResult(
                    pose,
                    tuple(cells),
                    distance,
                    "proposed",
                    transform,
                )
            )
    unique: dict[frozenset[Cell], MatchResult] = {}
    for result in sorted(ranked, key=lambda item: item.distance):
        unique.setdefault(frozenset(result.cells), result)
        if len(unique) >= k:
            break
    return list(unique.values())


def _normalise(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    centred = points - points.mean(axis=0, keepdims=True)
    span = np.ptp(centred, axis=0)
    scale = max(float(span.max()), 1.0)
    return centred / scale


def _variants(points: np.ndarray) -> Iterable[tuple[str, np.ndarray]]:
    points = np.asarray(points, dtype=float)
    matrices = {
        "identity": np.array([[1, 0], [0, 1]]),
        "rot90": np.array([[0, -1], [1, 0]]),
        "rot180": np.array([[-1, 0], [0, -1]]),
        "rot270": np.array([[0, 1], [-1, 0]]),
    }
    reflected = points * np.array([-1, 1])
    for name, matrix in matrices.items():
        yield name, points @ matrix.T
        yield f"mirror-{name}", reflected @ matrix.T


def chamfer_distance(cells: Sequence[Cell], target: PixelTarget, *, partial: bool = False) -> tuple[float, str]:
    if not cells:
        return math.inf, "identity"
    candidate = _normalise(np.asarray(planar_projection(cells), dtype=float))
    # PixelTarget cells are authored in canonical XY drawing coordinates.
    # Running them through ``planar_projection`` can swap X/Y whenever the
    # drawing is taller than wide, which makes the reported transform render
    # letters such as N sideways.  Only arbitrary 3-D candidates need inferred
    # planar axes.
    wanted = _normalise(
        np.asarray([(cell[0], cell[1]) for cell in target.cells], dtype=float)
    )
    best = (math.inf, "identity")
    for name, variant in _variants(candidate):
        pairwise = np.linalg.norm(variant[:, None, :] - wanted[None, :, :], axis=2)
        directed = float(pairwise.min(axis=1).mean())
        reverse = 0.0 if partial else float(pairwise.min(axis=0).mean())
        value = directed + reverse
        if value < best[0]:
            best = (value, name)
    return best


def _raster_mask(points: np.ndarray, *, size: int = 32, pad: int = 2) -> np.ndarray:
    """Rasterize unit lattice cells onto a centered, aspect-preserving canvas."""

    points = np.asarray(points, dtype=float)
    lo = points.min(axis=0) - 0.5
    hi = points.max(axis=0) + 0.5
    span = np.maximum(hi - lo, 1.0)
    scale = (size - 2.0 * pad) / float(span.max())
    used = span * scale
    offset = (np.asarray((size, size), dtype=float) - used) / 2.0 - lo * scale
    mask = np.zeros((size, size), dtype=bool)
    for x, y in points:
        x0 = max(0, int(math.floor((x - 0.5) * scale + offset[0])))
        x1 = min(size, int(math.ceil((x + 0.5) * scale + offset[0])))
        # Cartesian y is deliberately flipped to image row order.
        y0f = size - ((y + 0.5) * scale + offset[1])
        y1f = size - ((y - 0.5) * scale + offset[1])
        y0 = max(0, int(math.floor(y0f)))
        y1 = min(size, int(math.ceil(y1f)))
        mask[y0:y1, x0:x1] = True
    return mask


def _holes(points: np.ndarray) -> int:
    occupied = {(int(x), int(y)) for x, y in np.rint(points).astype(int)}
    min_x = min(x for x, _ in occupied) - 1
    max_x = max(x for x, _ in occupied) + 1
    min_y = min(y for _, y in occupied) - 1
    max_y = max(y for _, y in occupied) + 1
    empty = {
        (x, y)
        for x in range(min_x, max_x + 1)
        for y in range(min_y, max_y + 1)
        if (x, y) not in occupied
    }
    components = 0
    while empty:
        components += 1
        stack = [empty.pop()]
        while stack:
            x, y = stack.pop()
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour in empty:
                    empty.remove(neighbour)
                    stack.append(neighbour)
    # Padding guarantees exactly one exterior empty component.
    return max(0, components - 1)


def _shape_features(points: np.ndarray) -> tuple[float, float, int, int, int, float]:
    occupied = {(int(x), int(y)) for x, y in np.rint(points).astype(int)}
    xs = [point[0] for point in occupied]
    ys = [point[1] for point in occupied]
    width = max(xs) - min(xs) + 1
    height = max(ys) - min(ys) + 1
    aspect = max(width, height) / max(1.0, min(width, height))
    fill = len(occupied) / float(width * height)
    degrees = [
        sum(neighbour in occupied for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
        for x, y in occupied
    ]
    endpoints = sum(degree == 1 for degree in degrees)
    junctions = sum(degree >= 3 for degree in degrees)
    perimeter = sum(4 - degree for degree in degrees) / max(1.0, 4.0 * len(occupied))
    return aspect, fill, _holes(points), endpoints, junctions, perimeter


def _coarse_mass(mask: np.ndarray, bins: int = 5) -> np.ndarray:
    values = np.asarray(
        [chunk.mean() for rows in np.array_split(mask, bins, axis=0) for chunk in np.array_split(rows, bins, axis=1)],
        dtype=float,
    )
    total = float(values.sum())
    return values / total if total else values


def _symmetry_signature(mask: np.ndarray) -> np.ndarray:
    area = max(1, int(mask.sum()))
    return np.asarray(
        [
            np.logical_xor(mask, np.fliplr(mask)).sum() / area,
            np.logical_xor(mask, np.flipud(mask)).sum() / area,
        ],
        dtype=float,
    )


def recognition_score(cells: Sequence[Cell], target: PixelTarget) -> RecognitionScore:
    """Score a completed candidate by recognizability, under planar symmetries.

    Raster overlap carries most of the score.  Coarse spatial mass acts as a
    landmark descriptor (for example, arrow head versus shaft), while the
    remaining terms preserve holes/branches, aspect/fill, and symmetry.  The
    old Chamfer metric is intentionally only a small tie-breaker.
    """

    if not cells:
        return RecognitionScore(math.inf, "identity", 1.0, 1.0, 1.0, 1.0, 1.0, math.inf)
    candidate = np.asarray(planar_projection(cells), dtype=float)
    wanted = np.asarray([(cell[0], cell[1]) for cell in target.cells], dtype=float)
    wanted_mask = _raster_mask(wanted)
    wanted_mass = _coarse_mass(wanted_mask)
    wanted_symmetry = _symmetry_signature(wanted_mask)
    wanted_features = _shape_features(wanted)
    wanted_normal = _normalise(wanted)
    best: RecognitionScore | None = None
    for name, variant in _variants(candidate):
        mask = _raster_mask(variant)
        union = int(np.logical_or(mask, wanted_mask).sum())
        intersection = int(np.logical_and(mask, wanted_mask).sum())
        silhouette = 1.0 - intersection / max(1, union)
        landmarks = min(1.0, 0.5 * float(np.abs(_coarse_mass(mask) - wanted_mass).sum()))
        aspect, fill, holes, endpoints, junctions, perimeter = _shape_features(variant)
        w_aspect, w_fill, w_holes, w_endpoints, w_junctions, w_perimeter = wanted_features
        topology = min(
            1.0,
            0.45 * abs(holes - w_holes)
            + 0.10 * abs(endpoints - w_endpoints)
            + 0.08 * abs(junctions - w_junctions)
            + 0.50 * abs(perimeter - w_perimeter),
        )
        proportions = min(
            1.0,
            0.65 * abs(math.log(max(aspect, 1e-9) / max(w_aspect, 1e-9)))
            + 0.80 * abs(fill - w_fill),
        )
        symmetry = min(1.0, 0.5 * float(np.abs(_symmetry_signature(mask) - wanted_symmetry).sum()))
        normalized = _normalise(variant)
        pairwise = np.linalg.norm(normalized[:, None, :] - wanted_normal[None, :, :], axis=2)
        chamfer = min(1.0, float(pairwise.min(axis=1).mean() + pairwise.min(axis=0).mean()))
        distance = (
            0.44 * silhouette
            + 0.18 * landmarks
            + 0.13 * topology
            + 0.11 * proportions
            + 0.08 * symmetry
            + 0.06 * chamfer
        )
        score = RecognitionScore(
            distance,
            name,
            silhouette,
            landmarks,
            topology,
            proportions,
            symmetry,
            chamfer,
        )
        if best is None or score.distance < best.distance:
            best = score
    assert best is not None
    return best


def recognition_distance(cells: Sequence[Cell], target: PixelTarget, *, partial: bool = False) -> tuple[float, str]:
    """Return recognition-first distance, retaining Chamfer for partial beams."""

    if partial:
        return chamfer_distance(cells, target, partial=True)
    score = recognition_score(cells, target)
    return score.distance, score.transform


def _beam_match(
    target: PixelTarget,
    roll: str,
    *,
    k: int,
    beam_width: int,
    seed: int,
    box: int = 12,
) -> list[MatchResult]:
    from .lattice import DIRS, POST

    rng = random.Random(seed)
    # (score, tie, base, orient, cells, states)
    beam: list[tuple[float, float, int, int, tuple[Cell, ...], tuple[int, ...]]] = []
    for base in range(24):
        beam.append((0.0, rng.random(), base, base, ((0, 0, 0),), ()))

    for joint, roll_digit in enumerate(map(int, roll)):
        expanded: dict[tuple[int, Cell, frozenset[Cell]], tuple[float, float, int, int, tuple[Cell, ...], tuple[int, ...]]] = {}
        for _, _, base, orient, cells, states in beam:
            head = np.asarray(cells[-1], dtype=int)
            for state in range(3):
                step = np.asarray(DIRS[orient, state], dtype=int)
                nxt = tuple(int(value) for value in head + step)
                if nxt[2] != 0 or nxt in cells:
                    continue
                trial = (*cells, nxt)
                xs = [cell[0] for cell in trial]
                ys = [cell[1] for cell in trial]
                if max(xs) - min(xs) >= box or max(ys) - min(ys) >= box:
                    continue
                next_orient = int(POST[orient, state, roll_digit])
                distance, _ = recognition_distance(trial, target, partial=joint < 25)
                # Mildly favour turns so the beam does not collapse into long lines.
                turn_bonus = -0.002 if states and state != 0 else 0.0
                item = (distance + turn_bonus, rng.random(), base, next_orient, trial, (*states, state))
                key = (next_orient, nxt, frozenset(trial))
                if key not in expanded or item[:2] < expanded[key][:2]:
                    expanded[key] = item
        if not expanded:
            break
        beam = sorted(expanded.values(), key=lambda item: item[:2])[:beam_width]

    results: list[MatchResult] = []
    seen: set[frozenset[Cell]] = set()
    for _, _, base, _, cells, states in sorted(beam, key=lambda item: item[:2]):
        if len(states) != 26:
            continue
        signature = frozenset(cells)
        if signature in seen:
            continue
        seen.add(signature)
        distance, transform = recognition_distance(cells, target)
        results.append(
            MatchResult(
                pose=Pose(
                    tuple(-1 if int(state) == 2 else int(state) for state in states),
                    roll,
                    base=base,
                ),
                cells=cells,
                distance=distance,
                method="beam",
                transform=transform,
            )
        )
        if len(results) >= k:
            break
    return results


def _compact_family_match(
    target: PixelTarget,
    family: Any,
    *,
    k: int,
    shortlist: int = 4096,
) -> list[MatchResult]:
    """Two-stage lookup for a compact :class:`cubot.family.Family` cache.

    Width/aspect/fill features cheaply pre-rank the complete family; the
    shortlist is then scored with the recognition-first metric.  This keeps an
    839,903-walk cache interactive without allocating a family × target-pixel
    raster tensor.
    """

    count = len(family)
    if count == 0:
        return []
    target_points = planar_projection(target.cells)
    target_width = max(point[0] for point in target_points) - min(point[0] for point in target_points) + 1
    target_height = max(point[1] for point in target_points) - min(point[1] for point in target_points) + 1
    target_ratio = max(target_width, target_height) / max(1, min(target_width, target_height))
    target_fill = len(target.cells) / float(target_width * target_height)
    widths = np.asarray(family.widths, dtype=float)
    heights = np.asarray(family.heights, dtype=float)
    ratios = np.maximum(widths, heights) / np.maximum(1.0, np.minimum(widths, heights))
    fills = float(family.modules) / np.maximum(1.0, widths * heights)
    feature_distance = np.abs(np.log(np.maximum(ratios, 1e-9) / target_ratio))
    feature_distance += 0.35 * np.abs(fills - target_fill)
    take = min(count, max(shortlist, k * 32))
    indices = np.argpartition(feature_distance, take - 1)[:take] if take < count else np.arange(count)
    axes = tuple(axis for axis in range(3) if axis != int(family.plane_axis))
    ranked: list[MatchResult] = []
    for index in indices:
        cells: list[Cell] = []
        for first, second in family.cells[int(index)]:
            value = [0, 0, 0]
            value[axes[0]] = int(first)
            value[axes[1]] = int(second)
            cells.append(tuple(value))  # type: ignore[arg-type]
        distance, transform = recognition_distance(cells, target)
        pose = Pose(
            tuple(
                -1 if int(state) == 2 else int(state)
                for state in family.states[int(index)]
            ),
            family.roll,
            base=int(family.base),
        )
        ranked.append(MatchResult(pose, tuple(cells), distance, "family", transform))
    ranked.sort(key=lambda item: item.distance)
    unique: dict[frozenset[Cell], MatchResult] = {}
    for result in ranked:
        unique.setdefault(frozenset(result.cells), result)
        if len(unique) >= k:
            break
    return list(unique.values())


def match(
    target: PixelTarget,
    roll: str,
    *,
    k: int = 5,
    family: Iterable[tuple[Pose, Sequence[Cell]]] | Any | None = None,
    beam_width: int = 1200,
    seed: int = 0,
) -> list[MatchResult]:
    """Return distinct roll-compatible flat paths nearest to ``target``."""

    found: list[MatchResult] = []
    if len(target.cells) == 27:
        try:
            from .config import load_machine
            from .solver import solve

            solved = solve(
                target.cells, roll, all_solutions=True, budget_nodes=250_000, tether=load_machine().has_tether
            )
            for pose in solved.poses[:k]:
                from .lattice import fk

                cells, _ = fk(pose.states, roll, base=pose.base)
                distance, transform = recognition_distance(cells, target)
                found.append(MatchResult(pose, tuple(cells), distance, "exact", transform))
        except (ImportError, AttributeError):
            pass
    if family is not None:
        if all(hasattr(family, name) for name in ("states", "cells", "plane_axis", "widths", "heights")):
            found.extend(_compact_family_match(target, family, k=k))
        else:
            for pose, cells in family:
                distance, transform = recognition_distance(cells, target)
                found.append(MatchResult(pose, tuple(cells), distance, "family", transform))
            found.sort(key=lambda result: result.distance)
            found = found[: max(k * 4, k)]
    if len(found) < k:
        found.extend(_beam_match(target, roll, k=k, beam_width=beam_width, seed=seed))

    unique: dict[frozenset[Cell], MatchResult] = {}
    for result in sorted(found, key=lambda item: item.distance):
        unique.setdefault(frozenset(result.cells), result)
    return list(unique.values())[:k]
