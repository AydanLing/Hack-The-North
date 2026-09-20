"""Configuration loading, validation, and reproducible hashing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import tomllib

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_CONFIG_ROOT = PACKAGE_ROOT / "config"
_WHEEL_CONFIG_ROOT = Path(__file__).resolve().parent / "_assets" / "config"
CONFIG_ROOT = _SOURCE_CONFIG_ROOT if _SOURCE_CONFIG_ROOT.is_dir() else _WHEEL_CONFIG_ROOT


@dataclass(frozen=True, slots=True)
class Machine:
    modules: int
    side_mm: float
    gap_mm: float
    chamfer_mm: float
    roll: str
    mass_kg: float
    stall_torque_nm: float
    move_time_s: float
    joint_angle_deg: float = 120.0
    joint_min_position: int = -1
    joint_max_position: int = 1
    # Cable bundle leaving module 0 through its mount face (local -x, the face
    # a preceding module would attach to).  Modelled as a rigid keep-out box:
    # nothing may sweep through it or rest in the lattice cell it occupies.
    tether_length_mm: float = 0.0
    tether_width_mm: float = 40.0
    tether_facets: int = 4  # 4 = square box of tether_width_mm; 8 = round bundle of that diameter

    @property
    def has_tether(self) -> bool:
        return self.tether_length_mm > 0.0

    @property
    def pitch_mm(self) -> float:
        return self.side_mm + self.gap_mm

    @property
    def joints(self) -> int:
        return self.modules - 1


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    sweep_step_deg: float
    hard_penetration_mm: float
    soft_penetration_mm: float
    pivot_dip_exempt_mm: float
    ground_soft_mm: float
    ground_hard_mm: float
    torque_cap_nm: float
    torque_stall_nm: float
    balance_margin_mm: float
    fold_budget_s: float
    node_budget: int
    detour_budget: int
    side_ambiguity_ratio: float
    # Optional stress hard gates (defaults = effectively off for legacy profiles).
    holding_hard_nm: float = 1e9
    pivot_dip_hard_mm: float = 1e9
    balance_hard_mm: float = -1e9


def escapes_a4(roll: str) -> bool:
    return any(digit in "13" for digit in roll)


def _validate_machine(machine: Machine) -> None:
    if machine.modules < 2:
        raise ValueError("modules must be >= 2")
    if len(machine.roll) != machine.joints or any(c not in "0123" for c in machine.roll):
        raise ValueError("roll length/digits do not match the machine")
    if not escapes_a4(machine.roll):
        raise ValueError("roll is trapped in the 12-element A4 subgroup")
    if machine.pitch_mm <= machine.side_mm:
        raise ValueError("pitch must exceed cube side")
    if machine.joint_angle_deg != 120.0:
        raise ValueError("CuBot V2 joint detents must be 120 degrees")
    if (machine.joint_min_position, machine.joint_max_position) != (-1, 1):
        raise ValueError("CuBot V2 joints must have positions -1, 0, and +1")
    if machine.tether_length_mm < 0.0 or machine.tether_width_mm <= 0.0 or machine.tether_width_mm > machine.side_mm:
        raise ValueError("tether_length_mm must be >= 0 and 0 < tether_width_mm <= side_mm")
    if machine.tether_facets < 3:
        raise ValueError("tether_facets must be >= 3 (4 = square box, 8 = round bundle)")


def load_machine(path: str | Path | None = None) -> Machine:
    source = Path(path) if path else CONFIG_ROOT / "machine.toml"
    raw = tomllib.loads(source.read_text())
    machine = Machine(**raw["machine"])
    _validate_machine(machine)
    return machine


def load_profile(name: str = "loose", path: str | Path | None = None) -> Profile:
    source = Path(path) if path else CONFIG_ROOT / "profiles" / f"{name}.toml"
    raw = tomllib.loads(source.read_text())
    profile = Profile(name=name, **raw["profile"])
    if not 0.0 < profile.side_ambiguity_ratio <= 1.0:
        raise ValueError("side_ambiguity_ratio must be in (0, 1]")
    return profile


def config_hash(
    machine: Machine,
    profile: Profile,
    *,
    geometry_hash: str | None = None,
) -> str:
    if geometry_hash is None:
        from .solid import solid_geometry_hash

        geometry_hash = solid_geometry_hash()
    payload = json.dumps(
        {
            "machine": asdict(machine),
            "profile": asdict(profile),
            "geometry_hash": geometry_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
