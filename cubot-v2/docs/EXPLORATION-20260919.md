# Shape exploration — 2026-09-19

Forty-seven new common structures (block letters, digits, geometric primitives, everyday
icons) were designed as 27-cell masks, gated on the structural screens and exact
shipped-roll threading, and — for the ones that thread — folded from the straight chain
with the loose profile. Five parallel workers each owned one category; every mask they
tried is kept under `data/candidates/<category>/` as evidence. Their per-category reports
(with per-variant gate results and honest recognizability notes) are under
`out/explore-20260919/<category>/report.md`.

Already explored and therefore excluded: the shipped seven (heart, arrow, lightning,
plus, H, T, N), the seven rejected icons (house, fish, star, music-note, key,
question-mark, smiley), and the exhaustive plus/arrow searches.

## How to read the table

- **verdict** `PASS` = complete plan passing every loose hard check on the *exact* mask;
  `violating (n)` = complete plan with `n` named hard violations (ground incursion unless
  stated); `roll-UNSAT` = structurally valid but no threading under the shipped roll.
- Only rows whose rank-0 goal was confirmed to be the mask (`goal_is_mask`) are counted.
  The pipeline's matcher otherwise folds nearby family drawings, and three workers
  independently caught "PASS" lines that belonged to a substitute silhouette; the driver
  now folds exact threadings only and prints `[GOAL != MASK]` if that ever recurs.
- **finish** is the tracked orientation after replaying the move sides
  (`STANDING` = drawing plane vertical, as with the shipped T/N/lightning).
- Verification: every best variant was re-folded with `-k 2 --time-budget 150`; masks
  that only produced a violating plan were re-run with `-k 1 --time-budget 240`. The fold
  search is budget-sensitive — a large share of "violating" results at 90–150 s became
  clean passes at 240 s, so a violating verdict here means "no passing route found in
  240 s", not "no passing route exists".
- Recognizability is *not* encoded in the verdict (RULES.md: recognizability is a human
  gate). The blind sheet is `docs/exploration-20260919/contact-sheet-blind.png`; the
  labeled key is next to it. No `human_pick` has been set.

## What the roll word allows (findings that shaped every design)

All five workers independently derived the same planar "turn automaton" from the roll
word and checked it against `cubot.solver.solve` (one worker on 300 random paths, zero
disagreements): at each joint the flat chain can go straight or turn to *one* forced
side. Consequences that held across all 261 masks:

- **In-plane rotation and mirroring never change threadability** (the solver already
  tries all 24 bases). "Try the mirror" is not a lever.
- **Same-side double turns (a 2-wide U-turn) are impossible at joints 2, 3, 6, 7, 12,
  16, 25** (roll digit 0); **zig-zags are impossible where the roll digit is 2** (joints
  1, 14, 20, 23). So 2-wide strokes must be traversed lengthwise, and the shipped-style
  chunky 2-wide E/F/C/S/Z are all roll-UNSAT — 1-wide and 3-wide strokes thread far more
  often than 2-wide ones.
- **Long 45° diagonals are impossible**: strictly alternating turns are allowed for at
  most 5 consecutive joints (16–20), so diamonds, hourglasses, sine waves, X, a true
  V-in-the-middle M/W, and a stair-diagonal Z or 7 never thread. Diagonals must be drawn
  as 2–1 stepped stairs or replaced by square strokes.
- **Odd cell count kills closed rings**: 27 cells cannot form a closed even-perimeter
  loop, so 0/O/square/ring need a gap, an inner nub, or a chamfered corner. Corner and
  next-to-corner gaps are roll-UNSAT on the 8×8 ring; 16 of 28 mid-edge gaps thread.
- **Dead-end 1-wide strokes pin a chain end**: any glyph with three or more stroke tips
  (X, double arrow, crown spikes, tree trunk under a symmetric canopy, rocket fins) fails
  the degree screen or is roll-UNSAT once fixed.
- **Ground incursion is the dominant violation** (not torque, not collision): the fold
  search's fallback direct-replay routes swing a side through the table. More budget,
  not different masks, is what fixes it.

## Results

47 shapes attempted, 261 masks gated, 42 loose-PASS on the exact mask, 1 complete-but-violating (`z-v5`, not a Z anyway), 3 roll-UNSAT (crown, diamond, double-arrow), 1 structurally impossible (X). 37 registered.

Renders are under `out/explore-20260919/` (git-ignored); the two contact sheets are copied to `docs/exploration-20260919/`.

| # | shape | variant | tried | threadings | verdict | moves | worst soft | finish | box | render |
|---|-------|---------|------:|-----------:|---------|------:|-----------:|--------|-----|--------|
| 1 | c | c-v5 | 5 | 3 | PASS | 5 | 0.432 | flat | 7x7 | `letters-a/runs/c-v5/c/renders/top.png` |
| 2 | j | j-v4 | 4 | 3 | PASS | 5 | 0.432 | flat | 6x8 | `letters-a/runs/j-v4/j/renders/top.png` |
| 3 | m | m-v10 | 4 | 6 | PASS | 14 | 0.389 | flat | 7x6 | `verify/letters-b/runs/m-v10/m/renders/top.png` |
| 4 | wave | wave-v1 | 3 | 6 | PASS | 14 | 0.389 | flat | 7x6 | `verify2/geometric/runs/wave-v1/wave/renders/top.png` |
| 5 | w | w-v10 | 4 | 6 | PASS | 15 | 0.389 | flat | 7x6 | `verify/letters-b/runs/w-v10/w/renders/top.png` |
| 6 | mug | mug-v2 | 2 | 6 | PASS | 16 | 0.375 | flat | 7x8 | `verify2/icons/runs/mug-v2/mug/renders/top.png` |
| 7 | d2 | d2-v2 | 2 | 3 | PASS | 18 | 0.283 | flat | 5x7 | `verify2/digits/runs/d2-v2/d2/renders/top.png` |
| 8 | d5 | d5-v2 | 2 | 3 | PASS | 19 | 0.283 | flat | 5x7 | `verify2/digits/runs/d5-v2/d5/renders/top.png` |
| 9 | k | k-v9 | 3 | 6 | PASS | 14 | 0.218 | flat | 6x7 | `letters-b/runs/k-v9/k/renders/top.png` |
| 10 | s | s-v6 | 3 | 3 | PASS | 13 | 0.215 | flat | 6x7 | `letters-a/runs/s-v6/s/renders/top.png` |
| 11 | checkmark | checkmark-v1 | 2 | 3 | PASS | 24 | 0.207 | flat | 14x10 | `verify2/geometric/runs/checkmark-v1/checkmark/renders/top.png` |
| 12 | staircase | staircase-v2 | 2 | 3 | PASS | 17 | 0.195 | flat | 9x19 | `verify2/geometric/runs/staircase-v2/staircase/renders/top.png` |
| 13 | rocket | rocket-v4 | 1 | 6 | PASS | 10 | 0.0 | flat | 6x7 | `verify/icons/runs/rocket-v4/rocket/renders/top.png` |
| 14 | i | i-v8 | 4 | 6 | PASS | 14 | 0.0 | flat | 7x11 | `verify2/letters-b/runs/i-v8/i/renders/top.png` |
| 15 | d3 | d3-v5 | 3 | 3 | PASS | 15 | 0.0 | flat | 6x8 | `digits/runs/d3-v5/d3/renders/top.png` |
| 16 | v | v-v3 | 2 | 6 | PASS | 18 | 0.0 | flat | 9x8 | `verify/letters-b/runs/v-v3/v/renders/top.png` |
| 17 | dumbbell | dumbbell-v5 | 1 | 3 | PASS | 19 | 0.0 | flat | 11x5 | `verify/icons/runs/dumbbell-v5/dumbbell/renders/top.png` |
| 18 | d4 | d4-v5 | 6 | 3 | PASS | 20 | 0.0 | flat | 6x8 | `verify2/digits/runs/d4-v5/d4/renders/top.png` |
| 19 | d8 | d8-v4 | 2 | 3 | PASS | 21 | 0.0 | flat | 5x8 | `verify/digits/runs/d8-v4/d8/renders/top.png` |
| 20 | l | l-v3 | 4 | 9 | PASS | 21 | 0.0 | flat | 6x7 | `verify3/letters-a/runs/l-v3/l/renders/top.png` |
| 21 | tree | tree-v6 | 2 | 3 | PASS | 23 | 0.0 | flat | 8x6 | `verify2/icons/runs/tree-v6/tree/renders/top.png` |
| 22 | up-arrow | up-arrow-v2 | 2 | 3 | PASS | 26 | 0.0 | flat | 5x10 | `verify2/geometric/runs/up-arrow-v2/up-arrow/renders/top.png` |
| 23 | d1 | d1-v2 | 4 | 6 | PASS | 28 | 0.0 | flat | 5x9 | `verify2/digits/runs/d1-v2/d1/renders/top.png` |
| 24 | bell | bell-v4 | 2 | 6 | PASS | 30 | 0.0 | flat | 6x7 | `verify2/icons/runs/bell-v4/bell/renders/top.png` |
| 25 | d7 | d7-v3 | 5 | 3 | PASS | 6 | 0.472 | STANDING | 6x10 | `verify/digits/runs/d7-v3/d7/renders/top.png` |
| 26 | d0 | d0-v8 | 1 | 6 | PASS | 5 | 0.432 | STANDING | 6x8 | `verify/digits/runs/d0-v8/d0/renders/top.png` |
| 27 | u | u-v4 | 1 | 3 | PASS | 7 | 0.432 | STANDING | 8x6 | `verify/letters-a/runs/u-v4/u/renders/top.png` |
| 28 | triangle | triangle-v4 | 1 | 3 | PASS | 8 | 0.432 | STANDING | 7x9 | `verify/geometric/runs/triangle-v4/triangle/renders/top.png` |
| 29 | anchor | anchor-v4 | 1 | 3 | PASS | 11 | 0.432 | STANDING | 8x8 | `verify/icons/runs/anchor-v4/anchor/renders/top.png` |
| 30 | e | e-v3 | 2 | 3 | PASS | 11 | 0.432 | STANDING | 6x7 | `verify2/letters-a/runs/e-v3/e/renders/top.png` |
| 31 | square | square-v1 | 1 | 3 | PASS | 5 | 0.407 | STANDING | 8x8 | `verify/geometric/runs/square-v1/square/renders/top.png` |
| 32 | spiral | spiral-v1 | 1 | 3 | PASS | 5 | 0.404 | STANDING | 8x8 | `verify/geometric/runs/spiral-v1/spiral/renders/top.png` |
| 33 | y | y-v2 | 2 | 6 | PASS | 14 | 0.267 | STANDING | 9x9 | `letters-b/runs/y-v2/y/renders/top.png` |
| 34 | hourglass | hourglass-v4 | 1 | 3 | PASS | 11 | 0.074 | STANDING | 5x7 | `verify/geometric/runs/hourglass-v4/hourglass/renders/top.png` |
| 35 | d6 | d6-v7 | 1 | 3 | PASS | 5 | 0.06 | STANDING | 6x8 | `verify/digits/runs/d6-v7/d6/renders/top.png` |
| 36 | d9 | d9-v6 | 1 | 3 | PASS | 5 | 0.06 | STANDING | 6x8 | `verify/digits/runs/d9-v6/d9/renders/top.png` |
| 37 | flag | flag-v2 | 1 | 6 | PASS | 6 | 0.06 | STANDING | 7x9 | `verify/icons/runs/flag-v2/flag/renders/top.png` |
| 38 | f | f-v3 | 2 | 3 | PASS | 8 | 0.06 | STANDING | 6x9 | `letters-a/runs/f-v3/f/renders/top.png` |
| 39 | ring | ring-v1 | 1 | 3 | PASS | 10 | 0.0 | STANDING | 7x8 | `verify/geometric/runs/ring-v1/ring/renders/top.png` |
| 40 | boat | boat-v6 | 2 | 3 | PASS | 16 | 0.0 | STANDING | 9x6 | `verify2/icons/runs/boat-v6/boat/renders/top.png` |
| 41 | umbrella | umbrella-v7 | 2 | 6 | PASS | 18 | 0.0 | STANDING | 7x9 | `verify2/icons/runs/umbrella-v7/umbrella/renders/top.png` |
| 42 | a | a-v3 | 6 | 6 | PASS | 30 | 0.0 | STANDING | 6x8 | `verify2/letters-b/runs/a-v3/a/renders/top.png` |
| 43 | z | z-v5 | 2 | 3 | violating (16) | 13 | 0.0 | flat | 6x6 | `letters-a/runs/z-v5/z/renders/top.png` |
| 44 | crown | crown-v1 | 1 | 0 | roll-UNSAT | - | - | - | 8x4 | - |
| 45 | diamond | diamond-v1 | 1 | 0 | roll-UNSAT | - | - | - | 8x8 | - |
| 46 | double-arrow | double-arrow-v2 | 1 | 0 | roll-UNSAT | - | - | - | 11x5 | - |
| 47 | x | x-v4 | 1 | 0 | structural: degree | - | - | - | 7x7 | - |

## Per-category notes (condensed from the workers' reports)

**Block letters (L U C E F Z S J / M W V X Y K I A).** 14 of 16 letters have a
recognizable threadable mask; X is structurally impossible (four tips, 4-way crossing)
and Z is roll-hard (its diagonal needs 6+ alternating turns; 3,247 parametric Z masks,
657 structurally valid, none thread — the only threadable "Z" is a blob). The letters that
thread do so with 1-wide or 3-wide strokes: E/F/S needed a 1-wide stem, L a 3-wide stem,
M/W a square-font "dip" (`m-v10`/`w-v10`; the mechanically easier `m-v3`/`w-v3` read as
bags, not letters). V, K and Y use 2–1 stepped diagonals. I only threads with offset
serifs (symmetric serif I is roll-UNSAT in every configuration) and A only as a lopsided
glyph; neither found a passing route.

**Digits (0–9).** All ten digits thread (54 masks; 28 roll-UNSAT, 5 structural). Classic
seven-segment 2/5 thread only with one chamfered corner; 3 only with a short middle stroke;
6/9 need a 1-wide loop with a 4×2 eye; 8 needs 1-wide strokes with 3×2 eyes and a chamfer
(of 803,472 two-hole drawings in the 8×8 solver space, only the four corner-chamfered
copies of `d8-v4` are within distance 1 of a symmetric 8). 7 threads as a seven-segment
7 with a foot wart (`d7-v3`, reads "7 or Γ") or with a jogged stem (`d7-v4`, reads
clearly). The serif 1 (`d1-v2`) is the best-reading digit.

**Geometric.** Square (mid-edge gap), ring (chamfered octagon + inner nub), square wave,
staircase, checkmark and a 1.25-turn spiral all thread and pass. Diamond and a double
arrow never thread (all-turn outlines; four tips). Triangle threads only as a lumpy
right-triangle outline that reads as stairs; hourglass only as a blob with no waist; a
new up-arrow only as a mallet — the shipped arrow rotated is the only real up arrow.
A monotone 27-cell staircase cannot fit in 12×12 at all (`staircase-v2` is 9×19).

**Everyday icons.** Anchor, dumbbell, flag, mug, umbrella, bell, boat all thread and pass;
anchor and dumbbell read best. Crown never threads (three spikes need three same-side
hairpins the roll never provides — 1.42 M enumerated 9×6 feasible shapes contain no
crown). Tree and rocket pass mechanically but read as "mushroom" and "tower".

## Registered vs. not

The table above shows the best variant by mechanics (`explore_summary.py` ranks passing
< violating, flat < standing, then worst soft score, then moves). For three shapes the
registry deliberately uses a different passing variant because it reads better:
`square-wave` = `wave-v7` (the table's `wave-v1` reads as an M), `j` = `j-v3` (`j-v4`'s
tall hook reads as a lopsided U), `7` = `d7-v4` (jogged stem; `d7-v3` reads as Γ). The
contact sheets in `docs/exploration-20260919/` are built from the registered variants.

Winners registered in `cubot/generate/parametric.py` (`EXPLORED_NAMES`): every shape with
an exact threading, a verified loose-passing plan on the exact mask, and a worker
recognizability note of "reads as X" or better. Registered under their glyph names with
aliases (`zero`, `letter-k`, `wave`, `barbell`, …); `DEMO_NAMES` and `handoff/` are
untouched.

Passing but **not** registered because they do not read as their name: `hourglass-v4`
("8"), `rocket-v4` ("tower"), `triangle-v4` ("stairs"), `up-arrow-v2` ("mallet"),
`tree-v6` ("mushroom"), `m-v3`/`w-v3` ("bag"), `d7-v3` (marginal "7/Γ").

## Suggested next steps

1. Blind pick from `docs/exploration-20260919/contact-sheet-blind.png`, then `cubot library
   pick` for the chosen names.
2. For picks that finish STANDING (0, 6, 9, U, F, Y, flag, anchor, square, ring, …), re-plan
   with a different lay-down if a flat finish matters, as for the shipped T/N.
3. The fold search is budget-bound: most first-pass "violating" verdicts flipped to PASS
   at 240 s. A larger default budget (or a smarter side-selector near the table) would
   likely clear I, A and L too.
4. Export chosen winners with a generalized `tools/export_handoff.py` (it currently
   hard-codes the seven demo names).

## Best mask per shape

### c (c-v5) — PASS
```
#######
#######
##.....
##.....
##.....
##.....
#####..
```

### j (j-v4) — PASS
```
....##
....##
....##
#...##
#...##
#...##
######
######
```

### m (m-v10) — PASS
```
###.###
#.#.#.#
#.#.#.#
#.#.#.#
#.#.#.#
#.###.#
```

### wave (wave-v1) — PASS
```
###.###
#.#.#.#
#.#.#.#
#.#.#.#
#.#.#.#
#.###.#
```

### w (w-v10) — PASS
```
#.###.#
#.#.#.#
#.#.#.#
#.#.#.#
#.#.#.#
###.###
```

### mug (mug-v2) — PASS
```
#####..
#...#..
#...#..
#...###
#...#.#
#...###
#...#..
#####..
```

### d2 (d2-v2) — PASS
```
#####
####.
...##
#####
#....
#####
#####
```

### d5 (d5-v2) — PASS
```
#####
.####
##...
#####
....#
#####
#####
```

### k (k-v9) — PASS
```
##..##
##.###
##.#..
####..
###...
#####.
##..#.
```

### s (s-v6) — PASS
```
######
#.....
#.....
######
.....#
######
######
```

### checkmark (checkmark-v1) — PASS
```
...........###
..........##..
..........#...
........###...
........#.....
#.....###.....
#....##.......
###..#........
..#.##........
..###.........
```

### staircase (staircase-v2) — PASS
```
#........
#........
#........
#........
###......
..#......
..#......
..#......
..###....
....#....
....#....
....#....
....###..
......#..
......#..
......#..
......###
........#
........#
```

### rocket (rocket-v4) — PASS
```
.####.
.####.
.####.
.####.
.####.
##..##
##...#
```

### i (i-v8) — PASS
```
######.
####...
...#...
...#...
...#...
...#...
...#...
...#...
...#...
...####
.######
```

### d3 (d3-v5) — PASS
```
######
.....#
...###
...###
.....#
.....#
######
######
```

### v (v-v3) — PASS
```
##.....##
##.....##
.##....##
..#...###
..#...#..
..#..##..
..##.#...
...###...
```

### dumbbell (dumbbell-v5) — PASS
```
##.......##
##.......##
###########
###.......#
###.......#
```

### d4 (d4-v5) — PASS
```
#...##
#...##
#...##
######
...###
...###
...###
...###
```

### d8 (d8-v4) — PASS
```
#####
#...#
#...#
#####
#####
#...#
#...#
####.
```

### l (l-v3) — PASS
```
###...
###...
###...
###...
###...
######
######
```

### tree (tree-v6) — PASS
```
...##...
.######.
.#######
########
...##...
...##...
```

### up-arrow (up-arrow-v2) — PASS
```
.##..
####.
####.
#####
.##..
.##..
.##..
.##..
.##..
.##..
```

### d1 (d1-v2) — PASS
```
..##.
####.
####.
..##.
..##.
..##.
..##.
#####
.####
```

### bell (bell-v4) — PASS
```
..##..
.####.
.#..#.
.####.
######
######
.###..
```

### d7 (d7-v3) — PASS
```
######
######
....##
....##
....##
....##
....##
....##
....##
....#.
```

### d0 (d0-v8) — PASS
```
.#####
######
#....#
#....#
#....#
#....#
#....#
######
```

### u (u-v4) — PASS
```
##....##
##....##
##....##
##....##
##....##
.#######
```

### triangle (triangle-v4) — PASS
```
###....
#.#....
#.##...
#..#...
#..#...
#..###.
#....#.
#....#.
#######
```

### anchor (anchor-v4) — PASS
```
..###...
..#.#...
..###...
...##...
...##...
...##..#
#..##..#
########
```

### e (e-v3) — PASS
```
######
#.....
#.....
######
######
#.....
######
```

### square (square-v1) — PASS
```
########
#......#
#......#
#......#
#......#
#......#
#......#
#####.##
```

### spiral (spiral-v1) — PASS
```
########
.......#
.......#
.###...#
.#.....#
.#.....#
.#.....#
.#######
```

### y (y-v2) — PASS
```
##.....##
####..###
...#..#..
...####..
...##....
...##....
...##....
...##....
...##....
```

### hourglass (hourglass-v4) — PASS
```
#####
#...#
#####
####.
##.##
#...#
#####
```

### d6 (d6-v7) — PASS
```
.#####
##....
##....
##....
######
#....#
#....#
######
```

### d9 (d9-v6) — PASS
```
######
#....#
#....#
######
....##
....##
....##
#####.
```

### flag (flag-v2) — PASS
```
#######
#######
#######
#......
#......
#......
#......
#......
#......
```

### f (f-v3) — PASS
```
######
##...#
##....
####..
####..
##....
##....
##....
##....
```

### ring (ring-v1) — PASS
```
.#####.
##...##
##....#
#.....#
#.....#
#.....#
##...##
.#####.
```

### boat (boat-v6) — PASS
```
..##.....
..##.....
####.....
...#.....
#########
#########
```

### umbrella (umbrella-v7) — PASS
```
...##..
#######
#######
....#..
....#..
..#.#..
..#.#..
..#.#..
..###..
```

### a (a-v3) — PASS
```
..##..
.###..
.#.#..
##.##.
#####.
##..#.
##..##
##..##
```

### z (z-v5) — violating (16)
```
######
..####
..###.
..###.
###.##
######
```
violations: move 1 ground: early sampled table incursion 76.060 mm (limit 40.000 mm), move 2 ground: early sampled table incursion 76.060 mm (limit 40.000 mm), move 3 ground: early sampled table incursion 82.000 mm (limit 40.000 mm), move 4 ground: early sampled table incursion 164.000 mm (limit 40.000 mm), move 5 ground: early sampled table incursion 53.055 mm (limit 40.000 mm), move 6 ground: early sampled table incursion 130.726 mm (limit 40.000 mm), move 7 rest_cell_overlap: 3 duplicate occupied lattice cells at rest, move 7 cad_penetration: early sampled CAD penetration 80.000 mm (limit 6.000 mm), move 8 rest_cell_overlap: 3 duplicate occupied lattice cells at rest, move 8 ground: early sampled table incursion 246.000 mm (limit 40.000 mm), move 9 cad_penetration: early sampled CAD penetration 40.332 mm (limit 6.000 mm), move 10 ground: early sampled table incursion 55.628 mm (limit 40.000 mm), move 11 rest_cell_overlap: 2 duplicate occupied lattice cells at rest, move 11 cad_penetration: early sampled CAD penetration 80.000 mm (limit 6.000 mm), move 11 ground: early sampled table incursion 164.000 mm (limit 40.000 mm), move 12 cad_penetration: early sampled CAD penetration 63.654 mm (limit 6.000 mm)

### crown (crown-v1) — roll-UNSAT
```
##.##.##
##.##.##
########
.#######
```

### diamond (diamond-v1) — roll-UNSAT
```
...#.#..
..##.##.
.##...##
##.....#
#.....##
##...##.
.##.##..
..###...
```

### double-arrow (double-arrow-v2) — roll-UNSAT
```
##.......##
##.......##
###########
##.......##
##.......##
```

### x (x-v4) — structural: degree
```
##...##
.##.##.
..###..
..###..
.##.##.
##...##
##..###
```
