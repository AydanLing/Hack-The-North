# Library drawing brief (mask-first, at scale)

You own one category of `data/library-concepts.json`. For every concept in it
(priority 1 first, then priority 2) you produce recognizable 27-cell masks that
the chain can physically be, and you **never fold**. Folding is queued later
by `tools/explore_batch.py` after a blind judge has picked the variants that
read best. Work from `cubot-v2/`.

## Files

- Masks: `data/candidates/<category>/<name>-vN.txt` — `#` filled, `.` empty,
  top row first, exactly 27 `#`, no spaces. `<name>` is the concept name from
  the JSON (with hyphens). Number variants from v1 upward and never overwrite
  a variant you already gated; every mask you tried is evidence.
- Ideals for repair: `data/ideals/<category>/<name>.txt` — `#` required, `?`
  optional, `.` empty; consumed by `tools/design_search.py`.
- Report: `out/library-20260919/<category>/report.md` — one `## <name>`
  section per concept with a gate line per variant, the mask you consider best
  (as a code block), and one honest recognizability sentence ("reads as a cat",
  "reads as a bag, not a cat"). End with a `## Summary` listing concepts with
  ≥1 threadable variant, concepts UNSAT after repair (with the rule that
  killed them), and your top ten by recognizability.

## Commands

```bash
# gate one concept's variants (25 ms per mask; every verdict is a proof)
uv run python tools/explore_shape.py --name cat data/candidates/animals/cat-v*.txt --gate-only

# repair: enumerate the roll-feasible drawings nearest an annotated ideal
uv run python tools/design_search.py --name cat data/ideals/animals/cat.txt \
    --out data/candidates/animals --max 4 --cap 5000 --workers 1
# --ring treats every empty cell touching a '#' as optional; --nudge 300 also
# samples random one-cell nudges of the '#' cells (for ideals without '?').

# see your masks as silhouettes (optional, for your own eyes)
uv run python tools/blind_judge.py sheets --masks 'data/candidates/animals/cat-v*.txt' \
    --out out/library-20260919/animals/preview-cat
```

Gate output per mask is `STRUCTURAL FAIL at <stage>`, `UNSAT, 0 threadings`
or `FOUND, N threadings`. Only `FOUND` masks matter downstream.

## What the chain can be (the rules that decide threadability)

The 27 modules form one path with two ends. At each joint the flat chain can
go straight or turn to *one* forced side (the shipped roll word). Consequences
verified on 261 + 35,847 masks:

1. **Path shape**: connected, no holes needed, no branch points, at most two
   stroke tips (dead ends). Three-tip glyphs (X, crown spikes, symmetric tree,
   finned rocket, forked antlers) fail the `degree` screen or are UNSAT once
   fixed. A 1-wide dead-end stroke pins a chain end there.
2. **Stroke width**: 1-wide and 3-wide strokes thread far more often than
   2-wide. A 2-wide stroke must be traversed lengthwise: same-side double
   turns (2-wide U-turns) are impossible at joints 2, 3, 6, 7, 12, 16, 25 and
   zig-zags at joints 1, 14, 20, 23. Chunky 2-wide E/F/C/S/Z were all UNSAT.
3. **No long 45° diagonals**: strictly alternating turns run at most five
   joints, so draw diagonals as 2–1 stepped stairs or as square strokes.
   Diamonds, hourglass waists, sine waves never thread as drawn.
4. **27 is odd**: a closed ring needs a mid-edge gap, an inner nub or a
   chamfered corner; corner gaps are UNSAT. Two-hole shapes (8) needed 1-wide
   strokes with 3×2 eyes plus a chamfer.
5. **Parity**: on a checkerboard the two colours must count 14/13 with both
   chain ends on the 14 colour. `parity` failures are fixed by moving a tip
   or nudging one cell, not by redrawing.
6. **One deep only**: never draw two-thick blocks (`docs/CUBE_FEASIBILITY.md`).
   Filled blobs are fine as long as the path rules hold; wide filled areas
   read better than thin outlines at this resolution.
7. In-plane rotation and mirroring never change threadability; change the
   stroke, the box, the open corner or where the two ends sit instead.
8. Box: 5×7 to 9×9 is typical; wide glyphs up to 11×5, tall up to 6×11. The
   finishing orientation (flat or standing) is not yours to choose.

Draw for the reader first: the silhouette must carry the concept's defining
landmarks (a cat's ears, a whale's tail, a house's roof + door, a key's bow +
bit). Then reshape for the chain. 4–8 variants per concept is normal; if the
eighth still fails, write an ideal and run `design_search`; if that returns
nothing threadable within distance ~4 of the ideal, record the concept as
UNSAT with the rule that killed it and move on. Do not lower the
recognizability bar to make a concept thread: a passing blob that does not
read is not a library shape.

## Stop conditions

Per concept: ≥2 `FOUND` variants that you believe read, or 8 variants +
repair attempted. Per category: every priority-1 concept handled, then
priority-2 as time allows. Do not run folds, `cubot pipeline`, or anything
with a `--time-budget`; do not edit files outside your category's
`data/candidates/`, `data/ideals/` and `out/library-20260919/` directories.
