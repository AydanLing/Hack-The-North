"""Loading CuBot V2 fold paths and handing them to whatever drives the robot.

`handoff/shapes/<nn>-<name>/path.json` is the contract (schema `cubot.handoff.v1`); this module reads
it and nothing else — no planner import, no numpy. See `cubot-v2/handoff/README.md` for the field
reference. The two facts that matter to a caller:

* a move is one detent on one joint, `delta in {-1, +1}`, with a recorded `side` (`in` = modules
  `0..j-1` swing, `out` = modules `j+1..26` swing). Replay the recorded side; re-deciding it changes
  the world orientation the shape finishes in.
* `snake_pipeline.goal_states_mod3_27` is the same goal in snake_pipeline's bookkeeping, for the
  MuJoCo model.

Execution itself is deliberately behind a small interface. The bridge's job ends at "this is the plan";
MuJoCo and the servo bus belong to their owners, so the shipped executors either log the plan or spool
it to a JSONL queue for them to consume.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class Move:
    """One detent. `side` is 'in' or 'out'; `moving_side` is the same thing in snake_pipeline's words."""

    step: int
    joint: int
    delta: int
    side: str
    duration_s: float
    moving_side: str = ""
    state_after: int = 0
    hard_ok: bool = True
    peak_demand_nm: float = 0.0

    def compact(self) -> list:
        return [self.joint, self.delta, self.side, self.duration_s]


@dataclass
class FoldPlan:
    """A finalized path for one shape, as much of it as a driver needs."""

    shape: str
    number: int
    moves: list[Move]
    total_time_s: float
    ends_flat_on_table: bool
    loose_hard_ok: bool
    loose_violations: int
    peak_demand_nm: float
    goal_silhouette: list[str] = field(default_factory=list)
    goal_states_mod3_27: list[int] = field(default_factory=list)
    start_base: Optional[int] = None
    final_base: Optional[int] = None
    path_json: str = ""
    warnings: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        finish = "flat" if self.ends_flat_on_table else "standing on edge"
        return (f"{self.shape}: {len(self.moves)} moves, {self.total_time_s:.0f}s, finishes {finish}, "
                f"peak {self.peak_demand_nm:.1f} N·m"
                + ("" if self.loose_hard_ok else f", {self.loose_violations} hard violations"))

    def to_dict(self) -> dict:
        return {
            "shape": self.shape, "number": self.number, "total_time_s": self.total_time_s,
            "ends_flat_on_table": self.ends_flat_on_table, "loose_hard_ok": self.loose_hard_ok,
            "loose_violations": self.loose_violations, "peak_demand_nm": self.peak_demand_nm,
            "start_base": self.start_base, "final_base": self.final_base,
            "goal_states_mod3_27": self.goal_states_mod3_27,
            "moves": [m.compact() for m in self.moves],
            "path_json": self.path_json, "warnings": self.warnings,
        }


class ShapeLibrary:
    """The handoff folder, indexed by shape name. Paths are read once and cached."""

    def __init__(self, handoff_dir: str):
        self.handoff_dir = handoff_dir
        self._cache: dict[str, FoldPlan] = {}
        with open(os.path.join(handoff_dir, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        self.roll: str = str(index.get("roll", ""))
        self.pitch_mm: float = float(index.get("pitch_mm", 0.0) or 0.0)
        self._rows: dict[str, dict] = {str(r["name"]).lower(): r for r in index.get("shapes", [])
                                      if r.get("name")}

    def __contains__(self, shape: str) -> bool:
        return str(shape).lower() in self._rows

    @property
    def names(self) -> list[str]:
        return sorted(self._rows, key=lambda n: self._rows[n].get("number", 999))

    def path_json_for(self, shape: str) -> str:
        row = self._rows[str(shape).lower()]
        return os.path.join(self.handoff_dir, str(row["dir"]), "path.json")

    def plan(self, shape: str) -> FoldPlan:
        key = str(shape).lower()
        if key in self._cache:
            return self._cache[key]
        if key not in self._rows:
            raise KeyError(f"{shape!r} is not in {self.handoff_dir}/index.json; have: {', '.join(self.names)}")
        path = self.path_json_for(key)
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        plan = _plan_from_doc(doc, path)
        self._cache[key] = plan
        return plan


def _plan_from_doc(doc: dict, path_json: str) -> FoldPlan:
    summary = doc.get("summary", {}) or {}
    status = doc.get("status", {}) or {}
    goal = doc.get("goal", {}) or {}
    final = doc.get("final_tracked", {}) or {}
    sp = doc.get("snake_pipeline", {}) or {}
    moves = [
        Move(
            step=int(m.get("step", i + 1)),
            joint=int(m["joint"]),
            delta=int(m["delta"]),
            side=str(m.get("side", "")),
            duration_s=float(m.get("duration_s", 2.0)),
            moving_side=str(m.get("moving_side_snake_pipeline", "")),
            state_after=int(m.get("state_after", 0)),
            hard_ok=bool(m.get("hard_ok", True)),
            peak_demand_nm=float(((m.get("checks") or {}).get("measurements") or {})
                                 .get("peak_demand_nm", 0.0) or 0.0),
        )
        for i, m in enumerate(doc.get("moves", []))
    ]
    violations = status.get("loose_violations") or []
    warnings: list[str] = []
    if not status.get("loose_hard_ok", True):
        warnings.append(f"{len(violations)} loose hard-check violation(s): expected to fail physically")
    return FoldPlan(
        shape=str(doc.get("name", "")),
        number=int(doc.get("demo_number", 0) or 0),
        moves=moves,
        total_time_s=float(summary.get("total_time_s", sum(m.duration_s for m in moves))),
        ends_flat_on_table=bool(summary.get("ends_flat_on_table", True)),
        loose_hard_ok=bool(status.get("loose_hard_ok", True)),
        loose_violations=len(violations),
        peak_demand_nm=float(summary.get("peak_demand_nm", 0.0) or 0.0),
        goal_silhouette=[str(r) for r in (goal.get("silhouette") or [])],
        goal_states_mod3_27=[int(s) for s in (sp.get("goal_states_mod3_27") or [])],
        start_base=(doc.get("start") or {}).get("base"),
        final_base=final.get("base"),
        path_json=path_json,
        warnings=warnings,
    )


# --------------------------------------------------------------------------------- execution

class Executor(Protocol):
    """Whatever actually moves the robot. The bridge only needs `submit`."""

    name: str

    def submit(self, plan: FoldPlan, context: dict) -> dict:
        ...


class DryRunExecutor:
    """Logs the plan and returns. The default: it is what you want on a laptop, and it is what the
    demo should run until the sim or the servo bus is wired in."""

    name = "dryrun"

    def __init__(self, log=print):
        self.log = log
        self.submitted: list[FoldPlan] = []

    def submit(self, plan: FoldPlan, context: dict) -> dict:
        self.submitted.append(plan)
        self.log(f"[dryrun] {plan.summary_line()}")
        for w in plan.warnings:
            self.log(f"[dryrun]   ! {w}")
        self.log(f"[dryrun]   moves: " + " ".join(f"{m.joint}{'+' if m.delta > 0 else '-'}{m.side[:1]}"
                                                 for m in plan.moves))
        return {"executor": self.name, "accepted": True, "moves": len(plan.moves)}

    def home_all(self, context: dict | None = None) -> dict:
        self.log("[dryrun] home_all → software zero (straight line)")
        return {"executor": self.name, "accepted": True, "home": True}


class SpoolExecutor:
    """Appends one JSON line per request to a queue file for the sim / hardware owner to consume.

    This is the integration boundary the handoff asks for: the bridge decides *what* to fold, the sim
    reports back `formed`, drift, peak torque and the face it landed on (handoff/README.md, "What we
    would like back").
    """

    name = "spool"

    def __init__(self, path: str, log=print):
        self.path = path
        self.log = log
        self._lock = threading.Lock()

    def submit(self, plan: FoldPlan, context: dict) -> dict:
        row = {"queued_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "context": context,
               "plan": plan.to_dict()}
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self.log(f"[spool] queued {plan.shape} -> {self.path}")
        return {"executor": self.name, "accepted": True, "queued": self.path}


class NullExecutor:
    """Accepts and discards. For load-testing the language path without touching the robot."""

    name = "none"

    def submit(self, plan: FoldPlan, context: dict) -> dict:
        return {"executor": self.name, "accepted": True}


class ViewerExecutor:
    """Opens the CuBot fold viewer in the default browser on this machine and autoplays the shape.

    The bridge HTTP server mounts `cubot_urdf/` at `/sim/`, so the URL is always local even when
    Linq reaches the webhook through a tunnel. Falls back to a `file://` open if no `viewer_base`
    is configured.
    """

    name = "viewer"

    def __init__(self, viewer_base: str = "", viewer_html: str = "", log=print):
        self.viewer_base = (viewer_base or "http://127.0.0.1:8787/sim").rstrip("/")
        self.viewer_html = viewer_html
        self.log = log
        self.submitted: list[FoldPlan] = []

    def submit(self, plan: FoldPlan, context: dict) -> dict:
        from urllib.parse import urlencode
        import subprocess
        import webbrowser

        self.submitted.append(plan)
        query = urlencode({"shape": plan.shape, "play": "1"})
        if self.viewer_html and os.path.isfile(self.viewer_html) and not self.viewer_base:
            from pathlib import Path
            url = Path(self.viewer_html).resolve().as_uri() + "?" + query
        else:
            url = f"{self.viewer_base}/fold_viewer.html?{query}"
        self.log(f"[viewer] opening {url}")
        opened = False
        try:
            # Prefer macOS `open` so a new tab lands in the frontmost browser.
            if sys.platform == "darwin":
                subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                opened = True
            else:
                opened = bool(webbrowser.open(url, new=2))
        except Exception as e:
            self.log(f"[viewer] open failed: {type(e).__name__}: {e}")
        return {"executor": self.name, "accepted": True, "url": url, "opened": opened,
                "moves": len(plan.moves)}


class MujocoExecutor:
    """Spawns the interactive MuJoCo viewer replaying the shape's handoff path.

    On macOS this *must* go through `mjpython` or no window appears. Only one replay runs at a
    time: a new text kills the previous viewer so the laptop is not buried in windows.
    """

    name = "mujoco"
    _pid_path = os.path.join(os.path.expanduser("~"), ".cache", "cubot-mujoco.pid")

    def __init__(self, scene_xml: str = "", python_exe: str = "", speed: float = 1.0, log=print):
        from .config import REPO_ROOT
        self.scene_xml = scene_xml or os.path.join(REPO_ROOT, "cubot_urdf", "n17", "scene.xml")
        self.python_exe = python_exe or self._pick_python(log=log)
        self.speed = speed
        self.log = log
        self.submitted: list[FoldPlan] = []

    # Interpreters to try when mjpython is not next to us and not on PATH. Under
    # launchd the agent inherits a minimal PATH, so `which` alone silently falls
    # back to a plain python that opens no window at all.
    _MJPYTHON_FALLBACKS = (
        "/opt/homebrew/Caskroom/miniconda/base/bin/mjpython",
        "/opt/homebrew/bin/mjpython",
        "/usr/local/bin/mjpython",
    )

    @staticmethod
    def _pick_python(log=None) -> str:
        """Find mjpython: sibling, then PATH, then known install locations."""
        def usable(p: str) -> bool:
            return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)

        override = (os.environ.get("CUBOT_MJPYTHON") or "").strip()
        if override:
            if usable(override):
                return override
            if log:
                log(f"[mujoco] CUBOT_MJPYTHON={override!r} is not executable; searching instead")

        here = os.path.dirname(os.path.abspath(sys.executable))
        for name in ("mjpython", "mjpython.exe"):
            candidate = os.path.join(here, name)
            if usable(candidate):
                return candidate

        import shutil
        found = shutil.which("mjpython")
        if found:
            return found
        for candidate in MujocoExecutor._MJPYTHON_FALLBACKS:
            if usable(candidate):
                return candidate
        if log:
            log("[mujoco] no mjpython found — on macOS the viewer needs it to own the "
                "main thread, so no window will open. Set CUBOT_MJPYTHON to its path.")
        return sys.executable

    def _stop_previous(self) -> None:
        import signal
        try:
            with open(self._pid_path, encoding="utf-8") as f:
                old = int(f.read().strip() or 0)
        except (OSError, ValueError):
            return
        if old <= 0:
            return
        try:
            os.kill(old, signal.SIGTERM)
            self.log(f"[mujoco] stopped previous viewer (pid {old})")
        except ProcessLookupError:
            pass
        except OSError as e:
            self.log(f"[mujoco] could not stop pid {old}: {e}")

    def submit(self, plan: FoldPlan, context: dict) -> dict:
        import subprocess

        self.submitted.append(plan)
        if not plan.path_json or not os.path.isfile(plan.path_json):
            raise FileNotFoundError(f"no path.json for {plan.shape}")
        if not os.path.isfile(self.scene_xml):
            raise FileNotFoundError(f"MuJoCo scene missing: {self.scene_xml}")

        self._stop_previous()
        env = os.environ.copy()
        # so `python -m cubot_imessage.mujoco_replay` resolves regardless of cwd
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = pkg_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONUNBUFFERED"] = "1"
        # launchd / minimal PATH lacks /usr/sbin; mjpython imports mujoco which shells out to `sysctl`.
        env["PATH"] = (
            os.path.dirname(self.python_exe) + ":/opt/homebrew/bin:/usr/local/bin:"
            "/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
        )

        cmd = [
            self.python_exe, "-u", "-m", "cubot_imessage.mujoco_replay",
            "--path", plan.path_json,
            "--scene", self.scene_xml,
            "--speed", str(self.speed),
            "--title", f"CuBot · {plan.shape}",
        ]
        self.log(f"[mujoco] launching {' '.join(cmd)}")
        log_path = os.path.join(os.path.dirname(self._pid_path), "cubot-mujoco.log")
        log_f = open(log_path, "w", encoding="utf-8")
        # Detach from the bridge so a viewer crash cannot kill the webhook server.
        proc = subprocess.Popen(
            cmd, env=env, stdout=log_f, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        os.makedirs(os.path.dirname(self._pid_path), exist_ok=True)
        with open(self._pid_path, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
        return {"executor": self.name, "accepted": True, "pid": proc.pid,
                "path": plan.path_json, "moves": len(plan.moves), "log": log_path}


def build_executor(kind: str, spool_path: str = "", log=print,
                   viewer_base: str = "", viewer_html: str = "",
                   scene_xml: str = "",
                   hw_root: str = "", serial_port: str = "",
                   gear: float = 4.0, power: int = 3,
                   mirror_mujoco: bool | None = None,
                   n_modules: int | None = None) -> Executor:
    kind = (kind or "dryrun").lower()
    if kind == "none":
        return NullExecutor()
    if kind == "spool":
        return SpoolExecutor(spool_path or "out/imessage-queue.jsonl", log=log)
    if kind == "viewer":
        return ViewerExecutor(viewer_base=viewer_base, viewer_html=viewer_html, log=log)
    if kind == "mujoco":
        return MujocoExecutor(scene_xml=scene_xml, log=log)
    if kind == "hardware":
        from .hardware import HardwareExecutor  # noqa: PLC0415 — keeps dryrun imports light
        return HardwareExecutor(hw_root=hw_root, serial_port=serial_port,
                                gear=gear, power=power, scene_xml=scene_xml,
                                mirror_mujoco=mirror_mujoco, n_modules=n_modules, log=log)
    if kind == "dryrun":
        return DryRunExecutor(log=log)
    raise ValueError(
        f"unknown executor {kind!r} (dryrun | spool | viewer | mujoco | hardware | none)")


def load_any(path: str) -> FoldPlan:
    """A FoldPlan straight from a `path.json`, for poking at a single file."""
    with open(path, encoding="utf-8") as f:
        return _plan_from_doc(json.load(f), path)


def replay_states(plan: FoldPlan) -> list[int]:
    """Re-derive joint states by applying the deltas in order — a cheap consistency check
    against `goal_states_mod3_27` (handoff/tools/replay.py does the full kinematic version)."""
    n = max((m.joint for m in plan.moves), default=-1) + 1
    if plan.goal_states_mod3_27:
        # goal list is often joints+pad; fold joints are everything but a possible trailing pad.
        n = max(n, len(plan.goal_states_mod3_27) - 1)
    states = [0] * max(n, 0)
    for m in plan.moves:
        if m.joint >= len(states):
            states.extend([0] * (m.joint + 1 - len(states)))
        states[m.joint] += m.delta
    return states


def states_match_goal(plan: FoldPlan) -> bool:
    """True when replaying the deltas reaches the recorded goal (mod-3 joint list, optional tip pad)."""
    if not plan.goal_states_mod3_27:
        return True
    goal = [s % 3 for s in plan.goal_states_mod3_27]
    derived = [s % 3 for s in replay_states(plan)]
    if derived == goal:
        return True
    # Older 27-cube exports padded one trailing unused tip entry.
    if len(goal) == len(derived) + 1 and derived + [0] == goal:
        return True
    if len(goal) == len(derived) - 1 and derived[:-1] == goal:
        return True
    return False


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
