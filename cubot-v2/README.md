# CuBot V2

Offline, pre-simulation planning for a 27-module body-diagonal folding chain.
The pipeline turns flat icon targets into roll-compatible lattice paths, searches
for signed fold sequences, applies sampled CAD/ground/load checks, and writes
ranked records for later MuJoCo validation.

Each joint has exactly three legal positions: `-1`, `0`, and `+1`, meaning
−120°, 0°, and +120°. The planner never uses congruent ±2 winding states.
The current recognition-first demo vocabulary is heart, arrow, lightning,
plus/cross, H, T, and N.

The shipped arrow is an exact 27-cell open-chevron outline with a complete
loose-passing fold path. The shipped plus is an exact thick cross selected from
complete flat-family searches and also has complete loose-passing paths. These
authored semantic landmarks are reviewed independently from numeric matching:
a distance of zero proves replay fidelity, not recognizability.

```bash
uv sync --extra dev
uv run pytest
uv run cubot pipeline heart --profile loose --strict-report --out out/runs
uv run cubot harvest --duration 1800 --out out/harvest \
  --icons heart arrow lightning plus h t n \
  --family data/family/shipped-8x8.npz --library out/harvest/library
uv run cubot library list --root out/harvest/library
```

Every pipeline run writes `record.json`, `checked-plan.json`, loose and strict
reports, a clean recognition silhouette, a separate numbered engineering
render, an isometric render, and a numbered contact sheet. Harvest state is
flushed after each icon, so rerunning the same seeded command resumes safely.
The committed proposal cache is treated only as a proposal source: current FK,
folder, and check profiles revalidate every route before it can be marked
checked. Record human picks with `cubot library pick ...` after reviewing the
numbered sheet; rerunning the pipeline preserves those picks.

The finalized seven demo paths are exported to `handoff/` — a self-contained,
dependency-free folder (JSON, CSV, PNG, one pure-Python verifier) meant to be
handed to the MuJoCo sim owner. See `handoff/README.md` for the conventions and
`handoff/PATHS.md` for the move lists. Regenerate it with
`uv run python tools/export_handoff.py` after a new planner run.

New shapes are discovered with `tools/discover_glyphs.py`: a glyph atlas
(letters, digits, symbols, icons) is expanded into tens of thousands of exact
27-cell masks by four generators (parametric thick strokes, bitmap size
ladders, compass-run templates, boundary perturbation), every mask is solved
for an exact shipped-roll threading, the threadable ones are ranked offline
by recognition distance and legibility, and a shortlist is folded through the
standard pipeline within a wall-clock budget. See `docs/DISCOVERY.md` for the
latest sweep and `uv run python tools/discover_glyphs.py --help` for the
stages. Recognizability is still decided by a human blind pick.

MuJoCo, hardware drivers, voice, and LLM generation are deliberately not
dependencies of this project. The optional `judge` extra
(`uv sync --extra judge`) enables a Claude blind-naming annotation on the
discovery summary; it never ranks or picks.
