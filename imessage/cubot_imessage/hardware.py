"""Live STS3215 executor: handoff FoldPlan → Downloads/cubot `rc.Axis` chase.

Imports Jerry's proven driver in-place via ``CUBOT_HW_ROOT`` (default
``/Users/jerryli/Downloads/cubot``). Does not vendor that tree.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any

from .mujoco_replay import LOAD_SPEED_FRACTION, SETTLE_S, STEPS_PER_STATE, hardware_wall_s

DEFAULT_HW_ROOT = "/Users/jerryli/Downloads/cubot"
DETENT_OUT_DEG = 120.0
POLL_S = 0.04
# Chase speed index into rc.SPEEDS; power preset still caps via Axis._capped.
DEFAULT_SPEED_IDX = 3  # 800 steps/s before power cap
PID_PATH = os.path.join(os.path.expanduser("~"), ".cache", "cubot-hardware.pid")
# A wheel-mode "hold" is goal_speed 0, not a position hold: gravity creeps a
# loaded joint off its detent. Re-chase any joint that sagged past this.
TRIM_STEPS = 150
TRACK_NAME = "servo_state.json"    # rc.StateStore dead-reckoned turn counts
SIGNS_NAME = "joint_signs.json"    # optional per-joint direction map [±1]×26


def _calibration_path(name: str):
    from .homes import homes_path  # noqa: PLC0415 — avoid import cycle at module load
    return homes_path().parent / name


def expected_sids(n_modules: int | None = None) -> list[int]:
    """Servo ids for fold joints: modules N → joints N-1 → sids 1..N-1."""
    from .config import DEFAULT_N_MODULES
    n = int(n_modules if n_modules is not None else DEFAULT_N_MODULES)
    return list(range(1, n))  # servo id i+1 ↔ handoff joint i


# Back-compat for imports / doctor text.
EXPECTED_SIDS = expected_sids()


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
    """Replay a FoldPlan on the real STS3215 chain (ids 1..N-1 for an N-cube robot).

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
        power: int = 3,
        limit_deg: float = DETENT_OUT_DEG,
        mirror_mujoco: bool | None = None,
        scene_xml: str = "",
        n_modules: int | None = None,
        log=print,
    ):
        self.hw_root = hw_root or os.environ.get("CUBOT_HW_ROOT", DEFAULT_HW_ROOT)
        self.serial_port = (serial_port or os.environ.get("CUBOT_SERIAL_PORT", "")).strip()
        self.gear = float(os.environ.get("CUBOT_GEAR", gear) or gear)
        # Prefer the Settings-resolved power arg; only fall back to env if somehow unset.
        try:
            env_p = (os.environ.get("CUBOT_POWER") or "").strip()
            self.power = int(env_p) if env_p != "" else int(power)
        except ValueError:
            self.power = int(power)
        self.limit_deg = float(limit_deg)
        if mirror_mujoco is None:
            mirror_mujoco = _env_bool("CUBOT_MUJOCO_MIRROR", True)
        self.mirror_mujoco = bool(mirror_mujoco)
        self.scene_xml = scene_xml
        from .config import DEFAULT_N_MODULES
        try:
            env_n = (os.environ.get("CUBOT_N_MODULES") or "").strip()
            self.n_modules = int(env_n) if env_n else int(n_modules or DEFAULT_N_MODULES)
        except ValueError:
            self.n_modules = int(n_modules or DEFAULT_N_MODULES)
        self.sids = expected_sids(self.n_modules)
        self.n_joints = len(self.sids)
        self.log = log
        self.submitted: list = []
        self._lock = threading.Lock()
        self._bus = None
        self._axes: list = []
        self._rc = None
        self._sts = None
        self._mujoco = None
        self._store = None
        self._sign = [1] * self.n_joints
        # One 120° detent in motor steps for THIS gear, not the 4:1 constant.
        self._steps_per_state = self.gear * 4096.0 / 3.0
        self._last_targets: dict[int, int] = {}

    # -- bus lifecycle -------------------------------------------------------

    def _open(self) -> None:
        if self._bus is not None:
            return
        rc, sts = _import_driver(self.hw_root)
        self._rc, self._sts = rc, sts
        port = self.serial_port or sts.autodetect_port()
        self.log(f"[hardware] opening bus on {port} (gear={self.gear}, power={self.power})")
        bus = sts.Bus(port)
        found = bus.scan(self.sids)
        missing = [s for s in self.sids if s not in found]
        if missing:
            try:
                bus.close()
            except Exception:
                pass
            raise RuntimeError(
                f"robot offline / incomplete bus: need servos {self.sids[0]}..{self.sids[-1]}, "
                f"missing {missing} (found {found})"
            )
        geo = rc.Geometry(gear=self.gear, limit_deg=self.limit_deg)
        # rc.StateStore dead-reckons each shaft's TURN COUNT across runs. The
        # encoder is absolute within one motor turn only, and a detent is 1.33
        # turns, so a fresh process aligning by nearest wrap loses whole turns
        # on any folded joint — goals and homing then land 90° off at the
        # output. Falls back to the servo's EEPROM center zero (straight =
        # 2048, burned by soft_zero) when a servo has no store entry.
        store = rc.StateStore(str(_calibration_path(TRACK_NAME)))
        axes = [rc.Axis(bus, sid, geo, store) for sid in self.sids]
        for ax in axes:
            # Seed continuous track from the live encoder.
            st = bus.read_state(ax.sid)
            ax.update(st["position"])
            ax.set_power(self.power)
            ax.set_torque(True)
            note = ax.restore_note or ""
            if "DISAGREES" in note or "CHECK IT" in note:
                self.log(f"[hardware] sid {ax.sid}: {note}")
        self._load_signs()
        self._bus = bus
        self._axes = axes
        self._store = store
        store.remember(axes, time.monotonic(), min_interval=0.0)
        self.log(f"[hardware] torque on · {len(axes)} axes · power "
                 f"{rc.power_name(self.power)}")

    def _load_signs(self) -> None:
        path = _calibration_path(SIGNS_NAME)
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            signs = [1 if int(v) >= 0 else -1 for v in raw]
        except (OSError, ValueError) as e:
            self.log(f"[hardware] {SIGNS_NAME} unreadable ({e}); all joints +1")
            return
        if len(signs) != self.n_joints:
            self.log(f"[hardware] {SIGNS_NAME} has {len(signs)} entries, "
                     f"need {self.n_joints}; all joints +1")
            return
        self._sign = signs
        flipped = [j for j, s in enumerate(signs) if s < 0]
        self.log(f"[hardware] joint signs from {path}"
                 + (f" (flipped: {flipped})" if flipped else " (none flipped)"))

    def _close(self) -> None:
        axes, bus = self._axes, self._bus
        if self._store is not None and axes:
            self._store.remember(axes, time.monotonic(), min_interval=0.0)
        self._axes, self._bus = [], None
        self._store = None
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

    def _dest_cont(self, axis, joint: int, state: int) -> int:
        """Continuous encoder target for handoff state in {-1,0,+1}."""
        steps = int(round(int(state) * self._steps_per_state * self._sign[joint]))
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
            if self._store is not None:
                self._store.remember(self._axes, time.monotonic())
            time.sleep(POLL_S)
        arrived = axis.dest is None
        if not arrived:
            axis.stop("timeout")
        if self._store is not None:
            self._store.remember(self._axes, time.monotonic(), min_interval=0.0)
        return arrived

    def _retrim(self, targets: dict[int, int], speed: int) -> None:
        """Re-chase held joints that crept off their detent (wheel hold is a
        zero-speed command, not a position hold)."""
        for j, dest in targets.items():
            ax = self._axes[j]
            try:
                st = self._bus.read_state(ax.sid)
            except Exception:
                continue
            ax.update(st["position"])
            err = dest - ax.cont
            if abs(err) <= TRIM_STEPS:
                continue
            self.log(f"[hardware] trim j{j}: sagged {err:+d} steps — re-chasing")
            ax.go(dest, f"trim j{j}")
            self._chase(ax, 3.0 + abs(err) / max(1.0, speed * LOAD_SPEED_FRACTION), speed)

    def _run_plan(self, plan) -> dict[str, Any]:
        assert self._rc is not None and self._axes
        speed = self._rc.SPEEDS[min(DEFAULT_SPEED_IDX, len(self._rc.SPEEDS) - 1)]
        state = [0] * len(self._axes)
        targets: dict[int, int] = {}
        arrived_all = True
        for m in plan.moves:
            j = int(m.joint)
            if j < 0 or j >= len(self._axes):
                raise ValueError(
                    f"joint {j} out of range 0..{len(self._axes) - 1} "
                    f"(this chain has {len(self._axes) + 1} cubes — the plan needs more)")
            nxt = state[j] + int(m.delta)
            if nxt not in (-1, 0, 1):
                self.log(f"[hardware] clamp j{j} state {state[j]}{m.delta:+d} → "
                         f"{max(-1, min(1, nxt))}")
                nxt = max(-1, min(1, nxt))
            state[j] = nxt
            axis = self._axes[j]
            dest = self._dest_cont(axis, j, state[j])
            wall = hardware_wall_s(abs(int(m.delta)) or 1, float(m.duration_s) or 2.0)
            # The chase drives at `speed`, not the plan's ideal speed, so the
            # timeout must also cover the travel at that rate under load.
            chase_s = abs(dest - axis.cont) / max(1.0, speed * LOAD_SPEED_FRACTION) + SETTLE_S
            timeout = max(wall * 1.35, chase_s * 1.35, float(m.duration_s) or 2.0, 1.0)
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
            targets[j] = dest
            self._retrim(targets, speed)
        self._retrim(targets, speed)
        self._last_targets = dict(targets)
        if self._store is not None:
            self._store.remember(self._axes, time.monotonic(), min_interval=0.0)
        return {
            "executor": self.name,
            "accepted": True,
            "moves": len(plan.moves),
            "formed": arrived_all,
            "final_states": list(state),
        }

    def hold_trim(self, seconds: float) -> None:
        """Keep re-chasing the last commanded pose so it stays crisp on display."""
        targets = dict(self._last_targets)
        if not targets or self._bus is None or self._rc is None:
            return
        speed = self._rc.SPEEDS[min(DEFAULT_SPEED_IDX, len(self._rc.SPEEDS) - 1)]
        deadline = time.monotonic() + max(0.0, float(seconds))
        self.log(f"[hardware] holding pose (trim) for {seconds:.0f}s — ctrl-c to stop")
        while time.monotonic() < deadline:
            with self._lock:
                self._retrim(targets, speed)
            time.sleep(0.5)

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

    def _home_core(self) -> dict:
        """Drive every axis to software home. Caller holds the lock and mutex."""
        assert self._rc is not None and self._axes
        speed = self._rc.SPEEDS[min(DEFAULT_SPEED_IDX, len(self._rc.SPEEDS) - 1)]
        # Snapshot how far we are before chasing — if already home, drive is a no-op.
        start_err = {ax.sid: abs(ax.from_home()) for ax in self._axes}
        max_err = max(start_err.values()) if start_err else 0
        self.log(f"[hardware] homing {len(self._axes)} axes → software zero "
                 f"(max err {max_err} steps)")
        for ax in self._axes:
            ax.go(ax.home, "HOME")
        pending = {ax.sid for ax in self._axes}
        # Enough wall-clock for the farthest axis at the chase speed under load.
        deadline = time.monotonic() + 6.0 + max_err / max(1.0, speed * LOAD_SPEED_FRACTION)
        while pending and time.monotonic() < deadline:
            for ax in self._axes:
                if ax.sid not in pending:
                    continue
                try:
                    st = self._bus.read_state(ax.sid)
                except Exception as e:
                    self.log(f"[hardware] home read failed sid={ax.sid}: {e}")
                    ax.stop("read failed")
                    pending.discard(ax.sid)
                    continue
                ax.update(st["position"])
                if ax.dest is None:
                    pending.discard(ax.sid)
                    continue
                ax.drive(speed)
            if self._store is not None:
                self._store.remember(self._axes, time.monotonic())
            time.sleep(POLL_S)
        timed_out = []
        for ax in self._axes:
            if ax.dest is not None:
                timed_out.append(ax.sid)
                ax.stop("home timeout")
        ok = not timed_out
        self._last_targets = {j: self._axes[j].home for j in range(len(self._axes))}
        if self._store is not None:
            self._store.remember(self._axes, time.monotonic(), min_interval=0.0)
        self.log(
            f"[hardware] home {'ok' if ok else 'partial'} "
            f"max_err_steps={max_err} timed_out={timed_out or '—'}"
        )
        return {
            "executor": self.name,
            "accepted": True,
            "home": True,
            "formed": ok,
            "timed_out": timed_out,
            "hardware_online": True,
            "max_err_steps": max_err,
            "already_home": max_err <= 20,
        }

    def home_all(self, context: dict | None = None) -> dict:
        """Drive every axis to software home (straight chain). Used for 'straight line' texts."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("hardware busy: another fold is in progress")
        try:
            self._claim_mutex()
            self._open()
            return self._home_core()
        finally:
            self._release_mutex()
            self._lock.release()

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

            # Fold plans assume every joint starts at state 0. If the chain is
            # still bent (a prior fold, sag, a crash mid-shape), home it first
            # rather than folding garbage on top.
            bent = max((abs(ax.from_home()) for ax in self._axes), default=0)
            if bent > 2 * TRIM_STEPS:
                self.log(f"[hardware] chain not straight (max {bent} steps from home) "
                         f"— homing before the fold")
                home_res = self._home_core()
                if not home_res.get("formed"):
                    self.log("[hardware]   ! pre-fold homing incomplete "
                             f"(timed_out={home_res.get('timed_out')})")

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

    # -- operator / keep-alive ------------------------------------------------

    def _bus_alive(self) -> bool:
        if self._bus is None or not self._axes:
            return False
        try:
            self._bus.read_state(self._axes[0].sid)
            return True
        except Exception:
            return False

    def ensure_ready(self) -> dict[str, Any]:
        """Open (or reopen) the bus and leave it held. Safe to call repeatedly."""
        with self._lock:
            if self._bus is not None and not self._bus_alive():
                self.log("[hardware] bus handle dead — reopening")
                self._close()
            try:
                self._open()
            except Exception as e:
                return {"ok": False, "online": False, "error": str(e)}
            return {
                "ok": True,
                "online": True,
                "axes": len(self._axes),
                "power": self.power,
                "port": getattr(getattr(self._bus, "port", None), "port", None)
                        or self.serial_port or "",
            }

    def read_states(self) -> dict[str, Any]:
        """Snapshot present position / from_home for every held axis. No motion."""
        with self._lock:
            if self._bus is None or not self._bus_alive():
                try:
                    self._open()
                except Exception as e:
                    return {"ok": False, "online": False, "error": str(e), "servos": []}
            assert self._sts is not None
            servos = []
            for ax in self._axes:
                try:
                    st = self._bus.read_state(ax.sid)
                    ax.update(st["position"])
                    pos = int(st["position"])
                    servos.append({
                        "sid": ax.sid,
                        "present_position": pos,
                        "degrees": round(self._sts.steps_to_deg(pos % 4096), 2),
                        "from_home": int(ax.from_home()),
                        "voltage": st.get("voltage"),
                    })
                except Exception as e:
                    servos.append({"sid": ax.sid, "error": str(e)})
            return {
                "ok": True,
                "online": True,
                "power": self.power,
                "servos": servos,
            }

    def soft_zero(self) -> dict[str, Any]:
        """Redefine software home at the current pose (no motion) and persist JSON."""
        import json
        from pathlib import Path
        from .homes import homes_path  # noqa: PLC0415

        with self._lock:
            if self._bus is None or not self._bus_alive():
                try:
                    self._open()
                except Exception as e:
                    return {"ok": False, "online": False, "error": str(e)}
            assert self._sts is not None and self._rc is not None
            homes_rows: dict[str, Any] = {}
            ids: list[int] = []
            for ax in self._axes:
                st = self._bus.read_state(ax.sid)
                ax.update(st["position"])
                ax.set_zero()
                # set_zero burns EEPROM center-cal: this pose now READS
                # ~2048. Snapshot the relabeled frame, not the old one, or
                # every later session aims half a motor turn off.
                st = self._bus.read_state(ax.sid)
                ax.update(st["position"])
                ids.append(ax.sid)
                homes_rows[str(ax.sid)] = {
                    "present_position": int(st["position"]),
                    "degrees_reported": round(
                        self._sts.steps_to_deg(st["position"] % 4096), 2),
                    "cont_at_home": int(ax.cont),
                    "home": int(ax.home),
                }
            # Also capture tip / spare sids past the fold chain when present.
            tip = self.n_modules
            if tip not in self.sids:
                try:
                    extra = self._bus.scan([tip])
                except Exception:
                    extra = []
            else:
                extra = []
            extras: list = []
            for sid in extra:
                if sid in ids:
                    continue
                try:
                    ax = self._rc.Axis(self._bus, sid,
                                       self._rc.Geometry(self.gear, self.limit_deg))
                    st = self._bus.read_state(sid)
                    ax.update(st["position"])
                    ax.set_zero()
                    st = self._bus.read_state(sid)
                    ax.update(st["position"])
                    extras.append(ax)
                    ids.append(sid)
                    homes_rows[str(sid)] = {
                        "present_position": int(st["position"]),
                        "degrees_reported": round(
                            self._sts.steps_to_deg(st["position"] % 4096), 2),
                        "cont_at_home": int(ax.cont),
                        "home": int(ax.home),
                    }
                except Exception as e:
                    self.log(f"[hardware] soft-zero sid={sid} skipped: {e}")
            out_path = Path(homes_path())
            doc = {
                "schema": "cubot.software_homes.v1",
                "description": (
                    "Encoder snapshot of the straight-chain pose. The fold pipeline still "
                    "commands state 0 / 0 deg / go(home) — never raw present_position as zero. "
                    "On connect, Axis.home is aligned to this snapshot so from_home()==0 on "
                    "the straight line. Recapture only with the chain physically straight."
                ),
                "pipeline_contract": {
                    "handoff_state_0": "software home (straight line)",
                    "command": "axis.go(axis.home) or home + state*steps",
                },
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "port": self.serial_port or "",
                "servo_ids": ids,
                "homes": homes_rows,
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2)
                f.write("\n")
            if self._store is not None:
                # A fresh zero resets every turn count; stale dead-reckoning
                # from before the zero must not survive it.
                self._store.remember(self._axes + extras, time.monotonic(),
                                     min_interval=0.0)
            self._last_targets = {}
            self.log(f"[hardware] soft-zeroed {len(ids)} axes → {out_path} (no motion)")
            return {
                "ok": True,
                "online": True,
                "path": str(out_path),
                "servo_ids": ids,
                "homes": homes_rows,
            }

    def nudge_joint(self, joint: int, deg: float = DETENT_OUT_DEG,
                    pause_s: float = 2.0) -> dict[str, Any]:
        """Fold one joint to +deg output and back — the operator's calibration
        probe for direction (does + go the way the sim's + goes?) and for the
        true output angle (is the gear ratio right?)."""
        if not 0 <= joint < self.n_joints:
            raise ValueError(f"joint {joint} out of range 0..{self.n_joints - 1}")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("hardware busy: another fold is in progress")
        try:
            self._claim_mutex()
            self._open()
            assert self._rc is not None
            speed = self._rc.SPEEDS[min(DEFAULT_SPEED_IDX, len(self._rc.SPEEDS) - 1)]
            ax = self._axes[joint]
            st = self._bus.read_state(ax.sid)
            ax.update(st["position"])
            start_cont = ax.cont
            steps = int(round(self._sign[joint] * float(deg) / DETENT_OUT_DEG
                              * self._steps_per_state))
            wall = 3.0 + abs(steps) / max(1.0, speed * LOAD_SPEED_FRACTION)
            out: dict[str, Any] = {
                "joint": joint, "sid": ax.sid, "deg": float(deg),
                "sign": self._sign[joint], "steps": steps,
                "start_from_home": int(ax.from_home()),
            }
            self.log(f"[hardware] test j{joint} (sid {ax.sid}): "
                     f"{deg:+g}° output = {steps:+d} steps")
            ax.go(start_cont + steps, f"test j{joint} out")
            out["out_arrived"] = self._chase(ax, wall * 1.35, speed)
            st = self._bus.read_state(ax.sid)
            ax.update(st["position"])
            out["moved_steps"] = int(ax.cont - start_cont)
            out["moved_deg_out"] = round((ax.cont - start_cont)
                                         / self._steps_per_state * DETENT_OUT_DEG, 1)
            self.log(f"[hardware]   moved {out['moved_steps']:+d} steps "
                     f"≈ {out['moved_deg_out']:+.1f}° output — check it by eye")
            time.sleep(max(0.0, float(pause_s)))
            ax.go(start_cont, f"test j{joint} back")
            out["back_arrived"] = self._chase(ax, wall * 1.35, speed)
            st = self._bus.read_state(ax.sid)
            ax.update(st["position"])
            out["end_from_home"] = int(ax.from_home())
            if self._store is not None:
                self._store.remember(self._axes, time.monotonic(), min_interval=0.0)
            return out
        finally:
            self._release_mutex()
            self._lock.release()
