# Shape exploration — 2026-09-19 (interim, verified rows only)

Run by `tools/explore_shape.py` (gate → exact threading → fold of exact threadings only)
over 47 new common structures in five categories (block letters ×2, digits, geometric,
everyday icons); masks live in `data/candidates/<category>/`. Every row below is a fold
whose rank-0 goal was confirmed to be the mask itself (`goal_is_mask`), re-run in a
verification pass with `-k 2 --time-budget 150` and, for masks that only produced a
violating plan, a second pass with `-k 1 --time-budget 240`. A few second-pass folds
were still running when this file was generated; a follow-up commit will finalize it,
add the blind contact sheet, register the winners in the icon registry, and record the
run in `FINDINGS.md`.

Regenerate with `uv run python tools/explore_summary.py --out out/explore-20260919`.

| # | shape | variant | tried | threadings | verdict | moves | worst soft | finish | box | render |
|---|-------|---------|------:|-----------:|---------|------:|-----------:|--------|-----|--------|
| 1 | c | c-v5 | 5 | 3 | PASS | 5 | 0.432 | flat | 7x7 | `letters-a/runs/c-v5/c/renders/top.png` |
| 2 | j | j-v4 | 4 | 3 | PASS | 5 | 0.432 | flat | 6x8 | `letters-a/runs/j-v4/j/renders/top.png` |
| 3 | m | m-v10 | 3 | 6 | PASS | 14 | 0.389 | flat | 7x6 | `verify/letters-b/runs/m-v10/m/renders/top.png` |
| 4 | wave | wave-v1 | 3 | 6 | PASS | 14 | 0.389 | flat | 7x6 | `verify2/geometric/runs/wave-v1/wave/renders/top.png` |
| 5 | w | w-v10 | 3 | 6 | PASS | 15 | 0.389 | flat | 7x6 | `verify/letters-b/runs/w-v10/w/renders/top.png` |
| 6 | mug | mug-v2 | 2 | 6 | PASS | 16 | 0.375 | flat | 7x8 | `verify2/icons/runs/mug-v2/mug/renders/top.png` |
| 7 | k | k-v9 | 3 | 6 | PASS | 14 | 0.218 | flat | 6x7 | `letters-b/runs/k-v9/k/renders/top.png` |
| 8 | s | s-v6 | 3 | 3 | PASS | 13 | 0.215 | flat | 6x7 | `letters-a/runs/s-v6/s/renders/top.png` |
| 9 | staircase | staircase-v2 | 2 | 3 | PASS | 17 | 0.195 | flat | 9x19 | `verify2/geometric/runs/staircase-v2/staircase/renders/top.png` |
| 10 | rocket | rocket-v4 | 1 | 6 | PASS | 10 | 0.0 | flat | 6x7 | `verify/icons/runs/rocket-v4/rocket/renders/top.png` |
| 11 | d3 | d3-v5 | 3 | 3 | PASS | 15 | 0.0 | flat | 6x8 | `digits/runs/d3-v5/d3/renders/top.png` |
| 12 | v | v-v3 | 2 | 6 | PASS | 18 | 0.0 | flat | 9x8 | `verify/letters-b/runs/v-v3/v/renders/top.png` |
| 13 | dumbbell | dumbbell-v5 | 1 | 3 | PASS | 19 | 0.0 | flat | 11x5 | `verify/icons/runs/dumbbell-v5/dumbbell/renders/top.png` |
| 14 | d8 | d8-v4 | 2 | 3 | PASS | 21 | 0.0 | flat | 5x8 | `verify/digits/runs/d8-v4/d8/renders/top.png` |
| 15 | d1 | d1-v2 | 4 | 6 | PASS | 28 | 0.0 | flat | 5x9 | `verify2/digits/runs/d1-v2/d1/renders/top.png` |
| 16 | bell | bell-v4 | 2 | 6 | PASS | 30 | 0.0 | flat | 6x7 | `verify2/icons/runs/bell-v4/bell/renders/top.png` |
| 17 | d7 | d7-v3 | 4 | 3 | PASS | 6 | 0.472 | STANDING | 6x10 | `verify/digits/runs/d7-v3/d7/renders/top.png` |
| 18 | d0 | d0-v8 | 1 | 6 | PASS | 5 | 0.432 | STANDING | 6x8 | `verify/digits/runs/d0-v8/d0/renders/top.png` |
| 19 | u | u-v4 | 1 | 3 | PASS | 7 | 0.432 | STANDING | 8x6 | `verify/letters-a/runs/u-v4/u/renders/top.png` |
| 20 | triangle | triangle-v4 | 1 | 3 | PASS | 8 | 0.432 | STANDING | 7x9 | `verify/geometric/runs/triangle-v4/triangle/renders/top.png` |
| 21 | anchor | anchor-v4 | 1 | 3 | PASS | 11 | 0.432 | STANDING | 8x8 | `verify/icons/runs/anchor-v4/anchor/renders/top.png` |
| 22 | e | e-v3 | 2 | 3 | PASS | 11 | 0.432 | STANDING | 6x7 | `verify2/letters-a/runs/e-v3/e/renders/top.png` |
| 23 | square | square-v1 | 1 | 3 | PASS | 5 | 0.407 | STANDING | 8x8 | `verify/geometric/runs/square-v1/square/renders/top.png` |
| 24 | spiral | spiral-v1 | 1 | 3 | PASS | 5 | 0.404 | STANDING | 8x8 | `verify/geometric/runs/spiral-v1/spiral/renders/top.png` |
| 25 | y | y-v2 | 2 | 6 | PASS | 14 | 0.267 | STANDING | 9x9 | `letters-b/runs/y-v2/y/renders/top.png` |
| 26 | hourglass | hourglass-v4 | 1 | 3 | PASS | 11 | 0.074 | STANDING | 5x7 | `verify/geometric/runs/hourglass-v4/hourglass/renders/top.png` |
| 27 | d6 | d6-v7 | 1 | 3 | PASS | 5 | 0.06 | STANDING | 6x8 | `verify/digits/runs/d6-v7/d6/renders/top.png` |
| 28 | d9 | d9-v6 | 1 | 3 | PASS | 5 | 0.06 | STANDING | 6x8 | `verify/digits/runs/d9-v6/d9/renders/top.png` |
| 29 | flag | flag-v2 | 1 | 6 | PASS | 6 | 0.06 | STANDING | 7x9 | `verify/icons/runs/flag-v2/flag/renders/top.png` |
| 30 | f | f-v3 | 2 | 3 | PASS | 8 | 0.06 | STANDING | 6x9 | `letters-a/runs/f-v3/f/renders/top.png` |
| 31 | ring | ring-v1 | 1 | 3 | PASS | 10 | 0.0 | STANDING | 7x8 | `verify/geometric/runs/ring-v1/ring/renders/top.png` |
| 32 | boat | boat-v6 | 2 | 3 | PASS | 16 | 0.0 | STANDING | 9x6 | `verify2/icons/runs/boat-v6/boat/renders/top.png` |
| 33 | umbrella | umbrella-v7 | 2 | 6 | PASS | 18 | 0.0 | STANDING | 7x9 | `verify2/icons/runs/umbrella-v7/umbrella/renders/top.png` |
| 34 | i | i-v9 | 2 | 3 | violating (1) | 9 | 0.0 | flat | 8x7 | `letters-b/runs/i-v9/i/renders/top.png` |
| 35 | d4 | d4-v5 | 5 | 3 | violating (3) | 10 | 0.0 | flat | 6x8 | `digits/runs/d4-v5/d4/renders/top.png` |
| 36 | a | a-v4 | 4 | 3 | violating (5) | 12 | 0.0 | flat | 7x8 | `letters-b/runs/a-v4/a/renders/top.png` |
| 37 | z | z-v5 | 2 | 3 | violating (16) | 13 | 0.0 | flat | 6x6 | `letters-a/runs/z-v5/z/renders/top.png` |
| 38 | tree | tree-v6 | 1 | 3 | violating (12) | 15 | 0.0 | flat | 8x6 | `verify/icons/runs/tree-v6/tree/renders/top.png` |
| 39 | up-arrow | up-arrow-v2 | 1 | 3 | violating (1) | 20 | 0.0 | flat | 5x10 | `verify/geometric/runs/up-arrow-v2/up-arrow/renders/top.png` |
| 40 | l | l-v3 | 2 | 9 | violating (3) | 8 | 0.0 | STANDING | 6x7 | `verify/letters-a/runs/l-v3/l/renders/top.png` |
| 41 | d2 | d2-v2 | 1 | 3 | violating (1) | 17 | 0.0 | STANDING | 5x7 | `verify/digits/runs/d2-v2/d2/renders/top.png` |
| 42 | checkmark | checkmark-v1 | 1 | 3 | violating (1) | 18 | 0.0 | STANDING | 14x10 | `verify/geometric/runs/checkmark-v1/checkmark/renders/top.png` |
| 43 | d5 | d5-v2 | 1 | 3 | violating (1) | 19 | 0.0 | STANDING | 5x7 | `verify/digits/runs/d5-v2/d5/renders/top.png` |
| 44 | crown | crown-v1 | 1 | 0 | roll-UNSAT | - | - | - | 8x4 | - |
| 45 | diamond | diamond-v1 | 1 | 0 | roll-UNSAT | - | - | - | 8x8 | - |
| 46 | double-arrow | double-arrow-v2 | 1 | 0 | roll-UNSAT | - | - | - | 11x5 | - |

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

### i (i-v9) — violating (1)
```
########
...#####
...#....
...#....
...#....
...#####
..######
```
violations: move 8 ground: early sampled table incursion 218.000 mm (limit 40.000 mm)

### d4 (d4-v5) — violating (3)
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
violations: move 1 ground: early sampled table incursion 51.337 mm (limit 40.000 mm), move 5 ground: early sampled table incursion 106.004 mm (limit 40.000 mm), move 8 ground: early sampled table incursion 574.000 mm (limit 40.000 mm)

### a (a-v4) — violating (5)
```
..###..
..#.##.
..#..#.
..#..##
#######
#....##
#....##
#....##
```
violations: move 2 ground: early sampled table incursion 103.393 mm (limit 40.000 mm), move 3 ground: early sampled table incursion 106.004 mm (limit 40.000 mm), move 4 ground: early sampled table incursion 164.000 mm (limit 40.000 mm), move 5 ground: early sampled table incursion 82.000 mm (limit 40.000 mm), move 8 ground: early sampled table incursion 82.000 mm (limit 40.000 mm)

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

### tree (tree-v6) — violating (12)
```
...##...
.######.
.#######
########
...##...
...##...
```
violations: move 1 ground: early sampled table incursion 51.337 mm (limit 40.000 mm), move 3 ground: early sampled table incursion 103.393 mm (limit 40.000 mm), move 4 ground: early sampled table incursion 106.004 mm (limit 40.000 mm), move 5 ground: early sampled table incursion 164.000 mm (limit 40.000 mm), move 6 ground: early sampled table incursion 48.726 mm (limit 40.000 mm), move 7 ground: early sampled table incursion 76.060 mm (limit 40.000 mm), move 9 ground: early sampled table incursion 44.892 mm (limit 40.000 mm), move 10 ground: early sampled table incursion 82.000 mm (limit 40.000 mm), move 11 ground: early sampled table incursion 133.337 mm (limit 40.000 mm), move 12 ground: early sampled table incursion 133.337 mm (limit 40.000 mm), move 13 ground: early sampled table incursion 410.000 mm (limit 40.000 mm), move 14 cad_penetration: early sampled CAD penetration 26.982 mm (limit 6.000 mm)

### up-arrow (up-arrow-v2) — violating (1)
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
violations: move 19 ground: early sampled table incursion 188.004 mm (limit 40.000 mm)

### l (l-v3) — violating (3)
```
###...
###...
###...
###...
###...
######
######
```
violations: move 1 ground: early sampled table incursion 158.060 mm (limit 40.000 mm), move 2 ground: early sampled table incursion 410.000 mm (limit 40.000 mm), move 5 ground: early sampled table incursion 164.000 mm (limit 40.000 mm)

### d2 (d2-v2) — violating (1)
```
#####
####.
...##
#####
#....
#####
#####
```
violations: move 16 ground: early sampled table incursion 133.337 mm (limit 40.000 mm)

### checkmark (checkmark-v1) — violating (1)
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
violations: move 17 ground: early sampled table incursion 246.000 mm (limit 40.000 mm)

### d5 (d5-v2) — violating (1)
```
#####
.####
##...
#####
....#
#####
#####
```
violations: move 18 ground: early sampled table incursion 103.393 mm (limit 40.000 mm)

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
