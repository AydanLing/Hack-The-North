#!/usr/bin/env python3
"""Build the committed conservative module solid from the current top STL.

The emitted JSON contains only convex polytope data and provenance; the runtime
never opens the CAD file.  Plane support distances are rounded *up* to 0.01 mm,
so serialisation cannot shrink the printed part.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.solid import (  # noqa: E402
    JOINT_AXIS,
    _edges_from_active_planes,
    _unique_directions,
    _vertices_from_halfspaces,
)

DEFAULT_OUTPUT = ROOT / "data" / "solids" / "module.json"


def read_stl(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) >= 84:
        triangles = struct.unpack_from("<I", data, 80)[0]
        if 84 + triangles * 50 == len(data):
            values = np.empty((triangles * 3, 3), dtype=float)
            for triangle in range(triangles):
                offset = 84 + triangle * 50 + 12
                for vertex in range(3):
                    values[triangle * 3 + vertex] = struct.unpack_from("<fff", data, offset + vertex * 12)
            return values
    vertices: list[tuple[float, float, float]] = []
    for line in data.decode("ascii").splitlines():
        words = line.strip().split()
        if len(words) == 4 and words[0].lower() == "vertex":
            vertices.append(tuple(float(word) for word in words[1:]))
    if not vertices:
        raise ValueError(f"{path} is not a supported binary or ASCII STL")
    return np.asarray(vertices, dtype=float)


def support_directions() -> np.ndarray:
    values: list[list[float]] = []
    for axis in range(3):
        for sign in (-1.0, 1.0):
            value = [0.0, 0.0, 0.0]
            value[axis] = sign
            values.append(value)
    root2 = math.sqrt(2.0)
    for first in range(3):
        for second in range(first + 1, 3):
            for a in (-1.0, 1.0):
                for b in (-1.0, 1.0):
                    value = [0.0, 0.0, 0.0]
                    value[first], value[second] = a / root2, b / root2
                    values.append(value)
    root3 = math.sqrt(3.0)
    for a in (-1.0, 1.0):
        for b in (-1.0, 1.0):
            for c in (-1.0, 1.0):
                values.append([a / root3, b / root3, c / root3])
    return np.asarray(values, dtype=float)


def c3_orbit_max(directions: np.ndarray, support: np.ndarray) -> np.ndarray:
    """Make support exactly symmetric under x→y→z using a superset operation."""

    def rotate(value: np.ndarray) -> np.ndarray:
        return value[[2, 0, 1]]

    output = support.copy()
    for index, direction in enumerate(directions):
        orbit = [index]
        current = rotate(direction)
        for _ in range(2):
            matches = np.flatnonzero(np.linalg.norm(directions - current, axis=1) < 1e-9)
            if not len(matches):
                raise ValueError("support direction set is not C3-closed")
            orbit.append(int(matches[0]))
            current = rotate(current)
        output[index] = max(support[item] for item in orbit)
    return np.ceil(output * 100.0 - 1e-10) / 100.0


def make_piece(name: str, directions: np.ndarray, support: np.ndarray) -> dict[str, object]:
    vertices = _vertices_from_halfspaces(directions, support)
    edges = _edges_from_active_planes(vertices, directions, support)
    return {
        "name": name,
        "vertices_mm": np.round(vertices, 6).tolist(),
        "face_normals": np.round(_unique_directions(directions), 10).tolist(),
        "edge_directions": np.round(edges, 10).tolist(),
        "bounding_radius_mm": round(float(np.linalg.norm(vertices, axis=1).max()), 6),
    }


def build(cad_path: Path) -> dict[str, object]:
    data = cad_path.read_bytes()
    points = read_stl(cad_path)
    lower, upper = points.min(axis=0), points.max(axis=0)
    if not np.allclose(lower, -40.0, atol=0.02) or not np.allclose(upper, 40.0, atol=0.02):
        raise ValueError(f"CAD frame gate failed: bbox {lower.tolist()} .. {upper.tolist()}, expected ±40 mm")
    axial = points @ JOINT_AXIS
    if axial.min() < -0.01 or abs(float(axial.max()) - 40.0 * math.sqrt(3.0)) > 0.05:
        raise ValueError(f"CAD split-axis gate failed: t={axial.min():.4f}..{axial.max():.4f} mm")
    radial = points - axial[:, None] * JOINT_AXIS
    r111 = float(np.linalg.norm(radial, axis=1).max())
    if abs(r111 - 58.7878) > 0.05:
        raise ValueError(f"CAD sweep-radius gate failed: r111={r111:.6f} mm")

    directions = support_directions()
    moving_support = c3_orbit_max(directions, np.max(points @ directions.T, axis=0))
    still_points = -points
    still_support = c3_orbit_max(directions, np.max(still_points @ directions.T, axis=0))
    full_points = np.vstack((points, still_points))
    full_support = c3_orbit_max(directions, np.max(full_points @ directions.T, axis=0))
    if np.max(points @ directions.T - moving_support[None, :]) > 1e-8:
        raise AssertionError("rounded moving polytope is not a CAD superset")

    return {
        "schema": 1,
        "source": {
            "filename": cad_path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "note": "generation-time input only; runtime is CAD-independent",
        },
        "method": "26-direction support polytope, C3 orbit-max, supports rounded upward to 0.01 mm",
        "bbox_mm": [np.round(lower, 6).tolist(), np.round(upper, 6).tolist()],
        "joint_axis": np.round(JOINT_AXIS, 12).tolist(),
        "r111_mm": round(r111, 6),
        "pieces": {
            "moving": make_piece("moving-cad", directions, moving_support),
            "still": make_piece("still-cad", directions, still_support),
            "full": make_piece("full-cad-envelope", directions, full_support),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cad", type=Path, help="path to the top-half STL")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = build(args.cad)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.output}")
    print(f"sha256 {record['source']['sha256']}")
    print(f"bbox {record['bbox_mm']}  r111 {record['r111_mm']:.6f} mm")


if __name__ == "__main__":
    main()
