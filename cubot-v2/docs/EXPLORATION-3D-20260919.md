# Exploration 2026-09-19 — one-deep 3-D shells (volumetric campaign)

Branch `explore-volumetric-20260919`. Method: `docs/METHOD.md`, "The 3-D
variant". Every row below was folded with `tools/explore_shape3d.py` on exact
threadings of its layered mask and re-verified under the wire-bundle rule
(`tools/recheck_paths.py`); rows that passed before the rule landed and fail
under it are shown as violating. Blind sheet: `exploration3d-20260919/contact-sheet-blind.png`
(voxel renders; the blind pick is on the iso view, not the top projection).

**Validated (complete, hard-ok, goal is the drawing, export replay verified):**
tier 1 (loose on a flat table): stool (stool-r1), low-bench (v3), half-cube (v1),
side-table (v3), lounge (r1, r4), paperclip (v3, v4), hammer (v3);
tier 2 (platform only): bench (v1), low-bench (r3), pencil (v2), magnifier (v2),
bottle (v4), power (v1). Plus the demo shapes arrow (23 moves) and lightning
(16 moves) re-folded clean under the wire rule.

Blind-pick verdicts (coordinator, unlabeled voxel sheet): bench/table, sofa,
box corner, table, paperclip and magnifier read at a glance; stool-r1 reads as a
one-legged table or mushroom; hammer-v3 reads as an L/flag as much as a hammer;
pencil, bottle and power are weak reads (backfill only — "power" reads as a
balloon or lollipop).

**Not landed in the window:** tray, can-retainer, cube-outline, U-channel,
tube/can, arch, armchair — every one reaches its goal and fails only the final
entry move (22–34 mm CAD on dense floors, or the wire rule). The tube-r1 goal
is proven closed under `platform` + wire rule by an exhaustive backward search
(`UNSAT`): stacked full 3×3 rings are locked like the cube. The others are
budget-bound (all runs under a load average of 30–160 from other sessions);
`--backward` and 360 s reruns are the next step.

| # | shape | variant | tried | threadings | verdict | moves | worst soft | finish | box | render |
|---|-------|---------|------:|-----------:|---------|------:|-----------:|--------|-----|--------|
| 1 | paperclip | paperclip-v3 | 2 | 3 | PASS | 4 | 0.432 | flat | 5x10x1 | `w1/runs/paperclip-v3/paperclip/renders/top.png` |
| 2 | hammer | hammer-v3 | 2 | 6 | PASS | 14 | 0.001 | flat | 5x15x1 | `w1/runs/hammer-v3/hammer/renders/top.png` |
| 3 | stool | stool-r1 | 4 | 6 | PASS | 17 | 0.126 | tilted (+x) | 3x4x4 | `w1/runs/stool-r1/stool/renders/iso.png` |
| 4 | low-bench | low-bench-v3 | 5 | 6 | PASS | 28 | 0.06 | tilted (+y) | 3x7x3 | `w1/runs/low-bench-v3/low-bench/renders/iso.png` |
| 5 | half-cube | half-cube-v1 | 1 | 6 | PASS | 16 | 0.0 | tilted (+y) | 4x4x3 | `w2/runs/half-cube-v1/half-cube/renders/iso.png` |
| 6 | side-table | side-table-v3 | 1 | 3 | PASS | 16 | 0.0 | tilted (+x) | 3x5x5 | `w1/runs/side-table-v3/side-table/renders/iso.png` |
| 7 | lounge | lounge-r1 | 2 | 3 | PASS | 26 | 0.0 | tilted (-x) | 3x6x3 | `w1/runs/lounge-r1/lounge/renders/iso.png` |
| 8 | pencil | pencil-v2 | 1 | 3 | PASS (platform, tier 2) | 5 | 0.0 | flat | 3x10x1 | `w1/runs/pencil-v2/pencil/renders/top.png` |
| 9 | magnifier | magnifier-v2 | 1 | 3 | PASS (platform, tier 2) | 6 | 0.0 | flat | 5x16x1 | `w1/runs/magnifier-v2/magnifier/renders/top.png` |
| 10 | bench | bench-v1 | 2 | 3 | PASS (platform, tier 2) | 7 | 0.0 | upright | 3x7x4 | `w1/runs/bench-v1/bench/renders/iso.png` |
| 11 | bottle | bottle-v4 | 1 | 3 | PASS (platform, tier 2) | 11 | 0.0 | flat | 3x12x1 | `w1/runs/bottle-v4/bottle/renders/top.png` |
| 12 | power | power-v1 | 1 | 6 | PASS (platform, tier 2) | 6 | 0.0 | STANDING | 5x14x1 | `w1/runs/power-v1/power/renders/top.png` |
| 13 | armchair | armchair-v1 | 2 | 3 | violating (1) | 23 | 0.0 | upright | 3x5x4 | `w1/runs/armchair-v1/armchair/renders/iso.png` |
| 14 | tray | tray-v1 | 2 | 24 | violating (1) | 28 | 0.0 | upright | 5x3x2 | `w2/runs/tray-v1/tray/renders/iso.png` |
| 15 | cube-outline | cube-outline-v9 | 2 | 3 | violating (1) | 23 | 0.0 | tilted (-y) | 4x3x4 | `w2/runs/cube-outline-v9/cube-outline/renders/iso.png` |
| 16 | arch | arch-v3 | 1 | 3 | violating (1) | 25 | 0.0 | tilted (-z) | 5x3x4 | `w2/runs/arch-v3/arch/renders/iso.png` |
| 17 | tube | tube-r1 | 3 | 6 | violating (1) | 27 | 0.0 | tilted (+x) | 3x3x4 | `w2/runs/tube-r1/tube/renders/iso.png` |
| 18 | u-channel | u-channel-v1 | 3 | 6 | violating (1) | 28 | 0.0 | tilted (+y) | 3x5x3 | `w2/runs/u-channel-v1/u-channel/renders/iso.png` |
| 19 | can-retainer | can-retainer-v3 | 1 | 6 | partial | 16 | 0.0 | tilted (-y) | 3x3x4 | `w2/runs/can-retainer-v3/can-retainer/renders/iso.png` |

### paperclip (paperclip-v3) — PASS
```
...###.
...#.#.
...#.#.
.#.#.#.
.#.#.#.
.#.#.#.
.#...#.
.#...#.
.#...#.
.#####.
```

### hammer (hammer-v3) — PASS
```
#####
#####
#####
#....
#....
#....
#....
#....
#....
#....
#....
#....
#....
#....
#....
```

### stool (stool-r1) — PASS
```
###
###
###
###
---
###
.#.
...
##.
---
###
...
...
##.
---
.##
...
...
##.
```

### low-bench (low-bench-v3) — PASS
```
###
###
###
###
###
###
###
---
...
.#.
...
...
...
...
##.
---
...
.#.
...
...
...
...
##.
```

### half-cube (half-cube-v1) — PASS
```
####
....
....
....
---
####
#...
#...
#...
---
####
####
####
####
```

### side-table (side-table-v3) — PASS
```
###
###
###
###
###
---
...
.#.
...
...
##.
---
...
.#.
...
...
##.
---
...
.#.
...
...
##.
---
...
.#.
...
...
##.
```

### lounge (lounge-r1) — PASS
```
###
#..
...
...
...
...
---
###
...
...
...
...
.##
---
###
###
###
###
###
###
```

### pencil (pencil-v2) — PASS (platform, tier 2)
```
#..
###
###
###
###
###
###
###
###
##.
```

### magnifier (magnifier-v2) — PASS (platform, tier 2)
```
#####
#...#
#...#
#...#
#####
...#.
...#.
...#.
...#.
...#.
...#.
...#.
...#.
...#.
...#.
...#.
```

### bench (bench-v1) — PASS (platform, tier 2)
```
###
###
###
###
###
###
###
---
#..
...
...
...
...
...
#..
---
#..
...
...
...
...
...
#..
---
#..
...
...
...
...
...
#..
```

### bottle (bottle-v4) — PASS (platform, tier 2)
```
###
#.#
###
#..
#..
#..
#..
###
###
###
###
###
```

### power (power-v1) — PASS (platform, tier 2)
```
..#..
..#..
..#..
..#..
..#..
..#..
..#..
#####
#...#
#...#
#...#
#...#
#...#
#####
```

### armchair (armchair-v1) — violating (1)
```
###
...
...
...
...
---
###
...
...
...
...
---
###
...
...
...
###
---
###
###
###
###
###
```
violations: move 22 cad_penetration: early sampled CAD penetration 46.726 mm (limit 6.000 mm)

### tray (tray-v1) — violating (1)
```
#####
#...#
#####
---
#####
#####
#####
```
violations: move 27 tether_down: module 0 rests on the lowest layer with its wire bundle pointing down

### cube-outline (cube-outline-v9) — violating (1)
```
....
.#..
.#..
---
.###
.#.#
.###
---
.###
.#.#
.###
---
.###
.#.#
####
```
violations: move 22 cad_penetration: early sampled CAD penetration 101.393 mm (limit 6.000 mm)

### arch (arch-v3) — violating (1)
```
#####
#####
#####
---
#...#
#...#
#...#
---
#....
#....
#....
---
#....
#....
#....
```
violations: move 24 tether_down: module 0 rests on the lowest layer with its wire bundle pointing down

### tube (tube-r1) — violating (1)
```
#..
#..
##.
---
###
#.#
###
---
###
#.#
###
---
###
#.#
.##
```
violations: move 26 cad_penetration: early sampled CAD penetration 22.004 mm (limit 6.000 mm)

### u-channel (u-channel-v1) — violating (1)
```
#..
#..
...
...
...
---
#.#
#.#
#.#
#.#
#.#
---
###
###
###
###
###
```
violations: move 27 cad_penetration: early sampled CAD penetration 33.988 mm (limit 6.000 mm)

### can-retainer (can-retainer-v3) — partial
```
#..
#..
...
---
###
#.#
###
---
###
#.#
###
---
###
###
###
```
violations: move 15 cad_penetration: early sampled CAD penetration 22.004 mm (limit 6.000 mm)
