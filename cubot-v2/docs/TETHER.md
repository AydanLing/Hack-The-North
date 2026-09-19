# The cable bundle on module 0

The first cube is tethered: its servo bus and power leave through the face a
preceding module would have mounted on (module-local `-x`, the "bottom" of
the chain in snake_pipeline's chain-along-`+z` convention).  Nothing may
collide with that bundle, so from 2026-09-19 the planner models it as a rigid
part of module 0's still half.

## Model (`config/machine.toml`)

| key | default | meaning |
|---|---|---|
| `tether_length_mm` | 82.0 | how far the keep-out box extends from the mount face (one pitch); `0` switches the model off |
| `tether_width_mm` | 40.0 | square cross-section, centred on the face |

`cubot.solid.tether_piece` builds the box; `cubot.geometry` places it with
module 0's still-half frame in every sampled sweep (static on `out` moves,
swinging with the base side on `in` moves).  The checks it adds are all hard:

- **`cad_penetration`** — any module sweeping through the box (same limit as
  module–module contact; module 0's own halves are exempt, as designed).
- **`tether_cell`** (rest stage) — the lattice cell outside module 0's mount
  face must be empty in every rest pose.  `solve(..., tether=True)` applies the
  same rule to threadings, so rings that close against module 0 are never
  proposed; `cubot.match`, `tools/explore_shape.py` and `tools/explore_3d.py`
  pass it.
- **`tether_ground`** (rest stage) and the tether's share of **`ground`**
  (sweep) — the box may not enter the table beyond `ground_hard_mm`.  In
  practice this forbids the base-side `in` flip at joint 0 whose sense turns
  the mount face downward, which is how 18 of the 36 pre-tether paths failed.

The length is the modelling assumption that matters: a bundle that could lie
flat on the table would allow "cable pointing down" poses; a rigid 82 mm stub
does not.  Shorten `tether_length_mm` if the real harness is known to bend
freely at the face.

## Auditing shipped paths

```bash
uv run python tools/tether_audit.py --workers 4        # every handoff/shapes/*/path.json
uv run python tools/tether_audit.py out/<run>/record.json
```

Each path is replayed with and without the tether; only checks that pass
without it and fail with it are attributed to the tether.  Result on the 84
paths shipped before the model existed (`out/tether-audit.json`): 48 clean,
36 violating — 18 by the joint-0 `in` flip (mount face into the table), 9 by a
later base-side `in` move doing the same, 9 by a module resting in or
sweeping through the keep-out (`plus`, `c`, `j`, `d2`, `l`, `d7`, `l-v02`,
`music-note-v02`, `chair-v02`).  Violators are re-folded from their authored masks with
`tools/explore_shape.py` (exact threading, tether-aware) and re-exported.

`config_hash` includes the tether fields, so records made before the model
are distinguishable from records made with it.
