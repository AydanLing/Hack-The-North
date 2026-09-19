"""Convex collision solids for one CuBot module.

The normal runtime path loads :mod:`data/solids/module.json`, a conservative
support polytope generated from the current CAD.  The STL is deliberately not
a runtime dependency.  An analytic corner-chamfered cube remains available as
a deterministic fallback and for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from itertools import combinations, product
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_SOLID_PATH = PACKAGE_ROOT / "data" / "solids" / "module.json"
_WHEEL_SOLID_PATH = Path(__file__).resolve().parent / "_assets" / "data" / "solids" / "module.json"
DEFAULT_SOLID_PATH = _SOURCE_SOLID_PATH if _SOURCE_SOLID_PATH.is_file() else _WHEEL_SOLID_PATH
JOINT_AXIS = np.ones(3, dtype=float) / np.sqrt(3.0)


def _unit_rows(values: Iterable[Iterable[float]], *, atol: float = 1e-10) -> FloatArray:
    rows = np.asarray(tuple(tuple(row) for row in values), dtype=float).reshape((-1, 3))
    lengths = np.linalg.norm(rows, axis=1)
    if np.any(lengths <= atol):
        raise ValueError("solid direction vectors must be non-zero")
    return rows / lengths[:, None]


def _canonical_direction(value: FloatArray, *, digits: int = 10) -> tuple[float, float, float]:
    value = np.asarray(value, dtype=float)
    value = value / np.linalg.norm(value)
    first = next((component for component in value if abs(component) > 1e-10), 1.0)
    if first < 0:
        value = -value
    return tuple(float(x) for x in np.round(value, digits))


def _unique_directions(values: Iterable[Iterable[float]]) -> FloatArray:
    unique: dict[tuple[float, float, float], FloatArray] = {}
    for value in values:
        row = np.asarray(value, dtype=float)
        if np.linalg.norm(row) <= 1e-10:
            continue
        key = _canonical_direction(row)
        unique.setdefault(key, np.asarray(key, dtype=float))
    return np.asarray([unique[key] for key in sorted(unique)], dtype=float).reshape((-1, 3))


def _vertices_from_halfspaces(
    normals: FloatArray,
    offsets: FloatArray,
    *,
    tolerance: float = 1e-6,
) -> FloatArray:
    """Enumerate vertices of ``normals @ x <= offsets`` in three dimensions."""

    normals = np.asarray(normals, dtype=float)
    offsets = np.asarray(offsets, dtype=float)
    vertices: dict[tuple[float, float, float], FloatArray] = {}
    for indices in combinations(range(len(normals)), 3):
        matrix = normals[list(indices)]
        if abs(float(np.linalg.det(matrix))) < 1e-10:
            continue
        point = np.linalg.solve(matrix, offsets[list(indices)])
        if np.all(normals @ point <= offsets + tolerance):
            key = tuple(float(x) for x in np.round(point, 7))
            vertices.setdefault(key, point)
    if not vertices:
        raise ValueError("half-spaces do not enclose a non-empty 3D polytope")
    return np.asarray([vertices[key] for key in sorted(vertices)], dtype=float)


def _edges_from_active_planes(
    vertices: FloatArray,
    normals: FloatArray,
    offsets: FloatArray,
    *,
    tolerance: float = 2e-5,
) -> FloatArray:
    """Recover polytope edge directions from shared active face planes.

    A 3D polytope edge lies on at least two common supporting planes.  Collinear
    duplicates and antipodal directions are collapsed because SAT only needs
    one representative of each direction.
    """

    active = np.abs(vertices @ normals.T - offsets[None, :]) <= tolerance
    directions: list[FloatArray] = []
    for i, j in combinations(range(len(vertices)), 2):
        if int(np.count_nonzero(active[i] & active[j])) >= 2:
            directions.append(vertices[j] - vertices[i])
    return _unique_directions(directions)


@dataclass(frozen=True, slots=True)
class ConvexPiece:
    """A closed convex polytope in module-local millimetres."""

    name: str
    vertices: FloatArray
    face_normals: FloatArray
    edge_directions: FloatArray

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices, dtype=float).reshape((-1, 3))
        normals = _unit_rows(self.face_normals)
        edges = _unit_rows(self.edge_directions) if len(self.edge_directions) else np.empty((0, 3))
        if len(vertices) < 4 or np.linalg.matrix_rank(vertices - vertices.mean(axis=0)) < 3:
            raise ValueError(f"{self.name!r} is not a full-dimensional convex piece")
        vertices.setflags(write=False)
        normals.setflags(write=False)
        edges.setflags(write=False)
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "face_normals", normals)
        object.__setattr__(self, "edge_directions", edges)

    @property
    def radius_mm(self) -> float:
        return float(np.linalg.norm(self.vertices, axis=1).max())

    @property
    def bounds_mm(self) -> tuple[FloatArray, FloatArray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)


@dataclass(frozen=True, slots=True)
class ModuleSolid:
    """The two hinge halves and their convex rest envelope."""

    moving: ConvexPiece
    still: ConvexPiece
    full: ConvexPiece
    joint_axis: FloatArray
    r111_mm: float
    source_hash: str
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        axis = np.asarray(self.joint_axis, dtype=float).reshape(3)
        axis = axis / np.linalg.norm(axis)
        axis.setflags(write=False)
        object.__setattr__(self, "joint_axis", axis)

    @property
    def bounding_radius_mm(self) -> float:
        return max(self.moving.radius_mm, self.still.radius_mm, self.full.radius_mm)


def _piece_from_record(name: str, record: dict[str, Any]) -> ConvexPiece:
    return ConvexPiece(
        name=name,
        vertices=np.asarray(record["vertices_mm"], dtype=float),
        face_normals=np.asarray(record["face_normals"], dtype=float),
        edge_directions=np.asarray(record["edge_directions"], dtype=float),
    )


def load_module_solid(path: str | Path | None = None, *, fallback: bool = False) -> ModuleSolid:
    """Load committed CAD-derived data, optionally falling back analytically."""

    source = Path(path) if path is not None else DEFAULT_SOLID_PATH
    try:
        raw = json.loads(source.read_text())
        if raw.get("schema") != 1:
            raise ValueError(f"unsupported module solid schema {raw.get('schema')!r}")
        pieces = raw["pieces"]
        return ModuleSolid(
            moving=_piece_from_record("moving", pieces["moving"]),
            still=_piece_from_record("still", pieces["still"]),
            full=_piece_from_record("full", pieces["full"]),
            joint_axis=np.asarray(raw["joint_axis"], dtype=float),
            r111_mm=float(raw["r111_mm"]),
            source_hash=str(raw["source"]["sha256"]),
            provenance=dict(raw),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        if not fallback:
            raise
        return analytic_module_solid()


def solid_geometry_hash(solid: ModuleSolid | None = None) -> str:
    """Hash the exact runtime collision geometry, not only its CAD label."""

    value = MODULE_SOLID if solid is None else solid
    digest = hashlib.sha256()
    digest.update(value.source_hash.encode())
    for piece in (value.full, value.still, value.moving):
        digest.update(piece.name.encode())
        digest.update(np.ascontiguousarray(piece.vertices).tobytes())
        digest.update(np.ascontiguousarray(piece.face_normals).tobytes())
        digest.update(np.ascontiguousarray(piece.edge_directions).tobytes())
    return digest.hexdigest()


def _corner_chamfer_halfspaces(side_mm: float, chamfer_mm: float) -> tuple[FloatArray, FloatArray]:
    half = side_mm / 2.0
    normals: list[tuple[float, float, float]] = []
    offsets: list[float] = []
    for axis in range(3):
        for sign in (-1.0, 1.0):
            normal = [0.0, 0.0, 0.0]
            normal[axis] = sign
            normals.append(tuple(normal))
            offsets.append(half)
    diagonal_offset = 3.0 * half - chamfer_mm
    for signs in product((-1.0, 1.0), repeat=3):
        normals.append(signs)
        offsets.append(diagonal_offset)
    return _unit_rows(normals), np.asarray(offsets, dtype=float) / np.linalg.norm(np.asarray(normals), axis=1)


def _piece_from_halfspaces(name: str, normals: FloatArray, offsets: FloatArray) -> ConvexPiece:
    vertices = _vertices_from_halfspaces(normals, offsets)
    return ConvexPiece(name, vertices, _unique_directions(normals), _edges_from_active_planes(vertices, normals, offsets))


def analytic_module_solid(side_mm: float = 80.0, chamfer_mm: float = 8.0) -> ModuleSolid:
    """Return a corner-chamfered cube split by the body-diagonal hinge plane."""

    full_normals, full_offsets = _corner_chamfer_halfspaces(side_mm, chamfer_mm)
    moving_normals = np.vstack((full_normals, -JOINT_AXIS))
    moving_offsets = np.append(full_offsets, 0.0)
    still_normals = np.vstack((full_normals, JOINT_AXIS))
    still_offsets = np.append(full_offsets, 0.0)
    moving = _piece_from_halfspaces("moving-fallback", moving_normals, moving_offsets)
    still = _piece_from_halfspaces("still-fallback", still_normals, still_offsets)
    full = _piece_from_halfspaces("full-fallback", full_normals, full_offsets)
    axial = moving.vertices @ JOINT_AXIS
    radial = moving.vertices - axial[:, None] * JOINT_AXIS
    return ModuleSolid(
        moving=moving,
        still=still,
        full=full,
        joint_axis=JOINT_AXIS,
        r111_mm=float(np.linalg.norm(radial, axis=1).max()),
        source_hash="analytic-corner-chamfer",
        provenance={"source": "analytic", "side_mm": side_mm, "chamfer_mm": chamfer_mm},
    )


MODULE_SOLID = load_module_solid()


def tether_piece(side_mm: float = 80.0, length_mm: float = 40.0, width_mm: float = 20.0, facets: int = 4) -> ConvexPiece:
    """Rigid keep-out for the cable bundle leaving module 0 through its mount face.

    Module-local millimetres.  The piece is a convex ``facets``-gon prism of
    ``width_mm`` across flats, running from the ``-x`` face plane
    (``x = -side/2``, where a preceding module would mount) outward to
    ``x = -side/2 - length``, centred on the face.  ``facets=4`` is a square
    box of side ``width_mm`` (the shipped ``machine.toml`` model); ``facets=8``
    approximates a round bundle (the 3-D shell campaign's Ø20 × 40 mm model).
    It rides with module 0's still half and nothing may sweep through it,
    rest in the lattice cell it occupies, or drive it into the table.
    """

    if length_mm <= 0.0 or width_mm <= 0.0:
        raise ValueError("tether needs positive length and width")
    if facets < 3:
        raise ValueError("tether needs at least 3 facets")
    half = side_mm / 2.0
    normals: list[tuple[float, float, float]] = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)]
    offsets: list[float] = [-half, half + length_mm]
    for index in range(facets):
        angle = 2.0 * np.pi * index / facets
        normals.append((0.0, float(np.cos(angle)), float(np.sin(angle))))
        offsets.append(width_mm / 2.0)
    return _piece_from_halfspaces("tether", _unit_rows(normals), np.asarray(offsets, dtype=float))


TETHER_PIECE = tether_piece(facets=8)  # the 3-D campaign's Ø20 × 40 mm bundle; the engine uses machine.tether_* instead
TETHER_MODULE = -1  # module id the tether carries in collision / ground reports


__all__ = [
    "ConvexPiece",
    "DEFAULT_SOLID_PATH",
    "JOINT_AXIS",
    "TETHER_MODULE",
    "TETHER_PIECE",
    "tether_piece",
    "MODULE_SOLID",
    "ModuleSolid",
    "analytic_module_solid",
    "load_module_solid",
    "solid_geometry_hash",
]
