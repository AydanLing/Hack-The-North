#!/usr/bin/env python3
"""Open the n17 chain in the MuJoCo viewer.

`mjpython -m mujoco.viewer --mjcf ...` crashes in mujoco 3.13; launch_passive works.

    mjpython cubot_urdf/view_n17.py
    mjpython cubot_urdf/view_n17.py --scene cubot_urdf/n11/scene.xml
    mjpython cubot_urdf/view_n17.py --states 0,0,-1,0,1,1,0,1,0,0,0,1,0,0,-1,0
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import mujoco
import mujoco.viewer

ROOT = Path(__file__).resolve().parent
DETENT = {-1: -math.radians(120.0), 0: 0.0, 1: math.radians(120.0)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene", type=Path, default=ROOT / "n17" / "scene.xml")
    p.add_argument("--states", default="", help="comma-separated joint states in {-1,0,1}")
    p.add_argument("--no-gravity", action="store_true", help="freeze the chain as authored")
    args = p.parse_args()

    model = mujoco.MjModel.from_xml_path(str(args.scene))
    data = mujoco.MjData(model)
    if args.no_gravity:
        model.opt.gravity[:] = 0

    acts = []
    index = 1
    while True:
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"servo{index:02d}")
        if aid < 0:
            break
        acts.append(aid)
        index += 1
    print(f"{args.scene}: {len(acts)} servos")

    states = [0] * len(acts)
    if args.states:
        given = [int(v) for v in args.states.replace(" ", "").split(",") if v]
        for i, v in enumerate(given[: len(acts)]):
            states[i] = v
        print("states", states)

    mujoco.mj_resetData(model, data)
    for aid, state in zip(acts, states):
        data.ctrl[aid] = DETENT[int(state)]
    mujoco.mj_forward(model, data)

    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.azimuth = 140
        viewer.cam.elevation = -25
        viewer.cam.distance = 2.6
        viewer.cam.lookat[:] = [0.7, 0.0, 0.1]
        while viewer.is_running():
            mujoco.mj_step(model, data)
            viewer.sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
