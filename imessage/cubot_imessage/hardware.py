"""Live STS3215 executor: handoff FoldPlan → Downloads/cubot `rc.Axis` chase.

Imports Jerry's proven driver in-place via ``CUBOT_HW_ROOT`` (default
``/Users/jerryli/Downloads/cubot``). Does not vendor that tree.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

from .mujoco_replay import STEPS_PER_STATE, hardware_wall_s

DEFAULT_HW_ROOT = "/Users/jerryli/Downloads/cubot"
EXPECTED_SIDS = list(range(1, 27))  # servo id i+1 ↔ handoff joint i
DETENT_OUT_DEG = 120.0
POLL_S = 0.04
# Chase speed index into rc.SPEEDS; power preset still caps via Axis._capped.
DEFAULT_SPEED_IDX = 3  # 800 steps/s before power cap
PID_PATH = os.path.join(os.path.expanduser("~"), ".cache", "cubot-hardware.pid")


def _ensure_hw_path(hw_root: str) -> str:
    root = os.path.abspath(hw_root or DEFAULT_HW_ROOT)
    if not os.path.isdir(root):
        raise FileNotFoundError(
            f"CUBOT_HW_ROOT missing: {root} (set CUBOT_HW_ROOT to the working sts3215/rc tree)")
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def _import_driver(hw_root: str):
    _ensure_hw_path(hw_root)
    try:
        import rc  # type: ignore  # noqa: PLC0415 — lives under CUBOT_HW_ROOT
        import sts3215  # type: ignore  # noqa: PLC0415
    except ImportError as e:
        raise ImportError(
            f"cannot import rc/sts3215 from {_ensure_hw_path(hw_root)}: {e}"
        ) from e
    return rc, sts3215


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


class HardwareExecutor:
    """Replay a FoldPlan on the real STS3215 chain (ids 1..26).

    Soft-zeros at the current encoder pose (caller must leave the robot straight),
    then applies each handoff detent as ``state[j] * 120°`` output via ``Axis.go``.

    By default also spawns the MuJoCo viewer so a texted fold is visible on screen
    while the physical chain moves (``CUBOT_MUJOCO_MIRROR=false`` to disable).
    """

    name = "hardware"

    def __init__(
        self,
        hw_root: str = "",
        serial_port: str = "",
        gear: float = 4.0,
        power: int = 0,
        limit_deg: float = DETENT_OUT_DEG,
        mirror_mujoco: bool | None = None,
        scene_xml: str = "",
        log=print,
    ):
        self.hw_root = hw_root or os.environ.get("CUBOT_HW_ROOT", DEFAULT_HW_ROOT)
        self.serial_port = (serial_port or os.environ.get("CUBOT_SERIAL_PORT", "")).strip()
        self.gear = float(os.environ.get("CUBOT_GEAR", gear) or gear)
        try:
            self.power = int(os.environ.get("CUBOT_POWER", str(power)))
        except ValueError:
            self.power = power
        self.limit_deg = float(limit_deg)
        if mirror_mujoco is None:
            mirror_mujoco = _env_bool("CUBOT_MUJOCO_MIRROR", True)
        self.mirror_mujoco = bool(mirror_mujoco)
        self.scene_xml = scene_xml
        self.log = log
        self.submitted: list = []
        self._lock = threading.Lock()
        self._bus = None
        self._axes: list = []
        self._rc = None
        self._sts = None
        self._mujoco = None

    # -- bus lifecycle -------------------------------------------------------

    def _open(self) -> None:
        if self._bus is not None:
            return
        rc, sts = _import_driver(self.hw_root)
        self._rc, self._sts = rc, sts
        port = self.serial_port or sts.autodetect_port()
        self.log(f"[hardware] opening bus on {port} (gear={self.gear}, power={self.power})")
        bus = sts.Bus(port)
        found = bus.scan(EXPECTED_SIDS)
        missing = [s for s in EXPECTED_SIDS if s not in found]
        if missing:
            try:
                bus.close()
            except Exception:
                pass
            raise RuntimeError(
                f"robot offline / incomplete bus: need servos {EXPECTED_SIDS[0]}..{EXPECTED_SIDS[-1]}, "
                f"missing {missing} (found {found})"
            )
        geo = rc.Geometry(gear=self.gear, limit_deg=self.limit_deg)
        axes = [rc.Axis(bus, sid, geo) for sid in EXPECTED_SIDS]
        for ax in axes:
            # Seed continuous track from the live encoder, then soft-zero here
            # (straight chain is the session origin for handoff state 0).
            st = bus.read_state(ax.sid)
            ax.update(st["position"])
            ax.set_zero()
            ax.set_power(self.power)
            ax.set_torque(True)
        self._bus = bus
        self._axes = axes
        self.log(f"[hardware] torque on · {len(axes)} axes · power "
                 f"{rc.power_name(self.power)}")

    def _close(self) -> None:
        axes, bus = self._axes, self._bus
        self._axes, self._bus = [], None
        for ax in axes:
            try:
                ax.shutdown()
            except Exception:
                pass
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass

    def _claim_mutex(self) -> None:
        os.makedirs(os.path.dirname(PID_PATH), exist_ok=True)
        try:
            with open(PID_PATH, encoding="utf-8") as f:
                old = int(f.read().strip() or 0)
        except (OSError, ValueError):
            old = 0
        if old > 0 and old != os.getpid():
            try:
                os.kill(old, 0)
            except ProcessLookupError:
                pass
            except OSError:
                pass
            else:
                raise RuntimeError(
                    f"another hardware fold is already running (pid {old}); wait or clear {PID_PATH}")
        with open(PID_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

    def _release_mutex(self) -> None:
        try:
            with open(PID_PATH, encoding="utf-8") as f:
                cur = int(f.read().strip() or 0)
            if cur == os.getpid():
                os.remove(PID_PATH)
        except (OSError, ValueError):
            pass

    # -- motion --------------------------------------------------------------

    def _dest_cont(self, axis, state: int) -> int:
        """Continuous encoder target for handoff state in {-1,0,+1}."""
        steps = int(round(int(state) * STEPS_PER_STATE))
        return axis.home + steps

    def _chase(self, axis, timeout_s: float, speed: int) -> bool:
        """Drive until Axis clears dest or wall-clock timeout. Returns arrived?"""
        deadline = time.monotonic() + max(timeout_s, 0.5)
        while axis.dest is not None and time.monotonic() < deadline:
            try:
                st = self._bus.read_state(axis.sid)
            except Exception as e:
                self.log(f"[hardware] read failed sid={axis.sid}: {e}")
                axis.stop("read failed")
                return False
            axis.update(st["position"])
            axis.drive(speed)
            time.sleep(POLL_S)
        arrived = axis.dest is None
        if not arrived:
            axis.stop("timeout")
        return arrived

    def _run_plan(self, plan) -> dict[str, Any]:
        assert self._rc is not None and self._axes
        speed = self._rc.SPEEDS[min(DEFAULT_SPEED_IDX, len(self._rc.SPEEDS) - 1)]
        state = [0] * 26
        arrived_all = True
        for m in plan.moves:
            j = int(m.joint)
            if j < 0 or j >= 26:
                raise ValueError(f"joint {j} out of range 0..25")
            nxt = state[j] + int(m.delta)
            if nxt not in (-1, 0, 1):
                self.log(f"[hardware] clamp j{j} state {state[j]}{m.delta:+d} → "
                         f"{max(-1, min(1, nxt))}")
                nxt = max(-1, min(1, nxt))
            state[j] = nxt
            axis = self._axes[j]
            dest = self._dest_cont(axis, state[j])
            wall = hardware_wall_s(abs(int(m.delta)) or 1, float(m.duration_s) or 2.0)
            # Give the chase a little slack beyond the load estimate.
            timeout = max(wall * 1.35, float(m.duration_s) or 2.0, 1.0)
            self.log(
                f"[hardware] step {m.step:3d}  j{j:<2d} → state {state[j]:+d}  "
                f"side={m.side}  wall≈{wall:.1f}s  timeout={timeout:.1f}s"
            )
            axis.go(dest, f"j{j}→{state[j]:+d}")
            ok = self._chase(axis, timeout, speed)
            if not ok:
                arrived_all = False
                self.log(f"[hardware]   ! did not arrive (status={axis.status})")
            else:
                self.log(f"[hardware]   arrived ({axis.status})")
        return {
            "executor": self.name,
            "accepted": True,
            "moves": len(plan.moves),
            "formed": arrived_all,
            "final_states": list(state),
        }

    def _spawn_mujoco(self, plan, context: dict, *, force: bool = False) -> dict | None:
        """Fire-and-forget MuJoCo viewer; never blocks the bus fold."""
        if not self.mirror_mujoco and not force:
            return None
        try:
            from .robot import MujocoExecutor  # noqa: PLC0415 — avoid import cycle at module load
            if self._mujoco is None:
                self._mujoco = MujocoExecutor(scene_xml=self.scene_xml, log=self.log)
            self.log("[hardware] mirroring fold in MuJoCo viewer")
            return self._mujoco.submit(plan, context)
        except Exception as e:
            # Viewer is optional for demos — robot fold still proceeds when the bus is up.
            self.log(f"[hardware] MuJoCo mirror failed: {type(e).__name__}: {e}")
            return {"executor": "mujoco", "accepted": False, "error": str(e)}

    def submit(self, plan, context: dict) -> dict:
        self.submitted.append(plan)
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("hardware busy: another fold is in progress")

        try:
            self._claim_mutex()
            # Probe the bus first so we know whether to force a sim-only mirror.
            bus_error: Exception | None = None
            try:
                self._open()
            except Exception as e:
                bus_error = e
                self.log(f"[hardware] bus unavailable — sim only: {e}")

            # Always open MuJoCo when the bus is down (even if mirror is off);
            # otherwise mirror as usual so text + metal stay paired.
            mujoco_info = self._spawn_mujoco(plan, context, force=bus_error is not None)

            if bus_error is not None:
                result = {
                    "executor": self.name,
                    "accepted": True,
                    "moves": len(plan.moves),
                    "formed": False,
                    "hardware_online": False,
                    "hardware_offline": True,
                    "error": f"robot offline: {bus_error}",
                    "sim_only": True,
                }
                if mujoco_info is not None:
                    result["mujoco"] = mujoco_info
                return result

            self.log(f"[hardware] folding {plan.summary_line()}")
            for w in plan.warnings:
                self.log(f"[hardware]   ! {w}")
            try:
                result = self._run_plan(plan)
            except Exception as e:
                self.log(f"[hardware] fold aborted: {type(e).__name__}: {e}")
                raise
            result["hardware_online"] = True
            result["hardware_offline"] = False
            if mujoco_info is not None:
                result["mujoco"] = mujoco_info
            return result
        finally:
            self._release_mutex()
            self._lock.release()

    def shutdown(self) -> None:
        with self._lock:
            self._close()
            self._release_mutex()
