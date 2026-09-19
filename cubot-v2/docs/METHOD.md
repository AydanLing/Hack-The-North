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
| A 3-D or two-thick target | Don't. See `docs/CUBE_FEASIBILITY.md`; only one-deep plates, frames and standing shapes fold. |

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
