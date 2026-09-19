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

Moves 1–14 take 2.0 s each. Move 15 takes **3.0 s**, to soften the final face-to-face landing (see below).

| floor friction | formed | worst joint | closest module to wire zone | wire zone above table | time at cap | late moves |
|---|---|---:|---:|---:|---:|---:|
| 0.30 | yes | 0.7° | 17.4 mm | 9.4 mm | 0 s | 0 |
| 0.35 (vinyl, assumed) | yes | 0.7° | 17.2 mm | 9.2 mm | 0 s | 0 |
| 0.40 (not searched) | yes | 0.7° | 16.9 mm | 9.0 mm | 0 s | 0 |
| 0.45 | yes | 0.7° | 17.0 mm | 8.4 mm | 0 s | 0 |
| 0.50 (not searched) | yes | 0.7° | 17.2 mm | 8.3 mm | 0 s | 0 |

## Clipping check: corners never pass through each other

**Certified sweep.** Every move was swept with exact convex distances between every rotating part and every static
part (official URDF meshes, which enclose the printed CAD hulls). The step was bounded so that no point can outrun the
current clearance: step ≤ clearance / distance from the hinge. This proves no contact at *any* angle, not only at
sampled angles. Results, with ideal joint angles:

| pair type | closest approach |
|---|---:|
| neighbouring modules (corner past corner, about 9° from either end of every swing) | **1.63 mm** |
| modules far apart along the chain (the chain folding onto itself) | **1.6 mm** (moves 12, 14) |
| spacer plate against the rotating half of the next module (designed flush contact) | 0.26 mm overlap, constant from rest; never deepens while turning (URDF spacer box is slightly thicker than the gap) |

**Physics.** No module-to-module contact during any swing, except one. At the end of move 15, modules 10 and 25
become side-by-side neighbours (2.2 mm design gap), and servo sag of 0.7–2° under load lets their **flat faces** meet.
The contact is about 10 mm in from the face edges, not at a corner. Soft-contact depth is 1.4–1.5 mm with a 2 s move and
0.54–0.62 mm with the 3 s move used here (4 s gives the same), and 0.00 mm after the chain settles.

Margins are about 1.6 mm. Bearing play and compliance of the printed parts are not modelled; on hardware they could
use up part of that margin.

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
