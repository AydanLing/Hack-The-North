# lantern-4x4-2

A 3D "lantern": a hollow 4×4 cage, 3 levels tall, with 9 of the 12 ring cells filled on every level.
It is folded from the straight chain in **15 single-detent moves**. `path.json` uses the `cubot.handoff.v1` layout
(same fields as `../../../handoff/shapes/*/path.json`), so the handoff tools and fold viewers read it.

```
levels, bottom to top (# = cube)
bottom   middle   top
.###     ##.#     ####
...#     #..#     #...
#..#     #..#     #...
.###     ..##     ###.
```

## How it was found

1. Every reachable pose of the shipped roll whose cubes stay inside a hollow 4×4 column (≤ 6 levels) was enumerated:
   11.6 M poses. They were ranked as "lanterns", meaning every level is mostly a full ring.
2. A collision-free route was found by unfolding the goal backward to the straight chain. The collision check was a
   MuJoCo sweep with the official URDF meshes (`cubot_urdf/`), ≤ 1 mm, 10° samples.
3. The route was replayed forward in MuJoCo with full physics: free base, gravity, a floor at μ 0.35 (vinyl desk,
   assumed), and servo force caps of 5.8 and 10.6 N·m.

## Simulation results (MuJoCo 3.13)

| servo cap | formed | worst final joint error | late moves | time any servo sits at the cap |
|---|---|---:|---:|---:|
| 5.8 N·m | yes | 2.2° | 0 | 0.94 s |
| 10.6 N·m | yes | 2.2° | 0 | — (peak demand 6.3 N·m) |

Worst module-to-module overlap during the fold: 1.6 mm. Finished height: about 250 mm.

## Caveats

- The `side` fields are the planner's gravity-based guess. The simulation does not force them: physics chooses which
  half swings.
- The route was **not** found with the planner's full `check_move` (table/torque) during the search. Physics was the
  check instead.
- **Not wire-safe.** If wires leave module 27 through its outer face, this route fails. Modules enter an
  80 × 50 × 50 mm keep-out zone off that face by 23.5 mm, and the wires end pressed into the table. Use
  `../lantern-4x4-2-wiresafe/` instead: same lantern, a different 15-move route, validated in MuJoCo.
