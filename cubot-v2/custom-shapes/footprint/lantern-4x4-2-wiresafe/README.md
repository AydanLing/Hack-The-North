# lantern-4x4-2-wiresafe

The same hollow 4×4×3 lantern as `../lantern-4x4-2`, reached by a **different 15-move route that protects wires
leaving module 27** (the tail) through its outer face. The tail is allowed to move. Its wires must never be enclosed or
squished.

## Wire rules (all hold for every move)

1. **Keep-out zone:** an 80 × 50 × 50 mm box off module 27's outer face. No other module enters it at any point of
   any swing (MuJoCo URDF-mesh sweep, re-checked at 2° steps: 0.00 mm intrusion).
2. **Never enclosed:** at every rest pose, the straight line out of that face is clear to the outside of the shape.
3. **Not pressed into the table:** the keep-out zone never touches the table, during swings or at rest.

## How it was found

A physics-in-the-loop beam search. Every candidate move was simulated in MuJoCo (free base, gravity, 5.8 N·m servo
cap) from the chain's actual physical state. That matters because physics, not the planner, decides which half swings,
so the chain's orientation on the table is only known by simulating. A move was kept only if, in **three worlds at once**
(floor friction 0.30 / 0.35 / 0.45), its servo reached the detent within its 2.75 s slot and the wire zone kept
≥ 3 mm from every module and ≥ 5 mm from the table. The finished lantern was also held for 2 s.

Why so strict: a first version that passed one exact simulation drifted from move 4 onward when replayed, and ended
with the wires 66 mm into the table. Multi-body contact is chaotic, so single-run results are not trustworthy.

## Validation: continuous replay (`model/cubot/play_path.py --wire-end 27`), 5.8 N·m

| floor friction | formed | worst joint | closest module to wire zone | wire zone above table | time at cap | late moves |
|---|---|---:|---:|---:|---:|---:|
| 0.30 | yes | 0.7° | 16.3 mm | 9.4 mm | 0 s | 0 |
| 0.35 (vinyl, assumed) | yes | 0.7° | 16.1 mm | 9.2 mm | 0 s | 0 |
| 0.40 (not searched) | yes | 0.7° | 16.3 mm | 9.0 mm | 0 s | 0 |
| 0.45 | yes | 0.7° | 16.1 mm | 8.4 mm | 0 s | 0 |
| 0.50 (not searched) | yes | 0.8° | 16.8 mm | 8.3 mm | 0 s | 0 |

Servo order (1-based servo, detent): 5+, 22−, 24−, 8−, 6+, 10+, 4+, 23−, 14−, 11+, 17−, 13−, 25+, 2+, 20+.

```
python model/cubot/play_path.py --friction 0.35 --wire-end 27 cubot-v2/custom-shapes/footprint/lantern-4x4-2-wiresafe/path.json
```

## Limits

- The keep-out box size (80 × 50 × 50 mm) is an assumption. Change it in `play_path.py` / the search if the real
  bundle differs.
- Simulated only: the real robot will differ more than these worlds do. The margins (≥ 8 mm table, ≥ 16 mm modules)
  are the buffer.
- `side` in `path.json` is the planner's guess; physics chooses the swinging half.
- The route in `../lantern-4x4-2/path.json` is **not** wire-safe: modules enter the zone by 23.5 mm, and the wires
  end pressed into the table.
