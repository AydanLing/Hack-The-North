# CuBot V2 — finalized demo paths (handoff to the MuJoCo sim)

This folder is the complete, self-contained hand-off of every fold path the
offline pre-simulation planner (`cubot-v2`) has certified, to the MuJoCo
simulation pipeline: the seven finalized demo paths — **heart, arrow,
lightning, plus, H, T, N** (shapes 1–7, the fixed review contract) — followed
by the 42 mask-first exploration winners (8–49) and the 35 loose-passing
glyph-atlas discovery candidates (50–84). 84 paths in all; see
"Appended shapes" below for how the two extra groups differ from the demo seven.

Everything a replay needs is here: the machine constants, the collision hull,
the roll word, the start pose (including how the straight chain lies on the
table), the goal pose, the ordered single-detent moves with the side that
swings, our per-move check results, and renders. Nothing in this folder imports
`cubot`; it is plain JSON, CSV, PNG and one dependency-free Python verifier.

| # | shape | moves | loose hard checks | strict | predicted finish | notes |
|---|-------|------:|-------------------|--------|------------------|-------|
| 1 | heart | 16 | pass | fail¹ | flat | the original hardware certificate (tether was hand-lifted once at move 12) |
| 2 | arrow | 23 | pass | fail¹ | flat | open-chevron outline; 2 alternate passing routes |
| 3 | lightning | 14 | **FAIL** — 6 table-incursion violations | fail | **standing** | only complete route found; no loose-passing plan exists yet |
| 4 | plus | 22 | pass | fail¹ | flat | thick cross (family entry 32951); 6 alternate passing routes |
| 5 | h | 11 | pass | fail¹ | flat | |
| 6 | t | 6 | pass | fail¹ | **standing** | |
| 7 | n | 10 | pass | fail¹ | **standing** | |

¹ Every strict failure is the same known 0.398 mm CAD contact between bonded
neighbours against strict's 0 mm penetration limit (loose allows 6 mm). It is
a modelling artefact of the conservative hull, not a real collision.

`PATHS.md` is a generated digest with the silhouette and full move list of
every shape (all 84); `index.json` is the same table for machines. **No human pick has
been recorded yet** (`human_pick: null` everywhere) — "finalized" here means
these are the routes the planner shipped for the seven demo icons, reviewed on
`contact-sheet-labeled.png`.

## Two things to read before simulating

1. **Three shapes are predicted to finish standing up, not lying flat.**
   T, N and lightning end with the drawing plane vertical, balanced on a
   one-cube-wide edge (final support margin exactly +40 mm = half a cube).
   The reason: an `in` move swings the *base* side while the tail stays put,
   so the world orientation of the finished shape is a consequence of the
   move sides, not of the design. The record's nominal `goal.base` (what the
   `top.png` renders show) is *not* where the shape ends up. `path.json`
   carries both: `goal` (nominal) and `final_tracked` (predicted, with
   `ends_flat_on_table`). Heart, arrow, plus and H finish flat.
   Whether a standing T is acceptable for the demo (it does read as a T from
   the side) or these need re-planning with a different lay-down is a human
   decision — the sim should simply report the orientation it ends on.

2. **Lightning is not a passing plan.** It is shipped so the sim can measure
   it, but six of its fourteen moves dip the moving side 49–328 mm into the
   table in our sampled sweep (limit 40 mm). Expect it to fail physically.

## Appended shapes (8–84)

Everything after the demo seven was found by one of the two discovery methods
and exported through the very same replay and consistency checks
(`tools/export_handoff.py --manifest`), so the files, fields and conventions
are identical. What differs is provenance and review status:

| # | group | count | how they were found | manifest |
|---|-------|------:|---------------------|----------|
| 8–49 | mask-first exploration | 42 | hand-drawn 27-cell masks, gated by an exact shipped-roll threading, folded exactly (`docs/METHOD.md`, `docs/EXPLORATION-20260919.md`) | `out/explore-20260919/handoff-manifest.json` from `tools/explore_summary.py` |
| 50–84 | glyph-atlas discovery | 35 | generated atlas variants ranked offline, then folded (`docs/DISCOVERY.md`); names keep the atlas slug (`c-v01`), so several concepts appear twice (`hook-v01` / `hook-v02`) or also exist as an exploration winner (`c` vs `c-v01`) | `out/discovery-20260919/handoff-manifest.json` from `tools/discovery_manifest.py` |

- `path.json → provenance.source_record` says which run family a shape came
  from; `provenance.mask_variant` is the mask / atlas slug that was folded.
- Every appended shape is kinematically complete and passes the **loose** hard
  checks (that was the admission rule; the 21 discovery candidates that fold but
  violate loose are not exported). Strict fails everywhere for the same 0.398 mm
  artefact as the demo seven.
- Many appended shapes finish **standing** (see `ends_flat_on_table` in
  `index.json`) — the same `in`-move effect described above.
- No human pick has been recorded for any of them either; they are candidates,
  not a curated set. Recognizability was judged on the blind contact sheets in
  `docs/exploration-20260919/` and `docs/discovery-20260919/`.

## Folder layout

```
handoff/
├── README.md                 this file — conventions and field reference
├── PATHS.md                  generated digest: silhouettes + move lists for all 84
├── index.json                one row per shape (status, move count, bases, files)
├── machine.json              constants: 27 modules, 80 mm cube, 82 mm pitch, roll word, servo, check profiles
├── module_solid.json         conservative convex hull of one module (full / still / moving pieces), mm
├── contact-sheet-labeled.png the seven demo goal silhouettes, numbered (exploration / atlas sheets live under docs/)
├── contact-sheet-blind.png   same, unlabeled (for blind recognizability review)
├── tools/replay.py           dependency-free verifier / pretty-printer (python3 tools/replay.py shapes/*/path.json)
└── shapes/
    ├── 01-heart/
    │   ├── path.json         THE record — everything below is derived from it
    │   ├── moves.csv         one row per step: joint, delta, side, duration, state before/after, peak torque, penetration, table dip
    │   ├── silhouette.txt    goal drawing as ASCII
    │   ├── top.png           goal silhouette, clean (nominal orientation)
    │   ├── iso.png           isometric render of the goal
    │   └── engineering.png   top view with module numbers (0 = base ... 26 = tail)
    ├── 02-arrow/  03-lightning/  04-plus/  05-h/  06-t/  07-n/   (same files)
    ├── 08-c/ … 49-a/                 mask-first exploration winners (same files)
    └── 50-hook-v01/ … 84-check-v01/  glyph-atlas discovery candidates (same files)
```

## Conventions (the contract)

These match `cubot/lattice.py`, `cubot/geometry.py` and `CUBOT_V2_PLAN.md`
§2.2. `tools/replay.py` is a 150-line executable statement of the same rules.

**Machine.** 27 identical modules, indexed `0` (base) … `26` (tail). Each is
an 80 mm cube with 8 mm corner chamfers, cut by the plane through its centre
perpendicular to the body diagonal `(1,1,1)`; one servo turns the two halves
about that diagonal. Cube centres are `pitch = 82 mm` apart (80 mm cube +
2 mm spacer). Mass 0.223 kg per module. Stall torque at the hinge 10.6 N·m;
our working cap is 5.8 N·m.

**Joints.** There are 26 joints. **Joint `i` is the hinge inside module `i`**
(0-based) and separates module `i`'s *still* half (the one bolted to module
`i-1`; it carries local faces −x, −y, −z) from its *moving* half (carries
+x, +y, +z and the exit face to module `i+1`). Module 26's hinge is never
used. Joint state is one of exactly three positions:

| state | angle | geometry residue (mod 3) |
|------:|------:|--------------------------|
| `-1` | −120° | 2 |
| `0` | 0° | 0 |
| `+1` | +120° | 1 |

There is **no ±240° winding**: the servo may never cross either ±120° limit,
so going from `-1` to `+1` is always two moves through `0`. A *move* is one
detent, `delta ∈ {-1, +1}`, applied to one joint; nominal duration 2.0 s.

**Module frame and lattice FK.** In a module's local frame the chain arrives
through the −x face and, at state 0, leaves through +x. With

```
J  = [[0,0,1],[1,0,0],[0,1,0]]   # +120° about (1,1,1): x→y→z→x, J³ = I  (state +1 applies J, state −1 applies J²)
Rx = [[1,0,0],[0,0,-1],[0,1,0]]  # +90° about local +x (assembly roll),      Rx⁴ = I
```

the discrete forward kinematics is

```
d_k     = M_k · J^(s_k mod 3) · x̂        # exit direction of module k, a unit lattice vector
c_(k+1) = c_k + d_k                       # next cell; world position = pitch · c (mm)
M_(k+1) = M_k · J^(s_k mod 3) · Rx^(r_k)  # next orientation; r_k = k-th digit of the roll word
```

`M_k` is a proper cube rotation (world ← module-local), `c_0 = (0,0,0)` and
`M_0 = base`. At every rest all 27 cells are distinct.

**Roll word.** `12001300133101230333233210` — 26 digits, frozen at assembly:
module `k+1` is bolted onto module `k` rotated `r_k × 90°` about the chain
axis. Same convention and same word as snake_pipeline's `"shipped"`.

**`base` (orientation index).** `M_0` is stored as an index `0..23` into the
cube rotation group enumerated by breadth-first closure of `[J, Rx]` from the
identity (right multiplication, generator order J then Rx). Because that
ordering is easy to get wrong, every pose in `path.json` also carries the
explicit 3×3 `base_matrix`, and `module_orientation_matrices` for all 27
modules. Use the matrices; the index is for cross-reference with our code.

**Start pose.** Every path starts from the straight chain (all states `0`)
lying along +x. `start.base` (and the descriptive `start.lying` quarter-turn
count) says *which way the straight chain is rolled about its own axis* when
it is laid on the table. This matters: it decides how each hinge axis tilts
relative to gravity, and every move side was chosen under that lay-down.
`world_frames.start` gives the exact placement.

**Sides — what physically moves.** A move at joint `j` rotates one half of
the robot about the world axis `M_j · (1,1,1)/√3` through the centre of
module `j`:

| `side` | what swings | rotation about the axis | snake_pipeline name |
|--------|-------------|-------------------------|---------------------|
| `out` | modules `j+1..26` **and the moving half of `j`** | `+delta · 120°` | `moving_side = "child"` |
| `in` | modules `0..j-1` **and the still half of `j`** | `−delta · 120°` | `moving_side = "parent"` |

The side was selected by our gravity/moment model (the lighter side moves;
`checks.measurements.side_ambiguous` marks the ones where both sides had
nearly equal moments). Replay the recorded side; do not re-decide it, or the
final orientation will differ from `final_tracked`. After an `in` move the
base orientation changes — `moves[i].base_after` and `cells_after` already
include this.

**World frame for the sweeps.** Right-handed, `z` up, table at `z = 0`,
gravity `−z`, millimetres. `world_frames.*.centres_mm` are the 27 cube
centres of a rest pose with the whole rest envelope translated so its lowest
hull point touches `z = 0` (module 0 at `x = y = 0`); `rotations` are the
matching world←local matrices. `start` and `final_tracked` are the two the
sim needs; `goal_nominal` is what the renders show.

## `path.json` field reference (`schema: cubot.handoff.v1`)

| key | meaning |
|-----|---------|
| `name`, `demo_number` | shape name and its number on the contact sheets |
| `status` | `complete`, `loose_hard_ok`, `strict_hard_ok`, `loose_violations[]`, `human_pick`, notes |
| `summary` | move count, total time, `in`/`out` counts, `ends_flat_on_table`, peak torque demand, worst penetration and table dip, soft scores (0–1, higher is better) |
| `machine` | constants used for the checks (pitch 82 mm, roll word, servo limits, …) and the hull file |
| `start` | straight chain: `states[26]`, `base`, `base_matrix`, `lying`, `cells[27]`, per-module orientation matrices |
| `goal` | nominal goal: same keys plus `states_mod3`, `angles_deg`, `silhouette[]` (ASCII), `authored_target[]` (the icon mask it was matched to) |
| `final_tracked` | same joint states as `goal`, but the **predicted world orientation** after the moves; `lattice_span`, `ends_flat_on_table`, `final_balance_margin_mm` |
| `world_frames` | settled continuous frames (mm) for `start`, `final_tracked`, `goal_nominal` |
| `moves[]` | ordered steps, see below |
| `alternates[]` | other complete, loose-passing routes to the same goal (`moves_compact` = `[joint, delta, side, duration_s]`), ranked below the primary |
| `snake_pipeline` | the goal in snake_pipeline conventions (see next section) |
| `profiles` | the `loose` and `strict` thresholds the checks ran with |
| `reports` | per profile: candidate summary and this exact path's verdict, violations and scores |
| `provenance` | source `record.json`, plan index, creation time, git SHA, config/source hashes |

Each entry of `moves[]`:

| key | meaning |
|-----|---------|
| `step` | 1-based order |
| `joint`, `delta`, `side` | the move (see Conventions) |
| `moving_side_snake_pipeline` | `"parent"` for `in`, `"child"` for `out` |
| `duration_s` | nominal move time (2.0 s) |
| `state_before`, `state_after`, `angle_after_deg` | that joint only |
| `states_after[26]`, `base_after`, `cells_after[27]` | the full rest pose after the move |
| `hard_ok` | every hard check passed on this move under the accepting profile |
| `checks.hard` | `cad_penetration`, `ground`, `rest_cell_overlap`, `torque_stall`, plus the wire-bundle rules `tether_table`, `tether_cell`, `tether_down` (a 20 × 40 mm wire leaves module 0 through its free face; nothing may collide with it) → `[passed, reason]` |
| `checks.soft` | `balance`, `ground`, `holding_load`, `moving_side`, `near_contact`, `pivot_dip`, `torque` → `[score 0–1, reason]` |
| `checks.measurements` | raw numbers: `peak_demand_nm` (static + inertial over the eased profile), `static_peak_nm`, `holding_peak_nm`, `max_penetration_mm`, `max_ground_depth_mm`, `max_pivot_dip_mm`, `balance_margin_mm`, `first_contact_angle_deg`, `peak_angle_deg`, `arc` (`up`/`down`/`hump`/`mixed`/`flat`), `moving_side`, `side_ambiguous`, `samples` |

`moves.csv` is the same list flattened to one row per step for spreadsheets.

## Mapping to `snake_pipeline` (Jerry's MuJoCo model)

The two code bases describe the same mechanism with different bookkeeping.
Verified numerically on all seven goals: `snakeshape.mechanism.lattice_walk`
on the `"shipped"` assembly returns exactly `snake_pipeline.cells_chain_frame`.

| cubot-v2 (this folder) | snake_pipeline |
|------------------------|----------------|
| chain frame: arrive −x, leave +x; hinge `(1,1,1)`, frames roll with `Rx` | chain frame: arrive −z, leave +z; hinge `(±1,±1,1)` tilted by the cumulative roll, frames never roll |
| 26 joint states in `{-1,0,+1}` | 27 servo states in `{0,1,2}` (servo 27 unused) → `states_mod3 + [0]`, provided as `goal_states_mod3_27` and `goal_angles_rad_27` |
| `−1` = −120° | `2` = 240° — same rest geometry, but the servo must be driven **−120°**, never +240° |
| lattice cell `(x,y,z)` | `(y, z, x)` — `axis_map_v2_to_snake_pipeline = [[0,1,0],[0,0,1],[1,0,0]]` |
| `side: "in"` / `"out"` | `moving_side: "parent"` / `"child"` |
| pitch **82 mm** | `constants.PITCH = 0.084` m — our sweeps were run at 82; re-check clearances if you keep 84 |
| `world_frames` (mm, z up, settled on z = 0) | `kinematics.R_ROOT` lays the root flat with local z → world x, local y → world z |

Practical recipe: take `snake_pipeline.goal_states_mod3_27` for the target,
play `moves[]` one detent at a time with the recorded side (`parent`/`child`),
and lay the straight chain down in `start.base` (use `world_frames.start` to
build the root quaternion). Replaying only joint targets and letting physics
choose the side will still reach the same *shape*, but possibly in a
different world orientation than `final_tracked`.

## Verifying the files

```bash
cd handoff
python3 tools/replay.py shapes/*/path.json --quiet          # re-derive every pose, cell and base from integers
python3 tools/replay.py shapes/06-t/path.json --steps       # watch the T stand up, move by move
python3 tools/replay.py shapes/02-arrow/path.json --emit-moves
```

The verifier rebuilds the kinematics from `J` and `Rx` alone (no numpy), so a
clean run means the JSON is internally consistent and matches the conventions
above, independently of the code that produced it.

## What we would like back, per shape

From `CUBOT_V2_PLAN.md` §8.1: `formed` (bool), final shape drift (mm, rigid
motion removed), peak hinge torque (N·m), servo saturation time (s), base
travel (mm) and turn (deg), the face/orientation it ended on (so we can
compare with `final_tracked.base`), and the first move that failed if any.
Anything in the sim's own schema is fine — these are the fields the library
records will store.

## Provenance and regeneration

Source records: `cubot-v2/out/demo-20260919/runs/<shape>/record.json`
(planner git SHA `8bfd7f79`, loose config hash `7487b5c67bd18dfb`, strict
`ccfb6e2b5dbdd610`), produced on 2026-09-19 as described in
`cubot-v2/docs/FINDINGS.md` ("recognition-first seven-shape demo" and "arrow
and plus semantic optimization"). Arrow and plus are the semantically
optimized versions (open chevron; thick cross), not the earlier hook-like
arrow or nubbed plus.

`out/` is git-ignored; this folder is the committed copy. To regenerate after
a new planner run:

```bash
cd cubot-v2
uv run python tools/export_handoff.py --runs out/<run>/runs
python3 handoff/tools/replay.py handoff/shapes/*/path.json --quiet
```

The exporter re-verifies each path with the planner's own kinematics
(states reach the goal, FK matches the stored cells, 27 distinct cells) and
refuses to write a file that does not.
