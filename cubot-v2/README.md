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
`uv run python tools/export_handoff.py` after a new planner run; add
exploration winners with `--manifest` or `--shape NAME=RUN_DIR`. The
committed `handoff/` currently carries 84 paths — the demo seven, the 42
exploration winners and the 35 loose-passing glyph-atlas candidates
(`tools/discovery_manifest.py` turns a discovery `summary.json` into the same
manifest form) — and `../cubot_urdf/make_fold_viewer.py` bundles all of them
into the interactive fold viewer.

New shapes are found with the **mask-first method** (`docs/METHOD.md`), the
preferred way unless a task says otherwise: draw a few recognizable 27-cell
ASCII masks per concept under `data/candidates/<category>/`, gate them in
seconds (`tools/explore_shape.py --gate-only` — structural screen plus exact
shipped-roll threading, every verdict a proof), fold only the exact threadings
of the masks that survive, summarize with `tools/explore_summary.py`, blind-pick
from the unlabeled contact sheet, and export the picks with
`tools/export_handoff.py --manifest <out>/handoff-manifest.json`. Exploration
winners land in `handoff/` numbered after the demo seven, through the same
replay and consistency checks. The 2026-09-19 run took 47 concepts to 42
loose-passing exact masks (`docs/EXPLORATION-20260919.md`).

`tools/discover_glyphs.py` (the glyph atlas: generators → threading → offline
rank → fold, `docs/DISCOVERY.md`) remains available for breadth sweeps and for
boundary-perturbation *repair* of a hand-drawn concept that is roll-UNSAT, but
its ranking is a threadability filter, not a recognizability judgment; only
1.6 % of generated masks thread versus 39 % of hand-drawn ones.
Recognizability is always decided by a human blind pick.

The first cube is tethered (servo bus and power leave through its mount
face).  `config/machine.toml` models that bundle as a rigid keep-out on module
0 (`tether_length_mm`, `tether_width_mm`); every sweep, rest check and
threading honours it, and `tools/tether_audit.py` replays shipped paths
against it (`docs/TETHER.md`).

MuJoCo, hardware drivers, voice, and LLM generation are deliberately not
dependencies of this project. The optional `judge` extra
(`uv sync --extra judge`) enables a Claude blind-naming annotation on the
discovery summary; it never ranks or picks.
