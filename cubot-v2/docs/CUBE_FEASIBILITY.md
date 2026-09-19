# Can CuBot fold a 3×3×3 cube?

**No — and not because of a threshold.** The exact cube, and every
near-cube tried, is blocked by the hinge geometry itself. This note records
the measurements (2026-09-19, planner revision `0397435`, loose config hash
`7487b5c67bd18dfb`, pitch 82 mm, hull `data/solids/module.json`) so the
question does not have to be re-opened. Reproduce with
`tools/cube_feasibility.py`.

## 1. Kinematics is not the obstacle

- `solve()` threads the 3×3×3 under the shipped roll: **18 distinct state
  words** (432 threadings over the 24 bases, exhaustive in 51,792 nodes).
- A folder run with a rest-overlap-only checker finds complete **17–21 move**
  single-detent paths from straight to every one of them
  (`uv run python tools/cube_feasibility.py lattice`).

## 2. The obstacle: 22 mm, every time

Sweeping all 1,176 outgoing moves from the assembled cube (52 detents × both
sides × 18 words) with the loose profile:

| outcome | moves |
|---|---:|
| rest-cell overlap | 540 |
| CAD penetration exactly **22.00 mm** | 636 |
| anything under 6 mm | **0** |

(`uv run python tools/cube_feasibility.py escape --workers 8`, ~10 min.)

The number is the same for every move because it is one mechanism. A hinge
half rotating 120° about the body diagonal swings its three corners
(80 mm side, 8 mm chamfer) **22 mm out of its own cell** into the three
face-neighbour cells on the moving side: `H+d0` (where the tail came from),
`H+d1` (where it lands) and `H+t` (the third exit face). In a packed cube
`H+t` is always occupied.

## 3. Roll-word independent

`uv run python tools/cube_feasibility.py last-module` places a hinge module in
every cube cell with every one of the 24 orientations and swings one last
module in from outside (864 configurations). Minimum peak penetration:
**22.00 mm**. In the configurations where the hinge half *is* clean, the swung
module's arc instead bulges one third of a pitch toward the side opposite the
third face and hits `H−t` (30 mm) and `L−t` (42 mm, `L = H+d1`), plus `L+d1`
at 8.3 mm.

So a module can only land where the hinge sits on a **one-thick ridge** —
both neighbours along one axis empty or moving. No cell of a 3×3×3 satisfies
that. This is the quantitative form of "one-deep shapes fold, filled boxes
don't" (`CUBOT_V2_PLAN.md` §2.4, A.3).

## 4. Loosenings considered

| loosening | result |
|---|---|
| raise `hard_penetration_mm` (loose = 6 mm) | next reachable value is 22 mm, 27 % of the module side — a collision, not a tolerance |
| bigger corner chamfer | no: the 42 mm hit is edge-on-face; an analytic 32 mm chamfer still leaves 35 mm |
| raised platform / table-edge lay-down (`ground_hard_mm → ∞`) | reasonable and anticipated by the plan; 3D intermediates dip one pitch (82 mm) into a flat table. Applied in every probe below; does not change the CAD verdict |
| 3×3×3 minus one face-centre, 27th module beside the hole (26 in box) | the only near-cube with a legal *final* move (joint 21, 4.33 mm). Its 15-module two-layer core has no legal move at any core joint (all ≥ 22 mm); a backward search unfolds both tails and locks |
| 2×2×2 + tail, 3×3×2 slab + tail, cube shell minus a face-centre + 2-tail | zero non-trivial legal moves under the shipped roll (goal-side escape probes over all 52 moves, CAD + rest overlap, table removed) |
| greedy forward beam search from straight (real `check_move`, table removed, beam 16, depth 26), maximizing cells inside any 3×3×3 window | 16 / 27 after 7 moves, 17 / 27 after 25 — a one-deep cage, not a block |

## 5. Decision

The cube stays a geometry regression (`data/golden/cube.json`,
`tests/test_integration_qa.py::test_cube_has_zero_of_52_strict_local_moves`)
and is never a target. Cube-like demos must be one-deep: a cube outline drawn
flat, a standing corner of plates, or a frame. A solid cube needs different
hardware (non-cubic modules or a multi-DOF hinge).

## Method notes

- CAD collisions are time-symmetric, gravity and table checks are not. For
  dense goals, search backward (`fold(goal, straight, search_lying_faces=False)`)
  and `replay()` the reversed moves forward (negate `delta`, keep `side`) from
  `Pose(zeros, base=end_pose.base)`; the forward replay is the certificate.
- `fold()`'s goal-distance heuristic burns its budget when the last few
  closing moves are the constrained ones; a goal-side escape probe
  (`check_move` on all 52 moves) is a cheap necessary condition to run first.
- Gravity-distinct goal orientations: 24 bases / 4 yaws = 6 classes.
