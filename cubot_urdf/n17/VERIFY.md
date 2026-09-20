# Verify n17 URDF against the physical chain

Sim / handoff assume **17 cubes**, wire-end = **cube 1**, tip = cube 17.

## Files to open

| What | Path |
|------|------|
| MuJoCo scene (open this) | `cubot_urdf/n17/scene.xml` |
| Chain MJCF | `cubot_urdf/n17/cubot_shipped.xml` |
| URDF | `cubot_urdf/n17/cubot_shipped.urdf` |
| Planner machine | `cubot-v2/config/machine-17.toml` |

## Quick checks in person

1. **Count** cubes from the **wire / tether end** toward the tip → **17**.
2. **Roll word** (joint chirality 0–3), wire → tip, 16 joints:

```
cube:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17
roll:    1  2  0  0  1  3  0  0  1  3  3  1  0  1  2  3
```

   Same string: `1200130013310123` (first 16 digits of the full 26-cube roll).

3. **Pitch** in sim: 82 mm (80 mm side + 2 mm gap).
4. **Servos in URDF**: `servo01` … `servo17` (fold joints used by paths are `0..15` ↔ sids `1..16`).

## View the straight chain in MuJoCo

```bash
mjpython -m mujoco.viewer --mjcf cubot_urdf/n17/scene.xml
```

Or replay a path:

```bash
cd imessage
PYTHONPATH=. mjpython -m cubot_imessage.mujoco_replay \
  --path ../cubot-v2/handoff-17/shapes/05-L/path.json \
  --scene ../cubot_urdf/n17/scene.xml \
  --speed 2
```

If the physical chirality at any joint disagrees with the roll digit above, tell the operator — paths will fight the hardware.
