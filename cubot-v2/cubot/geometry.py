"""Continuous pre-simulation geometry for CuBot moves.

All dimensions are millimetres.  Resting kinematics stay integer elsewhere;
this module is the deliberate floating-point boundary for sampled joint sweeps,
convex SAT penetration, and table clearance.
"""

from __future__ import annotations

import functools

from dataclasses import dataclass, field
import math
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

from .config import Machine, Profile
from .records import CheckReport, Move, Pose, Side
from .solid import ConvexPiece, JOINT_AXIS, MODULE_SOLID, ModuleSolid

FloatArray = NDArray[np.float64]
DETENT_RAD = 2.0 * math.pi / 3.0


@dataclass(frozen=True, slots=True)
class Transform:
    rotation: FloatArray
    translation: FloatArray

    def __post_init__(self) -> None:
        rotation = np.asarray(self.rotation, dtype=float).reshape((3, 3))
        translation = np.asarray(self.translation, dtype=float).reshape(3)
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)

    @classmethod
    def identity(cls, translation: Iterable[float] = (0.0, 0.0, 0.0)) -> "Transform":
        return cls(np.eye(3), np.asarray(tuple(translation), dtype=float))


@dataclass(frozen=True, slots=True)
class CollisionHit:
    pair: tuple[int, int]
    pieces: tuple[str, str]
    angle_deg: float
    depth_mm: float


@dataclass(frozen=True, slots=True)
class GroundHit:
    module: int
    angle_deg: float
    depth_mm: float
    pivot_piece: bool = False


@dataclass(slots=True)
class SweepReport:
    joint: int
    delta: int
    side: Side
    sampled_angles_deg: list[float]
    collisions: list[CollisionHit] = field(default_factory=list)
    ground: list[GroundHit] = field(default_factory=list)
    max_depth_mm: float = 0.0
    max_pair: tuple[int, int] | None = None
    first_contact_angle_deg: float | None = None
    max_ground_depth_mm: float = 0.0
    max_pivot_dip_mm: float = 0.0

    @property
    def samples(self) -> int:
        return len(self.sampled_angles_deg)


@dataclass(frozen=True, slots=True)
class _Prepared:
    vertices: FloatArray
    face_normals: FloatArray
    edge_directions: FloatArray
    center: FloatArray
    radius_mm: float


@dataclass(frozen=True, slots=True)
class _PlacedPiece:
    module: int
    kind: str
    piece: ConvexPiece
    transform: Transform
    pivot_piece: bool = False


def rotation_about_axis(axis: Iterable[float], angle_rad: float) -> FloatArray:
    axis_array = np.asarray(tuple(axis), dtype=float)
    axis_array /= np.linalg.norm(axis_array)
    x, y, z = axis_array
    c, s, t = math.cos(angle_rad), math.sin(angle_rad), 1.0 - math.cos(angle_rad)
    return np.asarray(
        [
            [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
        ],
        dtype=float,
    )


def transform_points(piece: ConvexPiece, transform: Transform) -> FloatArray:
    return piece.vertices @ transform.rotation.T + transform.translation


def _prepare(piece: ConvexPiece, transform: Transform) -> _Prepared:
    return _Prepared(
        vertices=transform_points(piece, transform),
        face_normals=piece.face_normals @ transform.rotation.T,
        edge_directions=piece.edge_directions @ transform.rotation.T,
        center=transform.translation,
        radius_mm=piece.radius_mm,
    )


def _dedupe_axes(values: FloatArray) -> FloatArray:
    """Normalize and de-duplicate SAT axes in one vectorized pass."""

    axes = np.asarray(values, dtype=float).reshape((-1, 3))
    lengths = np.linalg.norm(axes, axis=1)
    axes = axes[lengths > 1e-9]
    if not len(axes):
        return np.empty((0, 3), dtype=float)
    axes = axes / np.linalg.norm(axes, axis=1)[:, None]
    nonzero = np.abs(axes) > 1e-9
    first_indices = np.argmax(nonzero, axis=1)
    signs = axes[np.arange(len(axes)), first_indices]
    axes = np.where((signs < 0.0)[:, None], -axes, axes)
    _, unique_indices = np.unique(np.round(axes, 9), axis=0, return_index=True)
    return axes[np.sort(unique_indices)]


def _overlap_prepared(first: _Prepared, second: _Prepared) -> float:
    center_distance = float(np.linalg.norm(first.center - second.center))
    if center_distance > first.radius_mm + second.radius_mm + 1e-9:
        return 0.0
    cross_axes = np.cross(
        first.edge_directions[:, None, :],
        second.edge_directions[None, :, :],
    ).reshape((-1, 3))
    axes = _dedupe_axes(
        np.vstack((first.face_normals, second.face_normals, cross_axes))
    )
    if not len(axes):
        return 0.0
    first_projection = first.vertices @ axes.T
    second_projection = second.vertices @ axes.T
    # This containment-safe form is the translation needed to separate the
    # intervals, not merely the length of their intersection.
    depths = np.minimum(
        first_projection.max(axis=0) - second_projection.min(axis=0),
        second_projection.max(axis=0) - first_projection.min(axis=0),
    )
    if np.any(depths <= 1e-8):
        return 0.0
    return float(depths.min())


def overlap_depth(
    first: ConvexPiece | ModuleSolid,
    first_transform: Transform,
    second: ConvexPiece | ModuleSolid,
    second_transform: Transform,
) -> float:
    """Return SAT penetration depth in mm, or zero when separated/touching."""

    first_piece = first.full if isinstance(first, ModuleSolid) else first
    second_piece = second.full if isinstance(second, ModuleSolid) else second
    return _overlap_prepared(_prepare(first_piece, first_transform), _prepare(second_piece, second_transform))


def ground_depth(
    piece: ConvexPiece | ModuleSolid,
    transform: Transform,
    *,
    table_z_mm: float = 0.0,
) -> float:
    """Depth in mm by which a convex body enters the table half-space."""

    body = piece.full if isinstance(piece, ModuleSolid) else piece
    minimum = float(transform_points(body, transform)[:, 2].min())
    return max(0.0, table_z_mm - minimum)


def _pose_frames(pose: Pose, machine: Machine) -> tuple[FloatArray, FloatArray]:
    from .lattice import continuous_frames

    angles = np.asarray(pose.states, dtype=float) * DETENT_RAD
    centers, rotations = continuous_frames(angles, pose.roll, machine.pitch_mm, pose.base)
    centers = np.asarray(centers, dtype=float)
    rotations = np.asarray(rotations, dtype=float)
    # Kinematics has no table.  Settle the complete rest envelope onto z=0;
    # subsequent motion keeps the physically static side fixed in that frame.
    minimum = min(
        float(transform_points(MODULE_SOLID.full, Transform(rotation, center))[:, 2].min())
        for center, rotation in zip(centers, rotations, strict=True)
    )
    centers = centers.copy()
    centers[:, 2] -= minimum
    return centers, rotations


def pose_frames(pose: Pose, machine: Machine) -> tuple[FloatArray, FloatArray]:
    """Public settled continuous frames used by geometry and load analysis."""

    return _pose_frames(pose, machine)


def _hull2(points: FloatArray) -> FloatArray:
    """Return a counter-clockwise monotone-chain hull."""

    unique = sorted({(float(point[0]), float(point[1])) for point in points})
    if len(unique) <= 1:
        return np.asarray(unique, dtype=float)

    def cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 1e-9:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 1e-9:
            upper.pop()
        upper.append(point)
    return np.asarray(lower[:-1] + upper[:-1], dtype=float)


def balance_margin(
    pose: Pose,
    machine: Machine,
    *,
    support_tolerance_mm: float = 0.5,
    solid: ModuleSolid = MODULE_SOLID,
) -> float:
    """Signed CoM margin to the convex table-support footprint in millimetres."""

    centers, rotations = _pose_frames(pose, machine)
    placed = [
        transform_points(solid.full, Transform(rotation, center))
        for center, rotation in zip(centers, rotations, strict=True)
    ]
    minimum = min(float(vertices[:, 2].min()) for vertices in placed)
    support_sets = [
        vertices[vertices[:, 2] <= minimum + support_tolerance_mm, :2]
        for vertices in placed
    ]
    support = np.concatenate([points for points in support_sets if len(points)], axis=0)
    hull = _hull2(support)
    if len(hull) < 3:
        return float("-inf")
    point = np.asarray(centers, dtype=float).mean(axis=0)[:2]
    margins: list[float] = []
    for index, start in enumerate(hull):
        end = hull[(index + 1) % len(hull)]
        edge = end - start
        length = float(np.linalg.norm(edge))
        if length > 1e-9:
            offset = point - start
            cross_z = float(edge[0] * offset[1] - edge[1] * offset[0])
            margins.append(cross_z / length)
    return min(margins, default=float("-inf"))


def score_balance(pose: Pose, machine: Machine, profile: Profile) -> CheckReport:
    """Report the configured balance preference as a soft score."""

    margin = balance_margin(pose, machine)
    desired = profile.balance_margin_mm
    lower = desired - machine.side_mm
    value = 0.0 if not np.isfinite(margin) else max(0.0, min(1.0, (margin - lower) / machine.side_mm))
    note = f"support margin {margin:.3f} mm (preferred {desired:.3f} mm)"
    return CheckReport(
        soft={"balance": (value, note)},
        measurements={"balance_margin_mm": margin},
    )


def advance_pose(pose: Pose, move: Move) -> Pose:
    """Apply a physical move, including root orientation for an ``in`` move.

    Joint states describe relative geometry, but the side choice determines
    which half stays fixed in the world.  When the base/in side moves, module
    zero rotates by the opposite world angle and the successor's ``base`` must
    record that cube-group orientation.  Omitting this update makes subsequent
    table and gravity checks use the wrong lying face.
    """

    from .lattice import ORIENTS, apply_detent, continuous_frames, orient_index

    states = apply_detent(pose.states, move.joint, move.delta)
    if move.side == "out":
        return Pose(states, pose.roll, pose.base, pose.lying)
    angles = np.asarray(pose.states, dtype=float) * DETENT_RAD
    _, rotations = continuous_frames(angles, pose.roll, 1.0, pose.base)
    axis = rotations[move.joint] @ JOINT_AXIS
    root_motion = rotation_about_axis(axis, -move.delta * DETENT_RAD)
    base = orient_index(np.rint(root_motion @ ORIENTS[pose.base]).astype(np.int8))
    return Pose(states, pose.roll, base, pose.lying)


def _rotate_positions(points: FloatArray, pivot: FloatArray, rotation: FloatArray) -> FloatArray:
    return (points - pivot) @ rotation.T + pivot


@functools.lru_cache(maxsize=8)
def _tether_piece(side_mm: float, length_mm: float, width_mm: float) -> ConvexPiece:
    from .solid import tether_piece

    return tether_piece(side_mm, length_mm, width_mm)


def tether_transform(pose: Pose, machine: Machine, *, base_frames: tuple[FloatArray, FloatArray] | None = None) -> Transform | None:
    """World placement of the tether keep-out at rest (module 0's still-half frame), or ``None``."""

    if not machine.has_tether:
        return None
    centers, rotations = base_frames if base_frames is not None else _pose_frames(pose, machine)
    return Transform(np.asarray(rotations[0], dtype=float), np.asarray(centers[0], dtype=float))


def tether_rest_depth(pose: Pose, machine: Machine) -> float:
    """Table incursion of the tether keep-out in the settled rest pose, mm."""

    transform = tether_transform(pose, machine)
    if transform is None:
        return 0.0
    piece = _tether_piece(machine.side_mm, machine.tether_length_mm, machine.tether_width_mm)
    return ground_depth(piece, transform)


def _sample_placements(
    pose: Pose,
    machine: Machine,
    joint: int,
    side: Side,
    progress_rad: float,
    *,
    solid: ModuleSolid,
    base_frames: tuple[FloatArray, FloatArray] | None = None,
) -> tuple[list[_PlacedPiece], list[_PlacedPiece]]:
    centers, rotations = base_frames if base_frames is not None else _pose_frames(pose, machine)
    centers = np.asarray(centers, dtype=float)
    rotations = np.asarray(rotations, dtype=float)
    pivot = centers[joint]
    axis = rotations[joint] @ solid.joint_axis
    start_angle = pose.states[joint] * DETENT_RAD
    start_moving_rotation = rotations[joint] @ rotation_about_axis(solid.joint_axis, start_angle)
    # The cable bundle is rigid with module 0's still half: static on ``out``
    # moves, swinging with the base side on ``in`` moves.  It shares module
    # index 0 so its designed contact with module 0 itself is not a collision.
    tether = (
        _tether_piece(machine.side_mm, machine.tether_length_mm, machine.tether_width_mm)
        if machine.has_tether
        else None
    )

    static: list[_PlacedPiece] = []
    moving: list[_PlacedPiece] = []
    if side == "out":
        world_rotation = rotation_about_axis(axis, progress_rad)
        for module in range(joint):
            static.append(_PlacedPiece(module, "full", solid.full, Transform(rotations[module], centers[module])))
        static.append(_PlacedPiece(joint, "still", solid.still, Transform(rotations[joint], pivot), True))
        if tether is not None:
            static.append(_PlacedPiece(0, "tether", tether, Transform(rotations[0], centers[0])))
        moving.append(
            _PlacedPiece(
                joint,
                "moving",
                solid.moving,
                Transform(world_rotation @ start_moving_rotation, pivot),
                True,
            )
        )
        if joint + 1 < len(centers):
            moved_centers = _rotate_positions(centers[joint + 1 :], pivot, world_rotation)
            for offset, center in enumerate(moved_centers, start=joint + 1):
                moving.append(
                    _PlacedPiece(offset, "full", solid.full, Transform(world_rotation @ rotations[offset], center))
                )
    else:
        world_rotation = rotation_about_axis(axis, -progress_rad)
        moving.append(
            _PlacedPiece(joint, "still", solid.still, Transform(world_rotation @ rotations[joint], pivot), True)
        )
        static.append(_PlacedPiece(joint, "moving", solid.moving, Transform(start_moving_rotation, pivot), True))
        if joint:
            moved_centers = _rotate_positions(centers[:joint], pivot, world_rotation)
            for module, center in enumerate(moved_centers):
                moving.append(
                    _PlacedPiece(module, "full", solid.full, Transform(world_rotation @ rotations[module], center))
                )
        if tether is not None:
            tether_center = _rotate_positions(centers[:1], pivot, world_rotation)[0]
            moving.append(_PlacedPiece(0, "tether", tether, Transform(world_rotation @ rotations[0], tether_center)))
        for module in range(joint + 1, len(centers)):
            static.append(_PlacedPiece(module, "full", solid.full, Transform(rotations[module], centers[module])))
    return static, moving


def _evaluate_sample(
    pose: Pose,
    move: Move,
    machine: Machine,
    angle_deg: float,
    solid: ModuleSolid,
    base_frames: tuple[FloatArray, FloatArray],
) -> tuple[list[CollisionHit], list[GroundHit]]:
    progress = math.radians(angle_deg) * move.delta
    static, moving = _sample_placements(
        pose,
        machine,
        move.joint,
        move.side,
        progress,
        solid=solid,
        base_frames=base_frames,
    )
    prepared_static = [(body, _prepare(body.piece, body.transform)) for body in static]
    collisions: list[CollisionHit] = []
    ground_hits: list[GroundHit] = []
    for mover in moving:
        prepared_mover = _prepare(mover.piece, mover.transform)
        for fixed, prepared_fixed in prepared_static:
            if mover.module == fixed.module:
                continue  # the designed interface between the hinge halves
            depth = _overlap_prepared(prepared_fixed, prepared_mover)
            if depth > 0.0:
                collisions.append(
                    CollisionHit(
                        pair=tuple(sorted((fixed.module, mover.module))),
                        pieces=(fixed.kind, mover.kind),
                        angle_deg=angle_deg,
                        depth_mm=depth,
                    )
                )
        depth = ground_depth(mover.piece, mover.transform)
        if depth > 0.0:
            ground_hits.append(GroundHit(mover.module, angle_deg, depth, mover.pivot_piece))
    return collisions, ground_hits


def sweep(
    pose: Pose,
    move: Move,
    machine: Machine,
    profile: Profile,
    *,
    solid: ModuleSolid = MODULE_SOLID,
) -> SweepReport:
    """Sample one signed detent and report collision/ground depths.

    A contact-bearing coarse interval is resampled at 1° resolution.  Both
    hinge halves participate, including their contacts with the two adjacent
    modules; this is essential for the closed-cube regression.
    """

    if pose.roll != machine.roll:
        # Alternate roll words are valid, but mismatches are nearly always an
        # accidental cache/config mix-up and must be made explicit by callers.
        machine = Machine(
            modules=machine.modules,
            side_mm=machine.side_mm,
            gap_mm=machine.gap_mm,
            chamfer_mm=machine.chamfer_mm,
            roll=pose.roll,
            mass_kg=machine.mass_kg,
            stall_torque_nm=machine.stall_torque_nm,
            move_time_s=machine.move_time_s,
        )
    base_frames = _pose_frames(pose, machine)
    coarse_step = float(profile.sweep_step_deg)
    coarse = np.linspace(0.0, 120.0, max(2, math.ceil(120.0 / coarse_step)) + 1)
    cache: dict[float, tuple[list[CollisionHit], list[GroundHit]]] = {}

    def evaluate(angle: float) -> tuple[list[CollisionHit], list[GroundHit]]:
        key = round(float(angle), 8)
        if key not in cache:
            cache[key] = _evaluate_sample(pose, move, machine, key, solid, base_frames)
        return cache[key]

    contact_indices: list[int] = []
    for index, angle in enumerate(coarse):
        collisions, _ = evaluate(float(angle))
        if collisions:
            contact_indices.append(index)
    refined: set[float] = set(float(x) for x in coarse)
    for index in contact_indices:
        lower = float(coarse[max(0, index - 1)])
        upper = float(coarse[min(len(coarse) - 1, index + 1)])
        point = lower
        while point <= upper + 1e-9:
            refined.add(round(point, 8))
            point += 1.0

    sampled = sorted(refined)
    all_collisions: list[CollisionHit] = []
    all_ground: list[GroundHit] = []
    for angle in sampled:
        collisions, ground_hits = evaluate(angle)
        all_collisions.extend(collisions)
        all_ground.extend(ground_hits)
    worst = max(all_collisions, key=lambda hit: hit.depth_mm, default=None)
    nonpivot = [hit for hit in all_ground if not hit.pivot_piece]
    pivot = [hit for hit in all_ground if hit.pivot_piece]
    return SweepReport(
        joint=move.joint,
        delta=move.delta,
        side=move.side,
        sampled_angles_deg=sampled,
        collisions=all_collisions,
        ground=all_ground,
        max_depth_mm=worst.depth_mm if worst else 0.0,
        max_pair=worst.pair if worst else None,
        first_contact_angle_deg=min((hit.angle_deg for hit in all_collisions), default=None),
        max_ground_depth_mm=max((hit.depth_mm for hit in nonpivot), default=0.0),
        max_pivot_dip_mm=max((hit.depth_mm for hit in pivot), default=0.0),
    )


def _band_score(value: float, good: float, bad: float) -> float:
    if value <= good:
        return 1.0
    if bad <= good:
        return 0.0
    return max(0.0, min(1.0, (bad - value) / (bad - good)))


def score_sweep(report: SweepReport, profile: Profile) -> CheckReport:
    """Translate raw geometric depths into configured hard/soft outcomes."""

    epsilon = 1e-6
    collision_ok = report.max_depth_mm <= profile.hard_penetration_mm + epsilon
    ground_ok = report.max_ground_depth_mm <= profile.ground_hard_mm + epsilon
    collision_reason = (
        f"max CAD penetration {report.max_depth_mm:.3f} mm"
        + (f" for modules {report.max_pair}" if report.max_pair else "")
        + f" (limit {profile.hard_penetration_mm:.3f} mm)"
    )
    ground_reason = (
        f"max non-pivot table incursion {report.max_ground_depth_mm:.3f} mm "
        f"(limit {profile.ground_hard_mm:.3f} mm)"
    )
    return CheckReport(
        hard={
            "cad_penetration": (collision_ok, collision_reason),
            "ground": (ground_ok, ground_reason),
        },
        soft={
            "near_contact": (
                _band_score(report.max_depth_mm, profile.soft_penetration_mm, profile.hard_penetration_mm),
                collision_reason,
            ),
            "ground": (
                _band_score(report.max_ground_depth_mm, profile.ground_soft_mm, profile.ground_hard_mm),
                ground_reason,
            ),
            "pivot_dip": (
                _band_score(report.max_pivot_dip_mm, profile.pivot_dip_exempt_mm, profile.ground_hard_mm),
                f"pivoting hinge half dips {report.max_pivot_dip_mm:.3f} mm",
            ),
        },
        measurements={
            "samples": report.samples,
            "max_penetration_mm": report.max_depth_mm,
            "max_ground_depth_mm": report.max_ground_depth_mm,
            "max_pivot_dip_mm": report.max_pivot_dip_mm,
            "first_contact_angle_deg": (
                report.first_contact_angle_deg if report.first_contact_angle_deg is not None else "none"
            ),
        },
    )


__all__ = [
    "CollisionHit",
    "GroundHit",
    "SweepReport",
    "Transform",
    "advance_pose",
    "balance_margin",
    "ground_depth",
    "overlap_depth",
    "pose_frames",
    "rotation_about_axis",
    "score_balance",
    "score_sweep",
    "sweep",
    "transform_points",
]
