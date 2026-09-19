"""Analytic gravity and holding-load checks for free CuBot folds."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Iterator

import numpy as np
from numpy.typing import NDArray

from .config import Machine, Profile
from .geometry import DETENT_RAD, pose_frames, rotation_about_axis
from .records import CheckReport, Pose, Side
from .solid import JOINT_AXIS

FloatArray = NDArray[np.float64]
G_M_S2 = 9.81


@dataclass(frozen=True, slots=True)
class SideChoice:
    side: Side
    moment_in_nm: float
    moment_out_nm: float
    ambiguous: bool
    ratio: float

    def __iter__(self) -> Iterator[object]:
        """Allow the compact ``side, in_m, out_m, ambiguous = choice`` idiom."""

        yield self.side
        yield self.moment_in_nm
        yield self.moment_out_nm
        yield self.ambiguous


@dataclass(frozen=True, slots=True)
class MomentReport:
    joint: int
    delta: int
    side: Side
    moving_modules: tuple[int, ...]
    moment_in_nm: float
    moment_out_nm: float
    ambiguous: bool
    ambiguity_ratio: float
    sample_angles_deg: tuple[float, ...]
    static_profile_nm: tuple[float, ...]
    static_peak_nm: float
    peak_angle_deg: float
    inertia_kgm2: float
    inertial_peak_nm: float
    peak_demand_nm: float
    holding_peak_nm: float
    holding_joint: int | None
    arc: str
    duration_s: float


def _side_indices(modules: int, joint: int, side: Side) -> np.ndarray:
    # The hinge module's halves have centroids on the joint axis and contribute
    # no gravity moment in this model.
    return np.arange(0, joint) if side == "in" else np.arange(joint + 1, modules)


def _gravity_moment(
    centers_mm: FloatArray,
    pivot_mm: FloatArray,
    axis: FloatArray,
    indices: np.ndarray,
    mass_kg: float,
) -> float:
    if not len(indices):
        return 0.0
    radii_m = (centers_mm[indices] - pivot_mm) / 1000.0
    force = np.asarray((0.0, 0.0, -mass_kg * G_M_S2))
    return float(np.sum(np.cross(radii_m, force) @ axis))


def moving_side(
    pose: Pose,
    joint: int,
    machine: Machine,
    ambiguity_ratio: float = 0.85,
) -> SideChoice:
    """Choose the side with the smaller initial gravity moment.

    ``in`` is modules before the hinge and ``out`` is modules after it.  When
    both moments vanish, the shorter side is chosen but marked ambiguous.
    """

    if not 0 <= joint < machine.joints:
        raise ValueError("joint must be in 0..25")
    centers, rotations = pose_frames(pose, machine)
    pivot = centers[joint]
    axis = rotations[joint] @ JOINT_AXIS
    incoming = abs(
        _gravity_moment(centers, pivot, axis, _side_indices(machine.modules, joint, "in"), machine.mass_kg)
    )
    outgoing = abs(
        _gravity_moment(centers, pivot, axis, _side_indices(machine.modules, joint, "out"), machine.mass_kg)
    )
    largest = max(incoming, outgoing)
    if largest < 1e-10:
        side: Side = "in" if joint <= machine.modules - joint - 1 else "out"
        return SideChoice(side, incoming, outgoing, True, 1.0)
    ratio = min(incoming, outgoing) / largest
    side = "in" if incoming < outgoing else "out"
    return SideChoice(side, incoming, outgoing, ratio >= ambiguity_ratio, ratio)


def inertia_about_axis(
    centers_mm: FloatArray,
    pivot_mm: FloatArray,
    axis: FloatArray,
    indices: np.ndarray,
    mass_kg: float,
    side_mm: float,
) -> float:
    """Point-mass parallel-axis term plus each cube's isotropic own inertia."""

    if not len(indices):
        return 0.0
    radii = (centers_mm[indices] - pivot_mm) / 1000.0
    perpendicular = radii - np.outer(radii @ axis, axis)
    own = mass_kg * (side_mm / 1000.0) ** 2 / 6.0
    return float(mass_kg * np.sum(perpendicular * perpendicular) + own * len(indices))


def holding_loads(
    centers_mm: FloatArray,
    axes: FloatArray,
    mass_kg: float,
    *,
    side_mm: float = 80.0,
    ground_tol_mm: float = 5.0,
) -> FloatArray:
    """Moment every non-moving joint must hold over one or more samples.

    A grounded cube supports itself.  A side with no ground support loads the
    separating joint as a cantilever; if both sides have support, the smaller
    residual air-side moment is a conservative bridge load.
    """

    centers = np.asarray(centers_mm, dtype=float)
    joint_axes = np.asarray(axes, dtype=float)
    if centers.ndim == 2:
        centers = centers[None, ...]
    if joint_axes.ndim == 2:
        joint_axes = joint_axes[None, ...]
    if centers.ndim != 3 or centers.shape[2] != 3:
        raise ValueError("centers_mm must have shape (samples, modules, 3)")
    if joint_axes.shape != (centers.shape[0], centers.shape[1] - 1, 3):
        raise ValueError("axes must have shape (samples, modules-1, 3)")
    _, modules, _ = centers.shape
    joints = modules - 1
    grounded = centers[:, :, 2] <= side_mm / 2.0 + ground_tol_mm
    force = np.asarray((0.0, 0.0, -mass_kg * G_M_S2))

    # Shape (samples, joints, modules, xyz): every module radius about every
    # separating joint.  A nested loop here would dominate analytic checking;
    # this is a regular prefix/suffix reduction.
    pivots = centers[:, :joints, None, :]
    radii_m = (centers[:, None, :, :] - pivots) / 1000.0
    torque_vectors = np.cross(radii_m, force)
    signed = np.einsum("sjmi,sji->sjm", torque_vectors, joint_axes)
    signed = np.where(grounded[:, None, :], 0.0, signed)
    prefix = np.cumsum(signed, axis=2)
    total = prefix[:, :, -1]
    indices = np.arange(joints)
    parent = np.where(indices[None, :] > 0, prefix[:, indices, np.maximum(indices - 1, 0)], 0.0)
    child = total - prefix[:, indices, indices]
    parent_moment = np.abs(parent)
    child_moment = np.abs(child)

    grounded_prefix = np.maximum.accumulate(grounded, axis=1)
    grounded_suffix = np.maximum.accumulate(grounded[:, ::-1], axis=1)[:, ::-1]
    parent_ground = np.ones((len(centers), joints), dtype=bool)
    child_ground = np.ones((len(centers), joints), dtype=bool)
    if joints > 1:
        parent_ground[:, 1:] = grounded_prefix[:, : joints - 1]
        child_ground[:, :-1] = grounded_suffix[:, 1:joints]
    return np.where(
        ~parent_ground,
        parent_moment,
        np.where(~child_ground, child_moment, np.minimum(parent_moment, child_moment)),
    )


def _classify_arc(height_change_mm: FloatArray, tolerance_mm: float = 1e-6) -> str:
    if height_change_mm.size == 0:
        return "flat"
    upward = bool(height_change_mm.max() > tolerance_mm)
    downward = bool(height_change_mm.min() < -tolerance_mm)
    end_flat = bool(abs(float(height_change_mm[-1].mean())) <= tolerance_mm)
    if not upward and not downward:
        return "flat"
    if upward and downward:
        return "mixed"
    if end_flat:
        return "hump" if upward else "dip"
    return "up" if upward else "down"


def move_moment(
    pose: Pose,
    joint: int,
    delta: int,
    side: Side,
    machine: Machine | float | None = None,
    mass: float | None = None,
    samples: int = 31,
    *,
    pitch: float | None = None,
    duration_s: float | None = None,
    ambiguity_ratio: float = 0.85,
) -> MomentReport:
    """Sample the real moving-side centre-of-mass torque along one detent.

    For compatibility with the design API, the fifth positional argument may
    be either a :class:`Machine` or a pitch in millimetres followed by ``mass``.
    """

    if delta not in (-1, 1):
        raise ValueError("delta must be one signed detent")
    if isinstance(machine, Machine):
        config = machine
        pitch_mm = config.pitch_mm if pitch is None else float(pitch)
        mass_kg = config.mass_kg if mass is None else float(mass)
        side_mm = config.side_mm
        move_time = config.move_time_s if duration_s is None else float(duration_s)
    else:
        from .config import load_machine

        default = load_machine()
        pitch_mm = float(machine) if machine is not None else (default.pitch_mm if pitch is None else float(pitch))
        mass_kg = default.mass_kg if mass is None else float(mass)
        side_mm = default.side_mm
        move_time = default.move_time_s if duration_s is None else float(duration_s)
        config = Machine(
            modules=default.modules,
            side_mm=side_mm,
            gap_mm=pitch_mm - side_mm,
            chamfer_mm=default.chamfer_mm,
            roll=pose.roll,
            mass_kg=mass_kg,
            stall_torque_nm=default.stall_torque_nm,
            move_time_s=move_time,
        )
    if samples < 2:
        raise ValueError("samples must be at least 2")
    centers, rotations = pose_frames(pose, config)
    pivot = centers[joint]
    axis = rotations[joint] @ JOINT_AXIS
    indices = _side_indices(config.modules, joint, side)
    choice = moving_side(pose, joint, config, ambiguity_ratio)
    inertia = inertia_about_axis(centers, pivot, axis, indices, mass_kg, side_mm)
    angles = np.linspace(0.0, DETENT_RAD, int(samples))
    world_sign = delta if side == "out" else -delta
    initial_centers = centers[indices].copy()
    height_changes: list[FloatArray] = []
    sampled_centers: list[FloatArray] = []
    sampled_axes: list[FloatArray] = []
    static: list[float] = []
    axes_zero = np.asarray([rotations[index] @ JOINT_AXIS for index in range(config.joints)])
    for angle in angles:
        world_rotation = rotation_about_axis(axis, world_sign * float(angle))
        current = centers.copy()
        current[indices] = (initial_centers - pivot) @ world_rotation.T + pivot
        sampled_centers.append(current)
        current_axes = axes_zero.copy()
        moving_joints = np.arange(0, joint) if side == "in" else np.arange(joint + 1, config.joints)
        if len(moving_joints):
            current_axes[moving_joints] = current_axes[moving_joints] @ world_rotation.T
        sampled_axes.append(current_axes)
        gravity = _gravity_moment(current, pivot, axis, indices, mass_kg)
        # Supply torque along the chosen direction of motion.
        static.append(-world_sign * gravity)
        height_changes.append(current[indices, 2] - initial_centers[:, 2])
    static_array = np.asarray(static)
    absolute_static = np.abs(static_array)
    peak_index = int(np.argmax(absolute_static))

    # Cosine-eased move: interpolate sampled static torque onto uniform time.
    time = np.linspace(0.0, move_time, int(samples))
    progress = 0.5 * DETENT_RAD * (1.0 - np.cos(np.pi * time / move_time))
    static_time = np.interp(progress, angles, static_array)
    alpha_peak = DETENT_RAD * math.pi**2 / (2.0 * move_time**2)
    alpha = alpha_peak * np.cos(np.pi * time / move_time)
    demand = np.abs(static_time + inertia * alpha)

    holds = holding_loads(
        np.asarray(sampled_centers),
        np.asarray(sampled_axes),
        mass_kg,
        side_mm=side_mm,
    )
    holds[:, joint] = 0.0
    holding_joint = int(np.argmax(holds.max(axis=0))) if holds.size else None
    holding_peak = float(holds[:, holding_joint].max()) if holding_joint is not None else 0.0
    height_array = np.asarray(height_changes)
    return MomentReport(
        joint=joint,
        delta=delta,
        side=side,
        moving_modules=tuple(int(index) for index in indices),
        moment_in_nm=choice.moment_in_nm,
        moment_out_nm=choice.moment_out_nm,
        ambiguous=choice.ambiguous,
        ambiguity_ratio=choice.ratio,
        sample_angles_deg=tuple(float(math.degrees(value)) for value in angles),
        static_profile_nm=tuple(float(value) for value in static_array),
        static_peak_nm=float(absolute_static[peak_index]),
        peak_angle_deg=float(math.degrees(angles[peak_index])),
        inertia_kgm2=inertia,
        inertial_peak_nm=float(inertia * alpha_peak),
        peak_demand_nm=float(demand.max()),
        holding_peak_nm=holding_peak,
        holding_joint=holding_joint,
        arc=_classify_arc(height_array),
        duration_s=move_time,
    )


def _band_score(value: float, good: float, bad: float) -> float:
    if value <= good:
        return 1.0
    if bad <= good:
        return 0.0
    return max(0.0, min(1.0, (bad - value) / (bad - good)))


def score(report: MomentReport, profile: Profile) -> CheckReport:
    """Score torque, holding load, and moving-side ambiguity."""

    # Static peak is the conservative stall gate: even when the eased inertial
    # term happens to cancel gravity at one instant, the drive must still be
    # able to hold/brake the same configuration.
    torque_ok = report.static_peak_nm <= profile.torque_stall_nm + 1e-9
    torque_reason = (
        f"peak static torque {report.static_peak_nm:.3f} N·m "
        f"(eased demand {report.peak_demand_nm:.3f}) "
        f"(cap {profile.torque_cap_nm:.3f}, stall {profile.torque_stall_nm:.3f})"
    )
    ambiguity_score = (
        1.0
        if report.ambiguity_ratio < profile.side_ambiguity_ratio
        else _band_score(report.ambiguity_ratio, profile.side_ambiguity_ratio, 1.0)
    )
    return CheckReport(
        hard={"torque_stall": (torque_ok, torque_reason)},
        soft={
            "torque": (
                _band_score(report.peak_demand_nm, profile.torque_cap_nm, profile.torque_stall_nm),
                f"peak demand including inertia {report.peak_demand_nm:.3f} N·m",
            ),
            "holding_load": (
                _band_score(report.holding_peak_nm, 0.0, profile.torque_stall_nm),
                f"peak holding load {report.holding_peak_nm:.3f} N·m"
                + (f" at joint {report.holding_joint}" if report.holding_joint is not None else ""),
            ),
            "moving_side": (
                ambiguity_score,
                f"side moment ratio {report.ambiguity_ratio:.3f}; selected {report.side}",
            ),
        },
        measurements={
            "static_peak_nm": report.static_peak_nm,
            "peak_demand_nm": report.peak_demand_nm,
            "peak_angle_deg": report.peak_angle_deg,
            "inertia_kgm2": report.inertia_kgm2,
            "holding_peak_nm": report.holding_peak_nm,
            "moving_side": report.side,
            "side_ambiguous": report.ambiguous,
            "arc": report.arc,
        },
    )


def hump_moment(n: int, mass_kg: float = 0.223, pitch_mm: float = 82.0) -> float:
    """Closed-form straight-side body-diagonal hump moment in N·m."""

    if n < 0:
        raise ValueError("n must be non-negative")
    return n * (n + 1) * mass_kg * G_M_S2 * (pitch_mm / 1000.0) / (2.0 * math.sqrt(3.0))


__all__ = [
    "G_M_S2",
    "MomentReport",
    "SideChoice",
    "holding_loads",
    "hump_moment",
    "inertia_about_axis",
    "move_moment",
    "moving_side",
    "score",
]
