# Findings

Append-only measurements from the CuBot V2 implementation. Each entry records
the command, config hash, and source revision that produced it.

## 2026-09-19 — corrected joint travel contract

- Hardware clarification: every hinge has exactly three positions, −120°, 0°,
  and +120°, represented in a physical `Pose` as `-1`, `0`, and `+1`.
- Geometry residue `2` remains valid inside orientation tables and flat-family
  caches, but it is converted to physical state `-1` before a `Pose`, threading
  result, plan, or library record is created. There is no ±2 winding state.
- The move graph permits only `-1 ↔ 0 ↔ +1`; changing between the two extremes
  therefore requires two single-detent moves through zero.
- Regression command: `uv run pytest tests/test_config_records.py
  tests/test_lattice.py tests/test_solver.py tests/test_folder.py`.
- Audit result: public pose validation, reference-solver output, detent updates,
  current JSON records, and planning heuristics now share the same contract.

## 2026-09-19 — imported proposal inventory

- Command: `python tools/import_legacy.py --cubot-root ... --snake-root ...`
- Result: 8,052 records normalized into `data/imported/legacy_proposals.jsonl.gz`:
  8,004 harvested flats, 42 statically extracted catalogue entries, five
  shipped picks, and the heart certificate. The 42 catalogue records are also
  kept human-readable in `data/imported/curated.json`.
- Interpretation: all records are untrusted proposals; historical `forms`,
  `physics`, or validation fields were deliberately discarded.

## 2026-09-19 — shipped flat family

- Command: `uv run python` calling `enumerate_flat(shipped, box=(8, 8))`.
- Result: 839,903 oriented 27-module walks from 2,279,309 visited nodes;
  enumeration took 15.46 seconds on this machine.
- Cross-check: exactly matches the legacy `FlatCache` reference count.
- Canonical planar occupancy deduplication leaves 696,085 drawings. The
  straightforward Python canonicalization is much slower than enumeration and
should stay an offline cache-building operation.

## 2026-09-19 — independent heart rediscovery

- Command: `fold(heart.start, heart.goal, time_budget_s=60,
  node_budget=200000, detour_budget=0, search_lying_faces=True,
  max_candidates=1)`.
- Result: a distinct 16-move loose-hard-valid route after 438 checked edges in
  18.95 seconds. Worst measured CAD penetration was 4.329 mm, ground excursion
  35.566 mm, and torque 7.795 N·m. Balance margin reached -51.11 mm and remained
  a named soft outcome as configured.
- Interpretation: this is a generic moment-side folder result and does not use
  the recorded heart certificate order.

## 2026-09-19 — seeded ten-icon harvest

- Command: `cubot harvest --duration 1800 --seed 20260919 -k 1` with the full
  shipped 8x8 family, the normalized legacy proposal cache, a 200,000-node
  folder cap, and zero detours.
- Result: all ten icons produced complete candidates in 338.74 seconds, within
  the 30-minute cap. Nine pass every loose hard check; `music-note` is retained
  as a complete violating candidate. Every icon has a strict comparison report;
  none of the ten passes the strict hard gate.
- Human review remains explicit. No icon is marked picked until a person names
  selections from `out/harvest-20260919/contact-sheet.png`.

## 2026-09-19 — recognition-first seven-shape demo

- The ten-icon nearest-Chamfer sheet above was rejected in human review: only
  the heart was recognizable. Chamfer had hidden missing landmarks and the
  numbered checkerboard render added visual noise.
- Completed matching now ranks silhouette overlap, coarse landmarks, topology,
  proportions, symmetry, and Chamfer. Review renders are single-color
  silhouettes; engineering module numbers are kept in a separate render.
- The demo vocabulary is heart, right arrow, lightning bolt, plus/cross, H, T,
  and N. All seven have exact 27-cell shipped-roll goals and complete physical
  paths using only joint states `-1`, `0`, and `+1`.
- Heart, arrow, plus, H, T, and N pass every loose hard check. Lightning retains
  a complete 14-move kinematic path with six named table-clearance violations;
  it is not represented as a passing plan.
- Strict reports exist for all seven. The six loose-passing routes fail strict
  only on the known 0.398 mm bonded-adjacent CAD contact against strict's zero
  penetration threshold; thresholds were not changed to force a pass.
- Review artifacts and checked plans are under `out/demo-20260919/`. Human
  picks remain unset pending review of `contact-sheet-blind.png`.

## 2026-09-19 — arrow and plus semantic optimization

- The previous arrow exactly matched its authored target but read as a hook or
  loop. The previous plus passed mechanics but had an upper-right nub and an
  overfilled right arm. This demonstrated that self-target distance zero is a
  replay check, not evidence of recognizability.
- Plus search exhaustively rescored 839,903 shipped 8×8 walks and 650,583
  shipped 7×9 walks. All 28 variants of the mathematically perfect centered
  8×8 two-cell-wide cross-minus-one were roll-UNSAT. Family entry 32951 was
  selected instead: it has 27 cells, no detached nub, two complete 22-move
  loose-passing routes, and only the known 0.398 mm bonded-contact finding
  under strict.
- Arrow contour search examined 15,099 outline variants and found 68 direct
  shipped-roll certificates. The selected open-chevron target has two long
  shaft rails, a stepped right head, and one exact mirrored threading with a
  complete 23-move loose-passing route. A filled arrow and a return arrow are
  retained as mechanics-safe alternates but are not the primary visual.
- Semantic preflight now requires arrow direction/head landmarks and
  intersecting four-direction plus bars before numeric matching. Blind human
  selection remains the final recognizability authority; no shape is silently
  marked picked.

## 2026-09-19 — 3×3×3 cube feasibility (negative result, roll-independent)

- Question: can the shipped chain fold a 3×3×3 cube, loosening `loose` a
  little if necessary?  Source revision `0397435`, loose config hash
  `7487b5c67bd18dfb`, pitch 82 mm, hull `data/solids/module.json`.
- Threading and lattice kinematics are not the obstacle.  `solve()` finds
  18 distinct physical state words for the cube under the shipped roll
  (432 threadings over the 24 bases, exhaustive in 51,792 nodes), and a
  rest-overlap-only folder finds complete 17–21 move single-detent paths
  from straight to every one of them
  (`tools/cube_feasibility.py lattice`).
- The obstacle is the continuous hinge geometry.  Sweeping all 1,176
  outgoing moves (52 detents × both sides × 18 words) from the assembled
  cube: 540 end in a rest-cell overlap; the remaining 636 all measure a CAD
  penetration of **22.00 mm** (`tools/cube_feasibility.py escape`).  The
  number is the same for every move because it is the same mechanism: a
  hinge half rotating 120° about the body diagonal swings its three corners
  22 mm out of its own cell into the three face-neighbour cells on the
  moving side, and in a packed cube the third of those cells is always
  occupied.
- Roll-independent check (`tools/cube_feasibility.py last-module`): with
  the hinge module in every cube cell and every one of the 24 orientations,
  the best possible single-module entry into the cube still peaks at 22 mm;
  the hinge-clean corner cases instead hit 30 mm (`H−t`) and 42 mm (`L−t`)
  because the swung module's arc bulges one third of a pitch toward the
  side opposite the hinge's third face.  A module can therefore only land
  where the hinge sits on a one-thick ridge (both neighbours along one axis
  empty or moving), which no cell of a 3×3×3 satisfies.  This is the
  quantitative form of the earlier "one-deep shapes fold, filled boxes
  don't" observation.
- Thresholds cannot reasonably absorb this: `loose` allows 6 mm, the next
  reachable value is 22 mm (27 % of the module side), and the arc-bulge hit
  is edge-on-face, so corner chamfers do not help either — an analytic
  32 mm chamfer still leaves 35 mm.
- Near-cube variants were also probed with goal-side escape probes (all 52
  moves, CAD + rest overlap, table removed): 3×3×3 minus one face-centre
  with the 27th module beside the hole has exactly one legal final move
  (joint 21, 4.33 mm), but its 15-module two-layer core has no legal move
  at any core joint (all ≥ 22 mm), so it cannot be closed; 2×2×2 + tail,
  3×3×2 + tail, and the cube shell minus a face-centre + 2-tail have no
  non-trivial legal moves at all under the shipped roll.
- A greedy forward beam search from straight (real `check_move`, table
  removed, beam 16, depth 26) reaches 16 of 27 cells inside a 3×3×3 window
  after 7 moves and 17 after 25 — a one-deep cage, not a block.
- Separate, acknowledged loosening: building any 3D intermediate on a flat
  table trips `ground_hard_mm` (dips of one full pitch, 82 mm).  A raised
  platform / table-edge lay-down removes that gate; it was applied in the
  probes above and does not change the CAD verdict.
- Decision: the cube stays a geometry regression (Appendix A.3), never a
  target.  Cube-like demos must be one-deep (plates, frames, standing
  shapes).

## 2026-09-19 — glyph-atlas discovery sweep

- Command: `uv run python tools/discover_glyphs.py --out out/discovery-20260919
  --seed 20260919 --dry-run --assert-known --max-variants-per-base 600 --workers 7`,
  then `--stages fold judge report --fold-budget-s 30 --detour-budget 0 --k 2`
  (56 candidates, sequential, 33 min), `--stages fold report --refold
  --detour-budget 8 --fold-budget-s 120 --fold-workers 6` (35 non-passing,
  14 min) and a final `--refold --pick-file rank/picks-refold2.txt
  --fold-budget-s 240 --fold-workers 3 --k 1` on twelve holdouts (16 min).
  Shipped roll, pitch 82, loose gate, strict reported.
- Atlas: 77 glyphs (A–Z, 0–9, symbols, icons) expanded by four generators
  (direction-aware thick strokes, bitmap size ladders, compass-run templates,
  boundary perturbation with chain screens) into 38,416 concept-variants /
  35,847 unique exact-27-cell masks. The shipped h/t/n/plus masks were
  regenerated (`--assert-known`).
- Threading: 587 unique masks (659 concept-variants across 55 concepts) have
  an exact shipped-roll threading; 35,260 are proven UNSAT; zero TIMEOUT at a
  100,000-node budget, so every verdict is a proof. Threadability rate 1.6 %.
  Twenty-two concepts have no exact form at all in this atlas: 3, a, anchor,
  bird, diamond, dog, e, fish, hash, hourglass, house, i, infinity, k, m,
  plane, r, rocket, square-wave, star, umbrella, x.
- Fold: 56 shortlisted (2 per concept, 40 % letter quota); 35 complete and
  loose-passing after the three passes, from 25 concepts: 6, 7, arrow-left,
  b, c, chair, check, d, f, h, hook, j, l, lightning, mug, music-note, o, q,
  spiral, t, table, tree, u, z, zigzag. Every strict verdict fails; most on
  the known 0.398 mm bonded contact, but c-v01/u-v01 (1.45 mm), check-v01
  (1.58 mm), table-v01 (1.58 mm) and chair-v02 (2.98 mm) carry a real
  sub-6 mm penetration on one move and are flagged in the digest.
- Search-budget finding: with detour 0 / 30 s the folder only finds short
  routes and falls back to violating direct-goal plans even for the shipped
  H, N, plus and heart masks; detour 8 with ≥ 120 s of single-core search per
  threading recovers them. Running six fold workers on this 8-core machine
  slows each CAD edge check about four-fold (H: 507 edges in 60 s versus the
  demo run's 656 edges in 43 s), so deep passes should use ≤ 3 workers.
- Vision judge skipped: the optional `judge` extra is not installed and no
  Anthropic credentials were present. Human picks remain unset; review
  `out/discovery-20260919/contact-sheet-folded-blind.png` and record picks
  with `cubot library pick ... --root out/discovery-20260919/library`.
- Digest committed as `docs/DISCOVERY.md`; the folded blind and labeled
  contact sheets are copied to `docs/discovery-20260919/`.

## 2026-09-19 — mask-first exploration and the preferred discovery method

- Command: `tools/explore_shape.py --gate-only` over `data/candidates/**/*.txt`,
  then `tools/explore_shape.py ... --time-budget 150 -k 2` per threadable mask
  with a `-k 1 --time-budget 240` second pass for complete-but-violating
  results; `tools/explore_summary.py --out out/explore-20260919`. Shipped
  roll, pitch 82, loose gate, strict reported. Digest in
  `docs/EXPLORATION-20260919.md`.
- Gate: 261 hand-drawn masks across 47 concepts; 102 (39 %) have an exact
  shipped-roll threading, 96 are proven UNSAT, 63 fail a structural screen
  (35 parity, 9 hamiltonian, 5 degree, 3 connected, 1 articulation, 10 wrong
  cell count). 43 of 47 concepts have at least one threadable variant; gating
  everything takes about seven seconds.
- Fold: 42 of 47 concepts have a complete loose-passing route on the exact
  mask (`goal_is_mask`), 1 is complete but violating (z), 3 are roll-UNSAT
  (crown, diamond, double-arrow), 1 is structurally impossible (x). Of 60
  folded variants, 33 were violating on their first pass and 23 of those
  passed on a later pass with more budget; a violating verdict is a budget
  statement. Of 304 loose violations logged, 250 are table incursion, 30 CAD
  penetration, 24 rest-cell overlap.
- Comparison of the four discovery approaches run today, scored as
  recognizable-and-valid yield: harvest (Chamfer nearest family) 1/10;
  recognition-first authored demo 6/7 at hours per shape; glyph atlas 35/56
  mechanically valid but ranked degenerate forms first (1.6 % of generated
  masks thread); mask-first 42/47 concepts with recognizability designed in.
- Decision: mask-first is the preferred discovery method unless a task says
  otherwise. Documented in `docs/METHOD.md`, referenced from `README.md`,
  `PLAN.md` and `docs/RULES.md`. The glyph atlas is kept as a breadth and
  boundary-repair tool.
- Handoff integration: `tools/explore_summary.py` now writes
  `handoff-manifest.json` (`cubot.handoff.manifest.v1`, loose-passing rows,
  `--only` for picks) and `tools/export_handoff.py` accepts `--manifest`,
  `--shape NAME=RUN_DIR` and `--no-demo`; entries are numbered after the demo
  seven and pass the same replay, goal-FK and self-avoidance checks. Verified
  by exporting the demo seven plus all 42 exploration winners to a scratch
  folder and running `handoff/tools/replay.py` on the result; regression in
  `tests/test_handoff_manifest.py`. `handoff/` itself is unchanged pending the
  blind pick.
- Housekeeping: the glyph-atlas entry above had been appended twice verbatim;
  the duplicate was removed.

## 2026-09-19 — exploration of 47 new common structures

- Command: `uv run python tools/explore_shape.py --name <shape> [--gate-only]
  data/candidates/<category>/<shape>-v*.txt`, run by five parallel workers
  (letters ×2, digits, geometric, icons), then a verification pass of every best
  variant with `-k 2 --time-budget 150` and a second pass with
  `-k 1 --time-budget 240` for masks whose first fold only produced a violating
  plan. Summary: `uv run python tools/explore_summary.py --out out/explore-20260919`.
- Result: 261 masks gated; 47 shapes. 42 have a complete loose-passing plan on
  the exact mask; 1 completes only with violations (the sole threadable "Z",
  which is not a Z); 3 are roll-UNSAT in every variant (crown, diamond, double
  arrow); X is structurally impossible (four stroke tips). 37 winners are
  registered in `cubot/generate/parametric.py` (`EXPLORED_NAMES`); the five
  passing-but-unrecognizable masks (hourglass, rocket, tree, triangle, up-arrow)
  are not. Full table and masks: `docs/EXPLORATION-20260919.md`.
- The pipeline matcher folds nearby family drawings alongside exact threadings
  and ranks plans by fold quality only, so a "PASS" can belong to a substitute
  silhouette. Three workers caught this independently; the driver now folds
  exact threadings only and records `goal_is_mask`. Rows without that flag are
  excluded from the summary.
- The fold search is budget-bound: 18 of the first-pass "complete but
  violating" verdicts (all ground incursion from the direct-replay fallback)
  became clean loose passes at 240 s. A violating verdict at 90–150 s is weak
  evidence about the mask.
- Roll-word structure confirmed by all workers against `solver.solve`: in-plane
  rotation/mirroring never changes threadability; same-side double turns are
  impossible at roll-digit-0 joints (2, 3, 6, 7, 12, 16, 25) and zig-zags at
  roll-digit-2 joints (1, 14, 20, 23); alternating turns run at most 5 joints
  (16–20), so 45° diagonals longer than ~5 cells never thread. 2-wide strokes
  are the hardest width; 1-wide and 3-wide thread far more often.
- Human picks remain unset; `docs/exploration-20260919/contact-sheet-blind.png`
  is the blind sheet for the 37 registered winners.
