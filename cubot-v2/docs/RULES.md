# Pre-simulation rules

The lattice, roll word, signed travel, rest-cell occupancy, sampled CAD sweep,
table depth, and torque-stall checks can reject a candidate. Near contact,
smaller ground dips, torque above the working cap, balance, holding load, and
moving-side ambiguity are reported as scores.

Every joint has exactly three physical states: `-1`, `0`, and `+1`, at −120°,
0°, and +120°. A geometry residue of `2` is stored as `-1`. States outside
this set and moves that would cross either limit are hard-invalid; there is no
alternate long-way winding.

Recognizability is an earlier gate than mechanics. Demo candidates are reviewed
as clean, unlabeled silhouettes. Matching must preserve the concept's defining
landmarks; foldability cannot compensate for an unreadable icon.

`loose` defines the working acceptance gate. `strict` is always reported and
does not silently replace the working result. MuJoCo remains the eventual
physics verdict.

Search results preserve three separate facts:

1. whether a complete joint path reached the goal;
2. whether that path passed the selected pre-simulation checks;
3. whether the search exhausted a sound state graph or only hit its budget.

A goal-side escape probe is diagnostic because gravity-based moving-side and
table rules can make the graph directed. Only exhaustive forward closure from
the start may be labelled `UNSAT`.
