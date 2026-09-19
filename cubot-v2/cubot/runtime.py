"""Reproducibility and run-directory helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from .config import Machine, Profile, config_hash
from .records import RunMeta


def git_sha(root: str | Path | None = None) -> str:
    directory = Path(root) if root else Path(__file__).resolve().parents[2]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_meta(
    machine: Machine,
    profile: Profile,
    *,
    seed: int,
    source_hash: str = "",
) -> RunMeta:
    return RunMeta(
        roll=machine.roll,
        pitch_mm=machine.pitch_mm,
        profile=profile.name,
        config_hash=config_hash(machine, profile),
        seed=seed,
        source_hash=source_hash,
        git_sha=git_sha(),
    )
