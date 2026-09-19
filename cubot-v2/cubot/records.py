"""Stable public records shared by the pre-simulation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from numbers import Integral
from pathlib import Path
from typing import Any, Literal

Cell = tuple[int, int, int]
Side = Literal["in", "out"]


class SearchStatus(StrEnum):
    FOUND = "FOUND"
    UNSAT = "UNSAT"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class RunMeta:
    roll: str
    pitch_mm: float
    profile: str
    config_hash: str
    seed: int = 0
    source_hash: str = ""
    git_sha: str = "unknown"
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True, slots=True)
class Pose:
    """A physical machine pose with one of three positions per joint.

    ``-1``, ``0``, and ``+1`` mean ``-120``, ``0``, and ``+120`` degrees.
    Geometry still uses the value modulo three, but values outside this range
    are not alternate windings: the hardware cannot occupy them.
    """

    states: tuple[int, ...]
    roll: str
    base: int = 0
    lying: int | None = None

    def __post_init__(self) -> None:
        if len(self.states) != 26:
            raise ValueError(f"expected 26 joint states, got {len(self.states)}")
        if len(self.roll) != 26 or any(c not in "0123" for c in self.roll):
            raise ValueError("roll must contain 26 digits in 0..3")
        if any(
            isinstance(state, bool)
            or not isinstance(state, Integral)
            or int(state) not in (-1, 0, 1)
            for state in self.states
        ):
            raise ValueError("joint states must be one of -1, 0, or +1")
        if not 0 <= self.base < 24:
            raise ValueError("base orientation must be in 0..23")
        if self.lying is not None and not 0 <= self.lying < 4:
            raise ValueError("lying face must be None or 0..3")

    @property
    def residues(self) -> tuple[int, ...]:
        return tuple(s % 3 for s in self.states)


@dataclass(slots=True)
class CheckReport:
    hard: dict[str, tuple[bool, str]] = field(default_factory=dict)
    soft: dict[str, tuple[float, str]] = field(default_factory=dict)
    measurements: dict[str, float | int | str | bool] = field(default_factory=dict)

    @property
    def hard_ok(self) -> bool:
        return all(passed for passed, _ in self.hard.values())

    @property
    def worst_soft(self) -> float:
        return min((score for score, _ in self.soft.values()), default=1.0)

    @property
    def violations(self) -> list[str]:
        return [f"{name}: {reason}" for name, (ok, reason) in self.hard.items() if not ok]


@dataclass(slots=True)
class Move:
    joint: int
    delta: int
    side: Side
    duration_s: float = 2.0
    checks: CheckReport = field(default_factory=CheckReport)

    def __post_init__(self) -> None:
        if isinstance(self.joint, bool) or not isinstance(self.joint, Integral) or not 0 <= int(self.joint) < 26:
            raise ValueError("joint must be in 0..25")
        if (
            isinstance(self.delta, bool)
            or not isinstance(self.delta, Integral)
            or int(self.delta) not in (-1, 1)
        ):
            raise ValueError("a move is one signed detent")


@dataclass(slots=True)
class PlanCandidate:
    start: Pose
    goal: Pose
    moves: list[Move]
    complete: bool
    goal_progress: int
    hard_ok: bool
    scores: dict[str, float] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def rank_key(self) -> tuple[int, float, float, float, int, int]:
        """Contract ordering for passing, violating, and partial plans.

        Completion class is always primary.  For complete violating plans the
        normalized violation count precedes soft scores.  For partial plans,
        remaining goal distance precedes violation severity, so a useful
        near-complete route cannot be hidden by a shallow route whose only
        advantage is that it has accumulated fewer soft measurements.
        """

        violation_count = sum(1 for violation in self.violations if violation)
        worst = min(self.scores.values(), default=1.0)
        if self.complete and self.hard_ok:
            return (0, 0.0, -worst, 0.0, len(self.moves), -self.goal_progress)
        if self.complete:
            normalized = violation_count / max(1, len(self.moves))
            return (1, normalized, -worst, 0.0, len(self.moves), -self.goal_progress)
        remaining = max(0, len(self.goal.states) - self.goal_progress)
        return (
            2,
            float(remaining),
            float(violation_count),
            -worst,
            len(self.moves),
            -self.goal_progress,
        )


@dataclass(slots=True)
class FoldResult:
    status: SearchStatus
    candidates: list[PlanCandidate]
    nodes: int
    elapsed_s: float
    proof: dict[str, Any] | None = None
    diagnostics: list[str] = field(default_factory=list)

    def ranked(self) -> list[PlanCandidate]:
        return sorted(self.candidates, key=lambda candidate: candidate.rank_key)


@dataclass(slots=True)
class ShapeRecord:
    name: str
    aliases: list[str]
    target: list[str]
    cells: list[Cell]
    pose: Pose | None
    plans: list[PlanCandidate]
    renders: dict[str, str]
    human_pick: bool | None
    source: str
    status: Literal["proposed", "threadable", "planned", "checked", "picked"]
    meta: RunMeta
    notes: list[str] = field(default_factory=list)


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def dump_json(value: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n")
