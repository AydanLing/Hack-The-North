# handoff-17 (booth default)

**17-cube** fold library used by the iMessage / Linq bridge (`CUBOT_HANDOFF_DIR` default).

Only paths that pass `tools/audit_path_quality.py` are shipped here: moves must be
close to the minimum detents the goal requires (ratio <= 1.5) and no joint may be
bent only to be returned to 0.  `square`, `plus` and `C` were removed on 2026-09-20
for exactly that reason (ratio 2.67 / 2.00 / 1.67) — re-add them only with a mask
whose shortest hard-valid route is clean.

Companion URDF / MuJoCo scene: `cubot_urdf/n17/` (verified as the first 17 modules
of the shipped 27-cube URDF; see `cubot_urdf/n17/VERIFY.md`).
The shorter alternate catalog lives in `../handoff-11/` (not wired into iMessage).
