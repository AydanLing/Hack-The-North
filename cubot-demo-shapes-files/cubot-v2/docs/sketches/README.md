# Fitted sketch targets

Fourteen 27-cell goal poses that thread on the shipped roll, produced from
rough hand sketches by `tools/sketch_fit.py`, plus the renders used to judge
whether they still look like anything.

This folder exists to answer one question that came out of drafting
`../DEMO_SHAPE_IDEAS.md`: *if threading a new icon is just a compute problem,
how many new icons can we actually have?* The answer is not the one the
threading numbers suggest.

## Contents

| file | what it is |
|------|------------|
| `demo-sketches.txt` | the fourteen input sketches, drawn by hand, none of them legal |
| `threadable-targets.txt` | the fourteen fitted masks that thread, with rank and IoU in each heading |
| `renders/<name>-silhouette.png` | clean silhouette per shape, for recognition review |
| `renders/<name>-iso.png` | isometric view per shape |
| `renders/contact-sheet-labeled.png` | all fourteen with names |
| `renders/contact-sheet-blind.png` | all fourteen without names — **use this one** |

Both files use `=== name` blocks of `.`/`#` rows; lines before the first `===`
are comments and are ignored by the parser.

## What these are, and what they are not

Each mask in `threadable-targets.txt` is a **goal pose**: a 27-cell shape that
the chain can occupy, verified three independent ways (the fitter's own solver
call, a `cubot screen` run per shape, and a re-solve during rendering).

It is **not a fold**. There is no move order, no CAD sweep, no table check. The
next step for any of these is:

```bash
uv run cubot fold docs/sketches/threadable-targets.txt --profile loose
```

Expect failures there. Lightning is a shipped icon with a perfectly good goal
pose and still has no loose-passing route, because six of its moves swing the
chain through the table.

## The result worth knowing

All fourteen sketches threaded. **One of the fourteen still reads as the thing
it was drawn from.**

| verdict | shapes |
|---------|--------|
| unambiguous | spiral |
| marginal | cloud, cat-face |
| failed recognition | mushroom, skull, star, donut, rabbit, smiley, space-invader, goose, pacman, ghost, maple-leaf |

Two things that follow:

**IoU is not recognition.** Mushroom retained 90% overlap with its sketch — the
highest of anything tested — and still came back reading as a plus sign,
because the search flattened the cap into a rectangle. Skull threaded early, at
rank 97, and reads as a building with windows. Neither number predicted the
outcome; only looking did.

**Topological shapes survive, featural shapes do not.** The spiral won because
there is no small detail in it to lose: any inward self-avoiding coil is still
a spiral. Everything that failed depended on a specific small feature in a
specific place — Pac-Man's wedge, a smiley's eye spacing, a cat's ears, a
maple leaf's lobes — and the variant walk moves cells precisely there. When
picking the next icon, prefer shapes whose identity is a *path property*:
spirals, mazes, zigzags, concentric rings, space-filling curves, knots.

## Reproducing

```bash
# fit sketches to threadable targets (about two minutes of CPU per sketch)
uv run python tools/sketch_fit.py docs/sketches/demo-sketches.txt \
    --out docs/sketches/threadable-targets.txt \
    --walks 16 --steps 6000 --tests 4000 --seed 11

# render silhouettes, isos and both contact sheets
uv run python tools/render_sketches.py

# confirm any single mask independently
uv run cubot screen <one-mask.txt>
```

`sketch_fit.py` is seeded, so the same command reproduces the same fourteen
masks. Changing `--seed`, `--walks` or `--steps` explores a different part of
each neighbourhood and will return different targets — which is worth doing,
since a different draw of the same sketch may keep more of its likeness.
