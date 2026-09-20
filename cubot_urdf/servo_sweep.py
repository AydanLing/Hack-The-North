#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mujoco>=3.1"]
# ///
"""Sweep every CuBot servo to +120 deg and back.

Loads scene.xml (floor + the 27-module chain from cubot_shipped.xml) and, one
servo at a time, ramps its position actuator 0 -> +120 deg -> 0 with a cosine
ease, then prints how close the joint actually got and how well it returned.

    uv run servo_sweep.py                 # headless physics sweep, prints a report
    uv run servo_sweep.py --view          # same, watched live in the MuJoCo viewer
                                          # (macOS: uv run --with mujoco mjpython servo_sweep.py --view)
    uv run servo_sweep.py --strong        # idealized servos: force cap removed
    uv run servo_sweep.py --kinematic     # pose-only animation, no physics
    uv run servo_sweep.py --together      # all 27 at once instead of one at a time
    uv run servo_sweep.py --servos 1,5-9  # subset
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import mujoco

DEFAULT_TARGET_DEG = 120.0
DEFAULT_MOVE_TIME_S = 2.0  # machine.json move_time_s
HOLD_S = 0.3
PAUSE_S = 0.2
SETTLE_S = 1.0


def parse_servo_list(spec: str, count: int) -> list[int]:
    """'1,5-9,27' -> [1, 5, 6, 7, 8, 9, 27] (1-based, validated)."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    bad = [n for n in out if not 1 <= n <= count]
    if bad:
        sys.exit(f"servo numbers out of range 1..{count}: {bad}")
    return sorted(set(out))


def ease(t: float, duration: float) -> float:
    """Cosine ease 0 -> 1 over duration."""
    if t <= 0.0:
        return 0.0
    if t >= duration:
        return 1.0
    return 0.5 * (1.0 - math.cos(math.pi * t / duration))


def profile(t: float, move_time: float) -> float:
    """0 -> 1 -> hold -> 0 fraction of the target over one full sweep."""
    if t < move_time:
        return ease(t, move_time)
    if t < move_time + HOLD_S:
        return 1.0
    return 1.0 - ease(t - move_time - HOLD_S, move_time)


def sweep_duration(move_time: float) -> float:
    return 2.0 * move_time + HOLD_S


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", type=Path, default=Path(__file__).parent / "scene.xml")
    ap.add_argument("--deg", type=float, default=DEFAULT_TARGET_DEG,
                    help=f"target angle in degrees (default {DEFAULT_TARGET_DEG:g})")
    ap.add_argument("--move-time", type=float, default=DEFAULT_MOVE_TIME_S,
                    help=f"seconds for each 0->target ramp (default {DEFAULT_MOVE_TIME_S:g})")
    ap.add_argument("--servos", default="",
                    help="which servos, e.g. '1,5-9,27' (default: all)")
    ap.add_argument("--together", action="store_true",
                    help="sweep every servo simultaneously instead of one at a time")
    ap.add_argument("--strong", action="store_true",
                    help="remove the 5.8 N*m force cap (idealized servos)")
    ap.add_argument("--kinematic", action="store_true",
                    help="set joint angles directly, no physics (implies every servo reaches the target)")
    ap.add_argument("--view", action="store_true",
                    help="watch live in the MuJoCo viewer (paced to real time)")
    args = ap.parse_args()

    model = mujoco.MjModel.from_xml_path(str(args.model))
    data = mujoco.MjData(model)

    # Actuators named servoNN, in order, with their joints' qpos addresses.
    servos = []  # (number, actuator_id, qpos_adr)
    for i in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        if name and name.startswith("servo"):
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            servos.append((int(name[5:]), i, model.jnt_qposadr[jid]))
    servos.sort()
    if not servos:
        sys.exit(f"no servo actuators found in {args.model}")

    if args.servos:
        wanted = set(parse_servo_list(args.servos, servos[-1][0]))
        servos = [s for s in servos if s[0] in wanted]

    target = math.radians(args.deg)
    lo, hi = model.actuator_ctrlrange[servos[0][1]]
    if not lo <= target <= hi:
        sys.exit(f"{args.deg:g} deg is outside the servo ctrlrange "
                 f"[{math.degrees(lo):.1f}, {math.degrees(hi):.1f}] deg")

    if args.strong:
        # Idealized servos: no force cap, and stiff enough not to droop under
        # the weight of the chain (stock kp=30 sags several degrees mid-chain).
        for _, act_id, _ in servos:
            model.actuator_forcerange[act_id] = [-1e6, 1e6]
            model.actuator_gainprm[act_id][0] = 2000.0          # kp
            model.actuator_biasprm[act_id][1:3] = [-2000.0, -200.0]  # -kp, -kv

    viewer = None
    if args.view:
        from mujoco import viewer as viewer_mod
        try:
            viewer = viewer_mod.launch_passive(model, data)
        except RuntimeError as exc:  # macOS: the viewer only runs under mjpython
            sys.exit(f"{exc}\n\nOn macOS run the viewer with:\n"
                     f"  uv run --with 'mujoco>=3.1' mjpython {Path(__file__).name} --view")

    def advance(set_ctrl_or_qpos) -> None:
        """One tick: apply commands, then step (or just recompute poses)."""
        set_ctrl_or_qpos()
        if args.kinematic:
            mujoco.mj_forward(model, data)
            data.time += model.opt.timestep
        else:
            mujoco.mj_step(model, data)
        if viewer is not None:
            if not viewer.is_running():
                sys.exit("viewer closed")
            viewer.sync()
            time.sleep(model.opt.timestep)

    def run_for(seconds: float, set_ctrl_or_qpos) -> None:
        for _ in range(int(round(seconds / model.opt.timestep))):
            advance(set_ctrl_or_qpos)

    def command(active: list[tuple[int, int, int]], value: float) -> None:
        for _, act_id, qadr in active:
            if args.kinematic:
                data.qpos[qadr] = value
            else:
                data.ctrl[act_id] = value

    if not args.kinematic:
        run_for(SETTLE_S, lambda: None)  # let the chain settle on the floor

    def sweep(active: list[tuple[int, int, int]]) -> tuple[float, float]:
        """Run one full 0 -> target -> 0 sweep; return (peak, final) deg reached."""
        duration = sweep_duration(args.move_time)
        start = data.time
        peak = 0.0
        while data.time - start < duration:
            frac = profile(data.time - start, args.move_time)
            advance(lambda: command(active, frac * target))
            peak = max(peak, max(data.qpos[qadr] for _, _, qadr in active))
        command(active, 0.0)
        run_for(PAUSE_S, lambda: None)
        final = max(abs(data.qpos[qadr]) for _, _, qadr in active)
        return math.degrees(peak), math.degrees(final)

    mode = "kinematic" if args.kinematic else ("strong" if args.strong else "physics")
    print(f"{len(servos)} servo(s), 0 -> {args.deg:+g} deg -> 0, "
          f"{args.move_time:g} s each way, mode: {mode}")

    if args.together:
        peak, final = sweep(servos)
        print(f"all together: peak {peak:7.2f} deg, back to within {final:.3f} deg")
    else:
        for num, act_id, qadr in servos:
            peak, final = sweep([(num, act_id, qadr)])
            note = ""
            if peak < args.deg - 1.0 or final > 5.0:
                note = ("  <-- fell short" if args.strong else
                        "  <-- fell short (5.8 N*m cap; try --strong)")
            print(f"servo{num:02d}: peak {peak:7.2f} deg, "
                  f"back to within {final:.3f} deg{note}")

    if viewer is not None:
        viewer.close()


if __name__ == "__main__":
    main()
