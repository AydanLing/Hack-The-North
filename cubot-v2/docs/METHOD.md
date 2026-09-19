# How we find shapes — the mask-first method

**Status: preferred method.** Unless a task says otherwise, new shapes are found
this way. It is the approach that produced the most *recognizable and valid*
paths per hour of the four tried on 2026-09-19 (comparison at the bottom), and
its winners flow into `handoff/` through the same exporter as the demo seven.

The idea in one line: **draw the shape so it is recognizable first, let a
six-second gate tell you which drawings the chain can physically be, and spend
the expensive fold search only on those exact drawings.** Recognizability is a
property you put in at the drawing step; every attempt to score it back in
after the fact (Chamfer matching, the atlas "iconicity" ranker) picked
mechanically easy blobs over readable icons.

## The pipeline

```
data/candidates/<category>/<concept>-vN.txt      1. draw   (minutes, human or LLM)
        │
        ▼  tools/explore_shape.py --gate-only     2. gate   (25 ms per mask, proofs not guesses)
        │     structural screen → exact shipped-roll threading
        ▼  tools/explore_shape.py                 3. fold   (≈2.5 min per mask, the only expensive step)
        │     fold ONLY exact threadings of the mask; loose checks; strict reported
        ▼  tools/explore_summary.py               4. summarize
        │     summary.md, contact-sheet-blind.png, handoff-manifest.json
        ▼  human blind pick                       5. judge  (the only recognizability authority)
        │     cubot library pick / --only, register in cubot/generate/parametric.py
        ▼  tools/export_handoff.py --manifest     6. hand off (same checks and schema as the demo seven)
```

### 1. Draw

One concept, several variants, as ASCII masks — `#` filled, `.` empty, top row
first, exactly 27 `#`. Put them in `data/candidates/<category>/<concept>-vN.txt`
(`letters-a`, `letters-b`, `digits`, `geometric`, `icons` exist; add a category
directory if none fits).

Draw for the reader, then for the chain. The exploration workers derived the
planar "turn automaton" of the shipped roll word and checked it against the
solver (`docs/EXPLORATION-20260919.md`, "What the roll word allows"); these
are the consequences that kept the threadable rate at 39 % instead of the
atlas' 1.6 %:

- The chain is one path with two ends, so the mask must be traversable end to
  end: no branch points, no isolated pixels, at most two stroke tips. Three or
  more tips (X, double arrow, crown spikes, symmetric tree, finned rocket) fail
  the degree screen or are roll-UNSAT once fixed.
- **1-wide and 3-wide strokes thread far more often than 2-wide ones.** A
  2-wide stroke must be traversed lengthwise: same-side double turns (a 2-wide
  U-turn) are impossible at joints 2, 3, 6, 7, 12, 16, 25 and zig-zags at
  joints 1, 14, 20, 23. The chunky 2-wide E/F/C/S/Z are all roll-UNSAT.
- **No long 45° diagonals**: strictly alternating turns are allowed for at
  most five consecutive joints, so draw diagonals as 2–1 stepped stairs or as
  square strokes. Diamonds, hourglasses, sine waves and X never thread as
  drawn.
- **27 is odd, so closed rings need a gap**: 0/O/square/ring need a mid-edge
  gap, an inner nub or a chamfered corner; corner gaps are UNSAT.
- In-plane rotation and mirroring never change threadability, so "try the
  mirror" is not a lever; change the stroke, the box or where the ends sit.
- Any two-thick *block* is impossible regardless of drawing
  (`docs/CUBE_FEASIBILITY.md`); only one-deep plates, frames and standing
  shapes fold.
- **A 1-wide stroke cannot enter a 3-wide block at the middle of an edge**: the
  two adjacent block corners become degree-2 cells that force a branch, so the
  gate reports a parity or Hamiltonian failure. Join a stem to a block at a
  block *corner*, or make the block ≥5 wide. This kills symmetric necks and
  stems on 3-wide caps, collars, crossguards and pencil points (the 2026-09-19
  backfill sweep: sword, chess pawn, CN tower, wine glass all failed on it). A
  5×3 block traversed middle-in/middle-out is Hamiltonian but roll-UNSAT in
  every length combination tried; a 5×3 block only threads as a chain *end*
  reached by a straight 1-wide lead (hammer, bottle).
- A concept usually needs 4–8 variants to land one threadable form. Vary
  stroke width, box (5×7 up to 9×9 is typical; a 9×19 staircase also worked),
  which corner is open, and where the two chain ends sit. The finishing
  orientation is not chosen: tall shapes tend to finish STANDING, wide ones
  flat; both are valid demo outcomes.

### 2. Gate (seconds)

```bash
uv run python tools/explore_shape.py --name rocket data/candidates/icons/rocket-v*.txt --gate-only
```

Prints one line per mask: a structural failure stage (`parity`,
`hamiltonian`, `degree`, `connected`, `articulation`, wrong cell count), or
`FOUND, N threadings`, or `UNSAT`. Gating all 261 masks in the repo takes
about seven seconds. Every verdict is a proof — there are no timeouts at the
default node budget — so an `UNSAT` mask should be redrawn, not retried.

### 3. Fold (minutes)

```bash
uv run python tools/explore_shape.py --name rocket data/candidates/icons/rocket-v4.txt \
    --out out/explore-<date>/icons --time-budget 150 -k 2
```

Only masks that threaded. The driver folds *exact threadings of the mask* and
records `goal_is_mask`; a pass on a nearby family substitute is not evidence
about the mask, and `explore_summary.py` drops rows that lack the flag.

Budget rules learned the hard way (`FINDINGS.md`, glyph-atlas entry):

- Use at least **120 s** per mask with the `loose` profile's detour budget of
  8. At 30 s / detour 0 the folder falls back to violating direct-goal plans
  even for shapes known to fold.
- If a mask returns *complete but violating*, rerun once with
  `-k 1 --time-budget 240` before giving up: 23 of the 33 first-pass
  violators in the exploration passed on a later pass. A violating verdict
  means "no passing route found in the budget", not "no passing route exists".
- Run **at most 3 fold processes** on this machine; six workers slow every
  CAD edge check about four-fold and you lose more than you gain.
- One process per concept, `--out` per category, so the per-worker
  `results.jsonl` files merge cleanly.

### 4. Summarize

```bash
uv run python tools/explore_summary.py --out out/explore-<date>
```

Merges every `results.jsonl` under the out dir, keeps the best variant per
concept (pass < violating < partial < threadable-no-plan < UNSAT <
structural), and writes `summary.md`, the numbered blind and labeled contact
sheets, and `handoff-manifest.json` listing every loose-passing row. Commit
`summary.md` as `docs/EXPLORATION-<date>.md` and record the run in
`docs/FINDINGS.md`.

### 5. Judge

Look at `contact-sheet-blind.png` with no labels and name what you see. A
shape you cannot name is not a demo shape no matter how clean its path. Record
the picks with `cubot library pick` (or rebuild the manifest with
`explore_summary.py --only <names>`) and register the winning masks in
`cubot/generate/parametric.py` `_PATTERNS` so `cubot pipeline <name>` can
re-fold them later. Registered exploration winners are *not* added to
`DEMO_NAMES`; the demo seven remain a fixed, numbered review contract.

The optional vision judge (`tools/vision_judge.py`, `uv sync --extra judge`)
annotates the sheet; it never picks.

### 6. Hand off

```bash
uv run python tools/export_handoff.py --manifest out/explore-<date>/handoff-manifest.json
```

A glyph-atlas sweep exports the same way once `tools/discovery_manifest.py`
has written its `handoff-manifest.json` from the sweep's `summary.json`;
`--manifest` may be repeated, and the whole set is rebuilt into the interactive
fold viewer with `python3 ../cubot_urdf/make_fold_viewer.py`.

Every manifest entry goes through exactly the checks the demo seven do: the
recorded moves are replayed with the current kinematics, the replayed states
must equal the recorded goal, the goal FK must equal the record's cells, the
goal must be self-avoiding, and the shipped path's strict verdict is looked up
by move signature. Shapes are numbered after the demo seven (8, 9, …) and
written as `handoff/shapes/NN-<name>/` with `path.json`, `moves.csv`,
`silhouette.txt`, renders, plus a row in `PATHS.md` and `index.json`.
`handoff/tools/replay.py` verifies the result without this package.

`--shape NAME=RUN_DIR` adds a single run; `--no-demo` exports only the
manifest/`--shape` entries (useful for a scratch export). Duplicate names are
refused rather than silently renumbered.

## When to use something else

| Situation | Use |
|---|---|
| A concept you drew is `UNSAT` in every variant (x, diamond, crown, star, house…) | Boundary perturbation from `cubot/generate/glyph_atlas.py` as a **repair** step around your drawing, then gate the results. This is what the arrow contour search did by hand (15,099 variants → 68 threadable). |
| You want breadth you cannot draw (a whole alphabet in one sweep) | `tools/discover_glyphs.py` — but treat its ranking as a threadability filter, not a recognizability ranking, and blind-pick before folding. |
| The demo seven need re-folding after a kinematics or profile change | `uv run cubot pipeline <name>` on the registered icon, then `tools/export_handoff.py` with the default run dir. |
| A two-thick target (any filled 2×2×2 block) | Don't. See `docs/CUBE_FEASIBILITY.md`; the 22 mm hinge-corner sweep locks every one of them. |
| A one-deep 3-D shell (tray, bench, tube, L-corner…) | The 3-D variant below: layered masks, `tools/repair_shell.py`, `tools/explore_shape3d.py`, two acceptance tiers. |

## Why this method won (2026-09-19)

| Approach | Target selection | Compute | Mechanically valid | Recognizable **and** valid |
|---|---|---|---|---|
| Harvest (`harvest-20260919`) | nearest family drawing by Chamfer | 6 min / 10 icons | 9 / 10 | 1 / 10 |
| Recognition-first demo (`demo`, `plus-search`, `arrow-broader-search`) | human-authored exact target + exhaustive family rescoring + semantic preflight | hours per shape | 6 / 7 | 6 / 7 |
| Glyph atlas (`discovery-20260919`) | 77 concepts → 4 generators → 35,847 masks → 1.6 % thread → "iconicity" rank → fold 56 | ~63 min | 35 / 56 | roughly half by eye; the top-ranked forms were degenerate |
| **Mask-first (`explore-20260919`)** | hand-drawn masks, 39 % thread, fold exact threadings only | 7 s gate + ~2.5 min per fold | 42 / 47 concepts | nearly all, because recognizability was designed in |

The mask-first method is the recognition-first demo method with the
per-shape human hours replaced by a few sketches and a seven-second gate. Its
remaining losses are on the fold side: of 304 loose violations logged in the
exploration, 250 were table incursions, 30 CAD penetrations and 24 rest-cell
overlaps. Table awareness in the folder and lattice-only pre-screening of the
up-to-64 threadings per mask are the two improvements that would move that
number; neither changes this workflow.

## The 3-D variant — one-deep shells

Solid volumes are impossible, but *hollow one-thick shells* — perpendicular
plates joined along edges (L-corner, tray, U-channel cradle, bench = top plate
plus two legs, standing square tube, arch) — thread under the shipped roll at
about the same rate as flat drawings (~30 % first draw) and some of them fold
on a flat table. The workflow is the mask-first loop with three additions.

```
data/candidates/volumetric/<concept>-vN.txt    1. draw   layered mask (z-slices, TOP layer first, `---` between)
        │
        ▼  tools/repair_shell.py gate --iso    2. gate   screen + threading + 2x2x2 screen + dense count + voxel PNG
        │  tools/repair_shell.py repair        2b. repair single-cell perturbation of an UNSAT base (20–40 s)
        ▼  tools/explore_shape3d.py            3. fold   exact threadings; loose first (tier 1), then platform (tier 2)
        ▼  tools/explore_summary.py            4. summarize   tier column, voxel contact sheet, manifest with tier/profile
        ▼  blind pick on the voxel sheet       5. judge
        ▼  tools/export_handoff.py --manifest  6. hand off   layered silhouette, accept_profile/tier recorded
```

- **Draw** plates 1 or 3 cubes wide; put chain ends at plate corners; exactly
  two legs (a four-leg table is a tree). For stools and benches, inset a leg one
  row from the end of the top plate — flush legs were roll-UNSAT or parity-fail
  in every variant tried. Never draw a filled 2×2×2 block: a "shell" containing
  one is a solid in disguise (a cube-outline-plus-column variant completed and
  then measured exactly 22.004 mm on its last move). `has_2x2x2_block` is exact
  and free, and both tools reject on it.
- **Two tiers.** `loose` on a flat table is tier 1 (the L-corner passes it: 18
  moves, no violations). `config/profiles/platform.toml` is `loose` with the
  table removed — the robot folds on a raised platform — and is tier 2. Both
  verdicts are recorded on every row and in the handoff (`status.accept_profile`,
  `status.tier`, `loose_hard_ok`, `platform_hard_ok`); a tier-2 pass never
  replaces the loose verdict.
- **Orientation is an outcome.** `goal_reached` compares joint states only, so a
  forward fold may finish with the drawn +z pointing sideways
  (`final_up_axis`, reported never failed). `--backward` folds from the goal to
  the straight chain and certifies the reversed route with a forward
  `replay()` — CAD is time-symmetric, gravity is not — which fixes the finishing
  orientation by construction.
- Judge from `renders/iso.png` (solid voxels, `cubot.viz.render_voxels`); the
  top view of a shell is only a projection.
