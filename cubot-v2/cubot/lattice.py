"""Exact lattice kinematics for the body-diagonal CuBot chain.

The convention in this module:

* local ``+x`` is the outgoing chain direction at state zero;
* ``J`` is a positive 120 degree rotation about local ``(1, 1, 1)``;
* ``RX`` is a positive 90 degree assembly roll about local ``+x``; and
* orientation matrices map module-local column vectors into world vectors.

One naming trap is worth making explicit.  A ``base_rot`` is a *quarter-turn
count* about local x, not an index into :data:`ORIENTS`.  Use
:func:`base_rot_orientation` to translate it.  With the deterministic group
ordering below, ``base_rot == 2`` maps to orientation index 6, not index 2.
The heart golden stores its cells in the unrolled design frame; laying it down
therefore rotates those cells but does not change the shape.

Only the table construction uses matrix multiplication.  Discrete forward
kinematics is integer lookup and addition.  Floating point is confined to the
independent :func:`continuous_frames` cross-check used by geometry code.
"""

from __future__ import annotations

from dataclasses import replace
from math import cos, sin, sqrt
from typing import Iterable, Sequence

import numpy as np

from .records import Cell, Pose

Matrix = np.ndarray

I3 = np.eye(3, dtype=np.int8)
J = np.array(((0, 0, 1), (1, 0, 0), (0, 1, 0)), dtype=np.int8)
RX = np.array(((1, 0, 0), (0, 0, -1), (0, 1, 0)), dtype=np.int8)
for _generator in (I3, J, RX):
    _generator.setflags(write=False)


def _matrix_key(matrix: np.ndarray) -> tuple[int, ...]:
    array = np.asarray(matrix, dtype=np.int8)
    if array.shape != (3, 3):
        raise ValueError(f"orientation must be a 3x3 matrix, got {array.shape}")
    return tuple(int(value) for value in array.flat)


def group_closure(generators: Iterable[np.ndarray]) -> tuple[np.ndarray, ...]:
    """Return the deterministic right-multiplication closure of ``generators``.

    Breadth-first discovery from the identity gives a deterministic ordering.
    Orientation indices are persisted in records, so the ordering is part of
    the data contract rather than an implementation detail.
    """

    gens = tuple(np.asarray(generator, dtype=np.int8) for generator in generators)
    for generator in gens:
        if generator.shape != (3, 3):
            raise ValueError("group generators must be 3x3 matrices")

    elements: list[np.ndarray] = [I3.copy()]
    seen = {_matrix_key(I3)}
    cursor = 0
    while cursor < len(elements):
        element = elements[cursor]
        for generator in gens:
            candidate = (element @ generator).astype(np.int8)
            key = _matrix_key(candidate)
            if key not in seen:
                seen.add(key)
                elements.append(candidate)
        cursor += 1

    for element in elements:
        element.setflags(write=False)
    return tuple(elements)


# The order is stable: I, then J, then RX,
# followed by breadth-first right products in generator order.
ORIENTS: tuple[np.ndarray, ...] = group_closure((J, RX))
ORIENT_INDEX: dict[tuple[int, ...], int] = {
    _matrix_key(matrix): index for index, matrix in enumerate(ORIENTS)
}


def orient_index(matrix: np.ndarray) -> int:
    """Return the stable orientation index of a proper cube rotation."""

    try:
        return ORIENT_INDEX[_matrix_key(matrix)]
    except KeyError as exc:
        raise ValueError("matrix is not a proper axis-aligned cube rotation") from exc


def compose_orientations(left: int, right: int) -> int:
    """Index of ``ORIENTS[left] @ ORIENTS[right]``."""

    _validate_base(left)
    _validate_base(right)
    return orient_index(ORIENTS[left] @ ORIENTS[right])


def inverse_orientation(orientation: int) -> int:
    """Index of the inverse of ``orientation``."""

    _validate_base(orientation)
    return orient_index(ORIENTS[orientation].T)


J_POWERS: tuple[np.ndarray, ...] = tuple(
    np.linalg.matrix_power(J, exponent).astype(np.int8) for exponent in range(3)
)
RX_POWERS: tuple[np.ndarray, ...] = tuple(
    np.linalg.matrix_power(RX, exponent).astype(np.int8) for exponent in range(4)
)
for _matrix in (*J_POWERS, *RX_POWERS):
    _matrix.setflags(write=False)

# DIRS[o, s] = M_o J^s x-hat.
DIRS = np.empty((24, 3, 3), dtype=np.int8)
# POST[o, s, r] = index(M_o J^s Rx^r).
POST = np.empty((24, 3, 4), dtype=np.int8)
for _orientation, _matrix in enumerate(ORIENTS):
    for _state, _joint_rotation in enumerate(J_POWERS):
        _after_joint = _matrix @ _joint_rotation
        DIRS[_orientation, _state] = _after_joint[:, 0]
        for _roll, _roll_rotation in enumerate(RX_POWERS):
            POST[_orientation, _state, _roll] = orient_index(
                _after_joint @ _roll_rotation
            )
DIRS.setflags(write=False)
POST.setflags(write=False)

AXIS_DIRS = np.array(
    ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)),
    dtype=np.int8,
)
AXIS_DIRS.setflags(write=False)
_AXIS_SLOT = {tuple(int(value) for value in direction): slot for slot, direction in enumerate(AXIS_DIRS)}
DIR_SLOT = np.array(
    [[_AXIS_SLOT[tuple(int(value) for value in direction)] for direction in options] for options in DIRS],
    dtype=np.int8,
)
DIR_SLOT.setflags(write=False)

# Four successive rolls about the straight chain's local +x axis, as matrices
# (BASE_ROTS) and as orientation indices convenient for FK (BASE_ORIENTS).
BASE_ROTS: tuple[np.ndarray, ...] = RX_POWERS
BASE_ORIENTS: tuple[int, ...] = tuple(orient_index(matrix) for matrix in BASE_ROTS)


def _validate_base(base: int) -> None:
    if isinstance(base, bool) or not isinstance(base, (int, np.integer)) or not 0 <= int(base) < 24:
        raise ValueError("base orientation must be an index in 0..23")


def parse_roll(roll: str | Iterable[int], *, joints: int | None = None) -> tuple[int, ...]:
    """Normalize a roll word to digits in ``0..3``.

    ``joints`` may be supplied for an exact length check.  Strings are parsed
    one character per interface so malformed separators cannot pass silently.
    """

    if isinstance(roll, str):
        if any(character not in "0123" for character in roll):
            raise ValueError("roll word must contain only digits 0..3")
        values = tuple(int(character) for character in roll)
    else:
        try:
            values = tuple(int(value) for value in roll)
        except (TypeError, ValueError) as exc:
            raise ValueError("roll word must be an iterable of integers in 0..3") from exc
        if any(value < 0 or value > 3 for value in values):
            raise ValueError("roll values must be in 0..3")
    if joints is not None and len(values) != joints:
        raise ValueError(f"expected {joints} roll values, got {len(values)}")
    return values


def geometry_states(signed: Iterable[int]) -> list[int]:
    """Return geometry residues (0, 1, or 2) for an integer state word.

    This is a geometry-only conversion.  A physical :class:`~cubot.records.Pose`
    may contain only ``-1``, ``0``, and ``+1``.
    """

    try:
        states = list(signed)
    except TypeError as exc:
        raise ValueError("joint states must be integers") from exc
    if any(
        isinstance(state, bool) or not isinstance(state, (int, np.integer))
        for state in states
    ):
        raise ValueError("joint states must be integers")
    return [int(state) % 3 for state in states]


def signed_options(residue: int) -> tuple[int, ...]:
    """The unique physical state for a geometric residue.

    A joint has exactly three positions: ``-1``, ``0``, and ``+1``.  Although
    other integers are congruent modulo three, they would require rotating
    beyond the hardware's +/-120 degree travel and are therefore invalid.
    """

    if isinstance(residue, bool) or not isinstance(residue, (int, np.integer)):
        raise ValueError("geometry residue must be an integer")
    value = int(residue) % 3
    return ((0,), (1,), (-1,))[value]


def signed_representatives(mod3_word: Iterable[int], k: int) -> list[list[int]]:
    """Return the sole physical signed word for one geometric pose.

    ``k`` remains in the public API for compatibility, but a three-position
    joint has no legal alternate winding.
    """

    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 0:
        raise ValueError("k must be a non-negative integer")
    if k == 0:
        return []
    residues = geometry_states(mod3_word)
    return [[signed_options(residue)[0] for residue in residues]]


def apply_detent(states: Sequence[int], joint: int, delta: int) -> tuple[int, ...]:
    """Apply one detent without crossing the physical range ``[-1, +1]``."""

    if isinstance(joint, bool) or not isinstance(joint, (int, np.integer)) or not 0 <= int(joint) < len(states):
        raise ValueError("joint index is outside the state word")
    if (
        isinstance(delta, bool)
        or not isinstance(delta, (int, np.integer))
        or int(delta) not in (-1, 1)
    ):
        raise ValueError("delta must be one detent (-1 or +1)")
    if any(
        isinstance(state, bool)
        or not isinstance(state, (int, np.integer))
        or int(state) not in (-1, 0, 1)
        for state in states
    ):
        raise ValueError("joint states must be physical positions in {-1, 0, +1}")
    out = [int(state) for state in states]
    target = out[int(joint)] + int(delta)
    if not -1 <= target <= 1:
        raise ValueError("move would leave the physical state range [-1, +1]")
    out[int(joint)] = target
    return tuple(out)


def fk(
    states: Iterable[int],
    roll: str | Iterable[int],
    base: int = 0,
) -> tuple[list[Cell], list[int]]:
    """Walk a discrete chain and return module cells and orientation indices.

    There is one more module than joint state.  This low-level geometry helper
    accepts either physical states ``-1/0/+1`` or geometry residues ``0/1/2``.
    Physical planning state must always be carried by :class:`Pose`; residue
    ``2`` must never be persisted as a machine position.
    """

    _validate_base(base)
    state_word = geometry_states(states)
    roll_word = parse_roll(roll, joints=len(state_word))

    cell = np.zeros(3, dtype=np.int32)
    orientation = int(base)
    cells: list[Cell] = [(0, 0, 0)]
    orientations = [orientation]
    for state, mount_roll in zip(state_word, roll_word, strict=True):
        direction = DIRS[orientation, state]
        cell += direction
        orientation = int(POST[orientation, state, mount_roll])
        cells.append(tuple(int(value) for value in cell))
        orientations.append(orientation)
    return cells, orientations


def pose_cells(pose: Pose) -> list[Cell]:
    """Cells occupied by ``pose`` in its actual ``base`` orientation."""

    return fk(pose.states, pose.roll, pose.base)[0]


def pose_frames(pose: Pose) -> list[int]:
    """Module orientation indices for ``pose``.

    ``Pose.lying`` is descriptive metadata.  A physical lay-down is already
    represented by ``Pose.base`` (as produced by :func:`lying_variants`) and is
    therefore not applied a second time here.
    """

    return fk(pose.states, pose.roll, pose.base)[1]


def self_avoiding(states: Iterable[int], roll: str | Iterable[int], base: int = 0) -> bool:
    """Whether a discrete pose occupies distinct lattice cells."""

    cells, _ = fk(states, roll, base)
    return len(cells) == len(set(cells))


def base_rot_orientation(base_rot: int) -> int:
    """Translate ``base_rot`` quarter turns into an orientation index."""

    if isinstance(base_rot, bool) or not isinstance(base_rot, (int, np.integer)) or not 0 <= int(base_rot) < 4:
        raise ValueError("base_rot must be a quarter-turn count in 0..3")
    return BASE_ORIENTS[int(base_rot)]


def lying_orientation(base: int, lying: int) -> int:
    """Right-compose ``base`` with ``lying`` quarter-turns about local +x."""

    _validate_base(base)
    return compose_orientations(int(base), base_rot_orientation(lying))


def lying_variants(pose: Pose) -> list[Pose]:
    """The four physical rolls of a pose about the straight chain's axis.

    Each result carries the actual rolled orientation in ``base`` and records
    its quarter-turn choice in ``lying``.  Callers must not apply ``lying`` as
    another transform when evaluating the resulting pose.
    """

    return [
        replace(pose, base=lying_orientation(pose.base, quarter_turns), lying=quarter_turns)
        for quarter_turns in range(4)
    ]


def escapes_a4(roll: str | Iterable[int]) -> bool:
    """Whether a roll word contains a 90/270 degree mount and escapes A4."""

    return any(value in (1, 3) for value in parse_roll(roll))


def reachable_orientation_count(roll: str | Iterable[int]) -> int:
    """Order of the subgroup generated by ``J`` and the roll values present."""

    roll_word = parse_roll(roll)
    generators = [J]
    generators.extend(RX_POWERS[value] for value in sorted(set(roll_word)))
    return len(group_closure(generators))


def _rotation_about_axis(axis: np.ndarray, radians: float) -> np.ndarray:
    """Rodrigues rotation, intentionally independent of the integer tables."""

    x, y, z = (float(value) for value in axis)
    cosine = cos(float(radians))
    sine = sin(float(radians))
    complement = 1.0 - cosine
    return np.array(
        (
            (complement * x * x + cosine, complement * x * y - sine * z, complement * x * z + sine * y),
            (complement * x * y + sine * z, complement * y * y + cosine, complement * y * z - sine * x),
            (complement * x * z - sine * y, complement * y * z + sine * x, complement * z * z + cosine),
        ),
        dtype=np.float64,
    )


_BODY_DIAGONAL = np.array((1.0, 1.0, 1.0), dtype=np.float64) / sqrt(3.0)
_X_AXIS = np.array((1.0, 0.0, 0.0), dtype=np.float64)


def continuous_frames(
    states_rad: Iterable[float],
    roll: str | Iterable[int],
    pitch: float,
    base: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Independent floating-point FK for continuous joint angles.

    Returns ``(centres, rotations)`` with shapes ``(N, 3)`` and ``(N, 3, 3)``.
    Centre zero is the world origin and distances use ``pitch`` millimetres.  At detent
    angles this agrees with :func:`fk`, but it computes every rotation with
    Rodrigues' formula and never consults :data:`DIRS` or :data:`POST`.
    """

    _validate_base(base)
    try:
        angles = tuple(float(angle) for angle in states_rad)
    except (TypeError, ValueError) as exc:
        raise ValueError("continuous joint states must be angles in radians") from exc
    roll_word = parse_roll(roll, joints=len(angles))
    pitch_mm = float(pitch)
    if not np.isfinite(pitch_mm) or pitch_mm <= 0:
        raise ValueError("pitch must be finite and positive")
    if any(not np.isfinite(angle) for angle in angles):
        raise ValueError("continuous joint angles must be finite")

    centres = np.empty((len(angles) + 1, 3), dtype=np.float64)
    rotations = np.empty((len(angles) + 1, 3, 3), dtype=np.float64)
    centre = np.zeros(3, dtype=np.float64)
    rotation = ORIENTS[int(base)].astype(np.float64)
    centres[0] = centre
    rotations[0] = rotation

    for index, (angle, mount_roll) in enumerate(zip(angles, roll_word, strict=True)):
        after_joint = rotation @ _rotation_about_axis(_BODY_DIAGONAL, angle)
        centre = centre + pitch_mm * (after_joint @ _X_AXIS)
        rotation = after_joint @ _rotation_about_axis(_X_AXIS, mount_roll * np.pi / 2.0)
        centres[index + 1] = centre
        rotations[index + 1] = rotation
    return centres, rotations


__all__ = [
    "AXIS_DIRS",
    "BASE_ORIENTS",
    "BASE_ROTS",
    "DIRS",
    "DIR_SLOT",
    "I3",
    "J",
    "J_POWERS",
    "ORIENTS",
    "ORIENT_INDEX",
    "POST",
    "RX",
    "RX_POWERS",
    "apply_detent",
    "compose_orientations",
    "continuous_frames",
    "escapes_a4",
    "fk",
    "geometry_states",
    "group_closure",
    "inverse_orientation",
    "base_rot_orientation",
    "lying_orientation",
    "lying_variants",
    "orient_index",
    "parse_roll",
    "pose_cells",
    "pose_frames",
    "reachable_orientation_count",
    "self_avoiding",
    "signed_options",
    "signed_representatives",
]
