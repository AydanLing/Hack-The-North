"""Replay a CuBot handoff path in MuJoCo using the *real* STS3215 + 4:1 numbers.

Timing and torque come from Jerry's snake_pipeline hardware contract, not demo fudge factors:

* Feetech STS3215 through a 1:4 planetary → one 120° state = ``4 * 4096 / 3 ≈ 5461`` motor steps
  (``firmware/HARDWARE.md``, ``loads.ServoSpec``).
* Bus Goal_Speed capped at 3000 steps/s, acc=100, settle 0.3 s (``robot_config.json`` /
  ``robot.speed_for_move`` / ``robot.move_time_estimate``).
* Under morph load the servo runs ~65 % of that commanded speed (review finding on
  torque–speed droop) — that is what the wall-clock pacing uses, so a "2.0 s" plan step
  actually takes ~3 s on screen, like the physical chain.
* Hinge stall = ``machine.stall_torque_nm`` (10.6 N·m = 2.94 × 4 × 0.9 at 12 V). Force limit
  in MuJoCo is that stall, not an invented 40 N·m.
* Module mass stays whatever the MJCF was built with (0.250 kg in ``cubot_urdf``; path.json
  records 0.223 — same order; we do not reskin the mesh mid-demo).

    mjpython -m cubot_imessage.mujoco_replay --path cubot-v2/handoff-17/shapes/01-heart/path.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Optional, Sequence

DETENT_RAD = {-1: -math.radians(120.0), 0: 0.0, 1: math.radians(120.0)}
DEFAULT_SCENE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cubot_urdf", "n17", "scene.xml",
)

# ---- snake_pipeline / HARDWARE.md / robot_config.json ---------------------------------
GEAR_RATIO = 4.0
MOTOR_STEPS_PER_TURN = 4096
STEPS_PER_STATE = GEAR_RATIO * MOTOR_STEPS_PER_TURN / 3.0          # 5461.333…
MAX_SPEED_STEPS_S = 3000                                           # robot_config.json
ACC_REGISTER = 100                                                 # Feetech Acceleration register
SETTLE_S = 0.3                                                     # robot_config settle_s
# Loaded morph speed vs Goal_Speed (snake_pipeline review: ~65 % of no-load under gravity).
LOAD_SPEED_FRACTION = 0.65
DEFAULT_STALL_NM = 10.6                                            # STS3215@12V × 4 × 0.9
DEFAULT_MOVE_S = 2.0                                               # machine.move_time_s
DEFAULT_MASS_KG = 0.223                                            # machine.mass_kg_per_module (MJCF was 0.250)


def speed_for_move(delta_steps: float, seconds: float,
                   acc: int = ACC_REGISTER, max_speed: int = MAX_SPEED_STEPS_S) -> int:
    """Same trapezoid solve as snakeshape.robot.speed_for_move."""
    d = abs(float(delta_steps))
    seconds = max(float(seconds), 0.05)
    a = 100.0 * max(int(acc), 0)
    if d == 0:
        return min(max_speed, 200)
    if a <= 0:
        v = d / seconds
    else:
        disc = a * a * seconds * seconds - 4.0 * a * d
        v = (a * seconds - math.sqrt(disc)) / 2.0 if disc >= 0 else float(max_speed)
    return int(round(min(max(v, 10.0), float(max_speed))))


def move_time_estimate(delta_steps: float, speed: int, acc: int = ACC_REGISTER) -> float:
    """Same estimate as snakeshape.robot.move_time_estimate."""
    d = abs(float(delta_steps))
    v = max(float(speed), 1.0)
    a = 100.0 * max(int(acc), 0)
    if d == 0:
        return 0.0
    if a <= 0:
        return d / v
    if d < v * v / a:
        return 2.0 * math.sqrt(d / a)
    return d / v + v / a


def hardware_wall_s(delta_states: int, planned_duration_s: float,
                    load_fraction: float = LOAD_SPEED_FRACTION) -> float:
    """Wall-clock seconds one detent should take on the real bus under load."""
    steps = abs(int(delta_states)) * STEPS_PER_STATE
    planned = max(float(planned_duration_s), 0.05)
    goal = speed_for_move(steps, planned, ACC_REGISTER, MAX_SPEED_STEPS_S)
    effective = max(10, int(round(goal * load_fraction)))
    return move_time_estimate(steps, effective, ACC_REGISTER) + SETTLE_S


def _load_path(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _machine_limits(doc: dict) -> tuple[float, float, float]:
    """(stall_nm, default_move_s, mass_kg_per_module) from path.json's machine block."""
    machine = doc.get("machine") or {}
    stall = float(machine.get("stall_torque_nm") or DEFAULT_STALL_NM)
    move_s = float(machine.get("move_time_s") or DEFAULT_MOVE_S)
    mass = float(machine.get("mass_kg_per_module") or DEFAULT_MASS_KG)
    return stall, move_s, mass


def _servo_ids(model) -> tuple[list[int], list[int]]:
    """Discover servo01..servoNN actuators present in the MJCF (N-generic)."""
    import mujoco
    addrs, acts = [], []
    i = 1
    while True:
        name = f"servo{i:02d}"
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
        if jid < 0 or aid < 0:
            break
        addrs.append(int(model.jnt_qposadr[jid]))
        acts.append(int(aid))
        i += 1
    if not addrs:
        raise RuntimeError("no servo01.. actuators found in the MJCF")
    return addrs, acts


def _pad_states(states: Sequence[int], n: int) -> list[int]:
    out = [int(s) for s in states]
    if len(out) < n:
        out.extend([0] * (n - len(out)))
    return out[:n]


def _states_from_qpos(data, addrs: Sequence[int]) -> list[int]:
    out = []
    for adr in addrs:
        q = float(data.qpos[adr])
        out.append(min(DETENT_RAD, key=lambda s: abs(DETENT_RAD[s] - q)))
    return out


def _set_all_ctrl(data, acts: Sequence[int], states: Sequence[int]) -> None:
    for aid, state in zip(acts, states):
        data.ctrl[aid] = DETENT_RAD[int(state)]


def _apply_hardware_actuators(model, stall_nm: float, mass_kg: float) -> None:
    """Force limit = real hinge stall; retarget body mass to path.json's per-cube weight.

    cubot_shipped.xml splits each module into still+moving halves at 0.125 kg each (0.250 kg
    total). snake_pipeline / handoff machine block uses 0.223 kg — scale inertias with mass so
    gravity moments match the planner.
    """
    import numpy as np
    model.actuator_forcerange[:] = np.array([-stall_nm, stall_nm])
    model.actuator_forcelimited[:] = 1
    # Module bodies are still/moving pairs; ignore free-floating helper geoms with tiny mass.
    masses = np.array(model.body_mass, dtype=float)
    # Average mass of the 0.125-ish half-bodies; scale so two halves ≈ mass_kg.
    half_ids = [i for i, m in enumerate(masses) if 0.05 < m < 0.4]
    if half_ids:
        current_half = float(np.mean(masses[half_ids]))
        target_half = float(mass_kg) / 2.0
        scale = target_half / current_half if current_half > 0 else 1.0
        for i in half_ids:
            model.body_mass[i] = masses[i] * scale
            model.body_inertia[i] = model.body_inertia[i] * scale


def _settle(model, data, viewer, seconds: float) -> None:
    import mujoco
    deadline = time.perf_counter() + seconds
    while viewer.is_running() and time.perf_counter() < deadline:
        step_start = time.perf_counter()
        mujoco.mj_step(model, data)
        viewer.sync()
        leftover = model.opt.timestep - (time.perf_counter() - step_start)
        if leftover > 0:
            time.sleep(leftover)
        if float((data.qvel ** 2).sum()) < 1e-4 and time.perf_counter() > deadline - seconds + 0.3:
            break


def _drive_joint(model, data, viewer, acts: Sequence[int], joint: int,
                 start_rad: float, end_rad: float, duration_s: float) -> None:
    """Ramp the position target over the hardware wall-clock, physics stepping underneath."""
    import mujoco
    if duration_s <= 0:
        data.ctrl[acts[joint]] = end_rad
        return
    t0 = time.perf_counter()
    while viewer.is_running():
        step_start = time.perf_counter()
        u = min(1.0, (step_start - t0) / duration_s)
        # Cosine ease — same family as loads.omega_max / the planner's eased torque profile.
        s = 0.5 - 0.5 * math.cos(math.pi * u)
        data.ctrl[acts[joint]] = start_rad + (end_rad - start_rad) * s
        mujoco.mj_step(model, data)
        viewer.sync()
        leftover = model.opt.timestep - (time.perf_counter() - step_start)
        if leftover > 0:
            time.sleep(leftover)
        if u >= 1.0:
            break
    data.ctrl[acts[joint]] = end_rad


def replay(path_json: str, scene_xml: str = DEFAULT_SCENE, speed: float = 1.0,
           hold_s: float = 8.0, title: str = "",
           load_fraction: float = LOAD_SPEED_FRACTION) -> int:
    import mujoco
    import mujoco.viewer
    import numpy as np

    doc = _load_path(path_json)
    name = str(doc.get("name") or os.path.basename(os.path.dirname(path_json)))
    moves = doc.get("moves") or []
    if not moves:
        print(f"no moves in {path_json}", file=sys.stderr)
        return 2
    if not os.path.isfile(scene_xml):
        print(f"scene not found: {scene_xml}", file=sys.stderr)
        return 2

    speed = max(0.05, float(speed))          # 1.0 = realtime vs hardware estimate
    load_fraction = min(1.0, max(0.2, float(load_fraction)))
    stall_nm, default_move_s, mass_kg = _machine_limits(doc)

    model = mujoco.MjModel.from_xml_path(scene_xml)
    data = mujoco.MjData(model)
    _apply_hardware_actuators(model, stall_nm, mass_kg)
    addrs, acts = _servo_ids(model)
    n_servos = len(acts)

    mujoco.mj_resetData(model, data)
    _set_all_ctrl(data, acts, _pad_states([0] * n_servos, n_servos))
    mujoco.mj_forward(model, data)

    # Precompute wall times so the banner is honest.
    walls = []
    for move in moves:
        planned = float(move.get("duration_s") or default_move_s)
        delta_states = abs(int(move.get("delta") or 1))
        walls.append(hardware_wall_s(delta_states, planned, load_fraction) / speed)
    total = sum(walls)

    print(f"[mujoco] {title or f'CuBot · {name}'}: {len(moves)} moves, ~{total:.0f}s wall-clock",
          flush=True)
    print(f"[mujoco] hardware: STS3215×{GEAR_RATIO:g}:1, stall ±{stall_nm:.1f} N·m, "
          f"{mass_kg:.3f} kg/cube, bus ≤{MAX_SPEED_STEPS_S} steps/s, "
          f"load×{load_fraction:.2f}, settle {SETTLE_S}s",
          flush=True)
    print("[mujoco] physics ON (gravity + floor contacts). close the window to stop", flush=True)

    with mujoco.viewer.launch_passive(model, data) as viewer:
        try:
            viewer.cam.azimuth = 140
            viewer.cam.elevation = -20
            viewer.cam.distance = 3.5
            viewer.cam.lookat[:] = np.array([1.07, 0.0, 0.12])
        except Exception:
            pass

        print("[mujoco] settling on the table…", flush=True)
        _settle(model, data, viewer, seconds=max(SETTLE_S, 1.5))

        for step, (move, duration) in enumerate(zip(moves, walls), 1):
            if not viewer.is_running():
                break
            joint = int(move["joint"])
            before = int(move.get("state_before", 0))
            after = int(move.get("state_after", before + int(move.get("delta", 0))))
            planned = float(move.get("duration_s") or default_move_s)
            print(f"[mujoco] step {step}/{len(moves)}  j{joint} {before:+d}→{after:+d}  "
                  f"side={move.get('side', '?')}  "
                  f"plan {planned:.1f}s → wall {duration:.1f}s", flush=True)

            current = _pad_states(_states_from_qpos(data, addrs), n_servos)
            if joint < 0 or joint >= n_servos:
                raise ValueError(f"joint {joint} out of range 0..{n_servos - 1}")
            current[joint] = before
            _set_all_ctrl(data, acts, current)
            # Motion portion of the wall time; settle is applied after.
            motion = max(0.2, duration - SETTLE_S / speed)
            _drive_joint(model, data, viewer, acts, joint,
                         DETENT_RAD[before], DETENT_RAD[after], motion)
            _settle(model, data, viewer, seconds=SETTLE_S / speed)

        print("[mujoco] fold finished — orbit with the mouse, close window to exit", flush=True)
        hold_until = time.perf_counter() + max(0.0, hold_s)
        while viewer.is_running() and time.perf_counter() < hold_until:
            step_start = time.perf_counter()
            mujoco.mj_step(model, data)
            viewer.sync()
            leftover = model.opt.timestep - (time.perf_counter() - step_start)
            if leftover > 0:
                time.sleep(leftover)
        while viewer.is_running():
            step_start = time.perf_counter()
            mujoco.mj_step(model, data)
            viewer.sync()
            leftover = model.opt.timestep - (time.perf_counter() - step_start)
            if leftover > 0:
                time.sleep(leftover)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Replay a CuBot path in MuJoCo at hardware timing.")
    p.add_argument("--path", required=True)
    p.add_argument("--scene", default=DEFAULT_SCENE)
    p.add_argument("--speed", type=float, default=1.0,
                   help="1.0 = realtime vs STS3215 bus estimate; 0.5 = half that")
    p.add_argument("--load-fraction", type=float, default=LOAD_SPEED_FRACTION,
                   help="effective Goal_Speed under gravity (default 0.65 from snake_pipeline review)")
    p.add_argument("--hold", type=float, default=12.0)
    p.add_argument("--title", default="")
    args = p.parse_args(argv)
    try:
        return replay(args.path, args.scene, args.speed, args.hold, args.title, args.load_fraction)
    except Exception as e:
        print(f"[mujoco] failed: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
