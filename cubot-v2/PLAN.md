# CuBot V2 — pre-simulation phase

This project implements the pre-simulation phase:

1. exact shipped-roll integer kinematics and heart certificate;
2. flat path screening, threadability, family search, and icon matching;
3. signed fold-order search with CAD sweep, table, and torque checks;
4. ranked passing/violating/partial candidates, renders, contact sheets, and a
   checked library suitable for later MuJoCo replay.

Hardware state is constrained to exactly three positions per joint: −120°, 0°,
and +120°, represented as `-1`, `0`, and `+1`. Geometry residue `2` is
canonicalized to physical state `-1`; ±2 winding states are invalid.

The recognition-first demo set is heart, arrow, lightning bolt, plus/cross, H,
T, and N. Clean unlabeled silhouettes are selected before fold planning so a
physics-feasible but visually unreadable approximation cannot enter the demo.
Target quality is a separate semantic gate: an exact self-match only proves
that a certificate replays its authored mask. Arrow targets must retain a
tail, a unique forward direction, and a head on both sides of the shaft; plus
targets must have intersecting contiguous bars reaching all four directions
without a detached nub or hole. Final acceptance still requires a blind human
pick.

Beyond the demo seven, shapes are found with the mask-first method in
`docs/METHOD.md` (draw recognizable exact masks, gate in seconds, fold only
exact threadings, blind-pick, export through the handoff manifest). It is the
default discovery route unless a task says otherwise; the glyph atlas and
family rescoring are secondary tools for breadth and repair.

The implementation is deliberately offline. MuJoCo, hardware drivers, voice,
LLMs, vision judging, unrestricted 3D discovery, and learned optimizers are not
part of this phase.

## Acceptance

- Replay and independently search the heart at an 82 mm pitch.
- Produce ranked, recognizable candidates for the seven demo targets.
- Run a deterministic 30-minute harvest and report loose plus strict checks.
- Require at least five loose-passing candidates to be selected by a human from
  the numbered contact sheet before marking the icon milestone complete.
