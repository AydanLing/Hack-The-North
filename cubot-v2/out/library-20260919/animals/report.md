# Animals — library drawing report (2026-09-19)

Worker: animals. All masks in `data/candidates/animals/`, ideals in `data/ideals/animals/`, silhouette sheets in `out/library-20260919/animals/preview-all/` (plus `preview-bee/`). Gate verdicts below are from `tools/explore_shape.py --gate-only` (re-run into `out/library-20260919/animals/gate/`) **with the module-0 tether keep-out enabled** (`machine.toml` `tether_length_mm = 82`, `solve(..., tether=True)`); the tether trims threading counts on 70 of 142 masks but flips none from FOUND to UNSAT. No folds were run.

Working rules learned on this category (all verified by the gate):

- Two 1-cell pointed tips at the top corners of a block (cat ears, fox ears, crab claws, bat wing tips) are UNSAT in every one of ~540k blob completions tried; the two tips become the chain ends and the roll word cannot start both. Making each tip 2 cells tall on a full-width row (`#.....#/#.....#/#######`) threads reliably, as do heart-style 2-wide lobes.
- Two leg tips at the bottom corners behave the same way (2-tall legs thread, 1-tall do not).
- Any third 1-wide tip (a chin, a tail, a fin, a stinger, a third leg) kills the mask (rule 1), so animals whose silhouette is defined by 3+ protrusions (spider, octopus, fox muzzle, forked tails, antlers) cannot be drawn honestly.
- 1-cell bridges between body segments (ant, bee stripes) fail the checkerboard parity of the segment they enter.

**Note on the module-0 wire stub (operator, mid-run):** module 1 has a cable bundle leaving its mount face, so nothing may occupy or sweep through that keep-out. While this run was in progress the repo gained `tether_length_mm` in `config/machine.toml`, a `tether` flag on `cubot.solver.solve` (the keep-out lattice cell must be empty) and tether pieces in `cubot/solid.py` / `cubot/geometry.py`; `tools/explore_shape.py` passes `tether=machine.has_tether`, so every gate line in this report already honours the flat-threading half of the rule. The sweep/collision half applies at fold time, and the already-shipped `handoff/shapes/*/path.json` must be re-verified against it; that is outside this worker's scope and is flagged upward.

## bat  (priority 1)

```
bat/bat-v1: FOUND, 3 threadings
bat/bat-v2: FOUND, 4 threadings
bat/bat-v3: FOUND, 3 threadings
bat/bat-v4: FOUND, 4 threadings
```

Best: `bat-v3`

```
##...##
##...##
#######
#######
#####..
```

Does not read as a bat (spread wings need jagged tips): reads as a tub or U. Weak; keep for evidence.

## bear  (priority 1)

```
bear/bear-v1: FOUND, 6 threadings
bear/bear-v2: FOUND, 4 threadings
```

Best: `bear-v2`

```
##...##
######.
#.#.###
#######
.#####.
```

Reads as a bear (teddy) face: two round ears, two eye holes, wide muzzle. Good.

## bee  (priority 1)

```
bee/bee-v1: STRUCTURAL FAIL at parity — checkerboard split 16/11; need a 1-cell imbalance
bee/bee-v2: FOUND, 5 threadings
bee/bee-v3: FOUND, 5 threadings
```

Best: `bee-v2`

```
##...##
##...##
####.#.
##.###.
.#.###.
.###...
..##...
```

Threads but does not read as a bee (no stripes possible without holes; two wing lobes on a body read as a tuning fork). Weak; stripes as notches fail parity, stinger tip is a third tip (rule 1).

## bird  (priority 1)

```
bird/bird-v1: UNSAT, 0 threadings
bird/bird-v2: FOUND, 4 threadings
bird/bird-v3: FOUND, 3 threadings
bird/bird-v4: FOUND, 4 threadings
```

Best: `bird-v2`

```
....##.
..#####
..#####
######.
#####..
.####..
```

Reads as a perched bird: head on top, wing block, tail sweeping down-left. Medium.

## butterfly  (priority 1)

```
butterfly/butterfly-v1: UNSAT, 0 threadings
butterfly/butterfly-v2: FOUND, 6 threadings
butterfly/butterfly-v3: FOUND, 5 threadings
```

Best: `butterfly-v2`

```
#####
#####
##.##
.###.
#####
#####
```

Reads as a butterfly (two wing pairs around a waist) or a bow. Medium.

## camel  (priority 1)

```
camel/camel-v1: UNSAT, 0 threadings
camel/camel-v2: FOUND, 3 threadings
camel/camel-v3: FOUND, 5 threadings
camel/camel-v4: FOUND, 10 threadings
```

Best: `camel-v2`

```
.##.##..
.##.##..
########
########
##.....#
```

Reads as a camel: two 2x2 humps on a body with legs. Medium-good.

## cat  (priority 1)

```
cat/cat-v1: UNSAT, 0 threadings
cat/cat-v2: STRUCTURAL FAIL at parity — checkerboard split 15/12; need a 1-cell imbalance
cat/cat-v3: STRUCTURAL FAIL at connected — 2 disconnected components with sizes 25, 2
cat/cat-v4: STRUCTURAL FAIL at parity — checkerboard split 15/12; need a 1-cell imbalance
cat/cat-v5: STRUCTURAL FAIL at parity — checkerboard split 13/14, but odd-cell path endpoints must have majority parity 1; bad endpoint(s): ((6, 2, 0),)
cat/cat-v6: STRUCTURAL FAIL at parity — checkerboard split 14/13, but odd-cell path endpoints must have majority parity 0; bad endpoint(s): ((3, 0, 0),)
cat/cat-v7: STRUCTURAL FAIL at hamiltonian — no Hamiltonian path exists after exhaustive search of 15 nodes
cat/cat-v8: STRUCTURAL FAIL at parity — checkerboard split 12/15; need a 1-cell imbalance
cat/cat-v9: STRUCTURAL FAIL at parity — checkerboard split 15/12; need a 1-cell imbalance
cat/cat-v10: UNSAT, 0 threadings
cat/cat-v11: FOUND, 3 threadings
cat/cat-v12: FOUND, 3 threadings
cat/cat-v13: FOUND, 3 threadings
```

Best: `cat-v11`

```
#.....#
#.....#
#######
.######
.######
...##..
...##..
```

Reads as a cat head (two tall ears on a wide face with a 2-wide chin), though it could pass for a bucket; every pointed-ear + tapered-chin version is UNSAT.

## chicken  (priority 1)

```
chicken/chicken-v1: STRUCTURAL FAIL at articulation — removing (1, 4, 0) creates 3 components
chicken/chicken-v2: FOUND, 4 threadings
chicken/chicken-v3: FOUND, 6 threadings
chicken/chicken-v4: FOUND, 3 threadings
```

Best: `chicken-v3`

```
.##....
###....
###..##
###..##
.######
.######
```

Reads as a chicken weakly: head block, tail up, body; comb was lost. Weak.

## cow  (priority 1)

```
cow/cow-v1: UNSAT, 0 threadings
cow/cow-v2: FOUND, 3 threadings
cow/cow-v3: FOUND, 3 threadings
```

Best: `cow-v2`

```
.....#.#
.....###
.....###
######.#
#####..#
##..####
```

Reads as a cow or bull weakly: horns on a raised head, body, legs. Medium-weak.

## crab  (priority 1)

```
crab/crab-v1: FOUND, 3 threadings
crab/crab-v2: FOUND, 3 threadings
crab/crab-v3: FOUND, 3 threadings
```

Best: `crab-v1`

```
##...##
##...##
#######
#######
#####..
```

Reads as a crab weakly: two claws up over a wide body; could be a basket. Weak.

## deer  (priority 1)

```
deer/deer-v1: FOUND, 4 threadings
deer/deer-v2: UNSAT, 0 threadings
```

Best: `deer-v1`

```
#######
##...##
.#####.
.#####.
.####..
...##..
```

Reads as a moose/deer head-on weakly: flat antler bar over ears and a narrow face. Weak.

## dinosaur  (priority 1)

```
dinosaur/dinosaur-v1: FOUND, 5 threadings
dinosaur/dinosaur-v2: FOUND, 6 threadings
dinosaur/dinosaur-v3: FOUND, 5 threadings
```

Best: `dinosaur-v1`

```
....##
....##
..###.
..###.
#####.
#####.
#####.
##....
```

Reads as a brontosaurus: long neck up on the right, body, legs, tail. Medium.

## dog  (priority 1)

```
dog/dog-v1: UNSAT, 0 threadings
dog/dog-v2: FOUND, 3 threadings
dog/dog-v3: FOUND, 3 threadings
dog/dog-v4: FOUND, 3 threadings
```

Best: `dog-v3`

```
#......
#...###
#..##.#
#######
#######
##...##
```

Reads as a dog in profile: floppy ear, eye hole, body, two legs.

## dolphin  (priority 1)

```
dolphin/dolphin-v1: STRUCTURAL FAIL at connected — 2 disconnected components with sizes 26, 1
dolphin/dolphin-v2: FOUND, 7 threadings
dolphin/dolphin-v3: FOUND, 6 threadings
dolphin/dolphin-v4: FOUND, 3 threadings
```

Best: `dolphin-v3`

```
....##..
....###.
#######.
########
.#######
```

Reads as a dolphin/whale body with dorsal fin and a nose; not clearly a dolphin. Weak.

## duck  (priority 1)

```
duck/duck-v1: FOUND, 3 threadings
duck/duck-v2: FOUND, 4 threadings
duck/duck-v3: FOUND, 4 threadings
```

Best: `duck-v1`

```
.##....
####...
.###...
#######
#######
..####.
```

Reads as a duck: head with bill on the left, body with eye hole. Medium-good.

## elephant  (priority 1)

```
elephant/elephant-v1: UNSAT, 0 threadings
elephant/elephant-v2: FOUND, 3 threadings
elephant/elephant-v3: FOUND, 3 threadings
```

Best: `elephant-v2`

```
....#####
#######.#
#########
##.....##
........#
```

Reads as an elephant weakly: body with trunk dropping at the right; the ear is lost. Medium-weak.

## fish  (priority 1)

```
fish/fish-v1: STRUCTURAL FAIL at parity — checkerboard split 12/15; need a 1-cell imbalance
fish/fish-v2: FOUND, 3 threadings
fish/fish-v3: FOUND, 2 threadings
fish/fish-v4: FOUND, 4 threadings
```

Best: `fish-v4`

```
..#####
#######
#######
..##.##
...####
```

Reads as a fish: fat body, eye hole, forked tail on the left. Medium-good.

## fox  (priority 1)

```
fox/fox-v1: FOUND, 3 threadings
fox/fox-v2: FOUND, 5 threadings
```

Best: `fox-v2`

```
###....
###..##
#######
######.
..####.
...##..
```

Reads as a cat, not a fox: pointed muzzle needs a third tip (rule 1) so it collapses to the cat head. Weak.

## frog  (priority 1)

```
frog/frog-v1: UNSAT, 0 threadings
frog/frog-v2: FOUND, 6 threadings
frog/frog-v3: FOUND, 3 threadings
```

Best: `frog-v2`

```
.#####.
#######
###.###
.#####.
##...##
```

Reads as a frog (bulging eyes, wide body, four splayed feet) though it flirts with space-invader.

## giraffe  (priority 1)

```
giraffe/giraffe-v1: FOUND, 2 threadings
giraffe/giraffe-v2: FOUND, 4 threadings
```

Best: `giraffe-v1`

```
....##
....##
....##
######
######
#####.
##..##
```

Reads as a giraffe: tall 2-wide neck rising from a body with legs. Good.

## horse  (priority 1)

```
horse/horse-v1: FOUND, 2 threadings
horse/horse-v2: FOUND, 2 threadings
```

Best: `horse-v2`

```
.....##.
.....###
.....#.#
######.#
########
##...###
```

Reads as a quadruped with the head up (horse or dog); the mane is lost. Medium.

## mouse  (priority 1)

```
mouse/mouse-v1: FOUND, 5 threadings
mouse/mouse-v2: FOUND, 5 threadings
mouse/mouse-v3: FOUND, 10 threadings
```

Best: `mouse-v3`

```
##....
##....
.#####
######
######
######
```

Reads as a mouse: round ear, body, tail. Medium.

## octopus  (priority 1)

```
octopus/octopus-v1: STRUCTURAL FAIL at parity — checkerboard split 14/13, but odd-cell path endpoints must have majority parity 0; bad endpoint(s): ((3, 0, 0),)
octopus/octopus-v2: STRUCTURAL FAIL at parity — checkerboard split 15/12; need a 1-cell imbalance
octopus/octopus-v3: STRUCTURAL FAIL at connected — 3 disconnected components with sizes 22, 3, 2
octopus/octopus-v4: STRUCTURAL FAIL at parity — checkerboard split 15/12; need a 1-cell imbalance
octopus/octopus-v5: STRUCTURAL FAIL at parity — checkerboard split 14/13, but odd-cell path endpoints must have majority parity 0; bad endpoint(s): ((3, 0, 0),)
```

UNSAT: tentacles are either 3+ tips (rule 1) or a 2-wide comb of same-side U-turns (rule 2); every variant failed parity/connected or is roll-UNSAT.

## owl  (priority 1)

```
owl/owl-v1: FOUND, 3 threadings
owl/owl-v2: FOUND, 5 threadings
owl/owl-v3: FOUND, 3 threadings
```

Best: `owl-v2`

```
##...##
##...##
##.#.#.
####.#.
######.
.####..
```

Reads as an owl: ear tufts and two eye holes on a wide face. Good, best face in the set.

## penguin  (priority 1)

```
penguin/penguin-v1: FOUND, 4 threadings
penguin/penguin-v2: FOUND, 1 threadings
penguin/penguin-v3: FOUND, 4 threadings
penguin/penguin-v4: FOUND, 2 threadings
```

Best: `penguin-v4`

```
.##..
.###.
.###.
#####
#####
###.#
#####
```

Does not read as a penguin (no belly contrast possible); reads as a bottle or a seal. Weak.

## pig  (priority 1)

```
pig/pig-v1: UNSAT, 0 threadings
pig/pig-v2: FOUND, 4 threadings
pig/pig-v3: FOUND, 2 threadings
```

Best: `pig-v2`

```
.######..
########.
###.#####
##....###
```

Reads as a pig only weakly: round body, snout bump, legs; could be a sheep. Weak.

## rabbit  (priority 1)

```
rabbit/rabbit-v1: UNSAT, 0 threadings
rabbit/rabbit-v2: FOUND, 3 threadings
rabbit/rabbit-v3: FOUND, 3 threadings
rabbit/rabbit-v4: FOUND, 4 threadings
```

Best: `rabbit-v2`

```
#.#....
#.#....
#.#....
#.#....
#######
####.##
######.
```

Reads as a rabbit: two tall 1-wide ears over a body block. Good.

## seahorse  (priority 1)

```
seahorse/seahorse-v1: FOUND, 3 threadings
seahorse/seahorse-v2: FOUND, 4 threadings
seahorse/seahorse-v3: FOUND, 3 threadings
```

Best: `seahorse-v1`

```
####..
####..
..##..
..####
..####
.###..
.###..
.###..
```

Reads as a seahorse weakly: head at top-left, curved belly, curled tail. Weak.

## shark  (priority 1)

```
shark/shark-v1: STRUCTURAL FAIL at parity — checkerboard split 13/14, but odd-cell path endpoints must have majority parity 1; bad endpoint(s): ((7, 1, 0),)
shark/shark-v2: FOUND, 3 threadings
shark/shark-v3: FOUND, 6 threadings
shark/shark-v4: FOUND, 5 threadings
```

Best: `shark-v2`

```
....##....
....##....
########..
#########.
...######.
```

Reads as a shark weakly: 2-wide dorsal fin on a long body; forked tails are all UNSAT. Medium-weak.

## sheep  (priority 1)

```
sheep/sheep-v1: UNSAT, 0 threadings
sheep/sheep-v2: FOUND, 5 threadings
sheep/sheep-v3: FOUND, 5 threadings
sheep/sheep-v4: FOUND, 4 threadings
```

Best: `sheep-v2`

```
.######.
.######.
########
###...##
##......
```

Reads as a sheep: cloud body over two legs and a head bump. Medium.

## snail  (priority 1)

```
snail/snail-v1: FOUND, 3 threadings
snail/snail-v2: FOUND, 5 threadings
```

Best: `snail-v1`

```
.######..
.#....#..
.#..#.#..
.#..#.#..
.####.###
.##..####
```

Reads as a snail: rectangular spiral shell with a foot and head. Medium.

## snake  (priority 1)

```
snake/snake-v1: UNSAT, 0 threadings
snake/snake-v2: FOUND, 5 threadings
snake/snake-v3: FOUND, 3 threadings
snake/snake-v4: FOUND, 5 threadings
```

Best: `snake-v2`

```
##.....
#######
.....##
.....#.
.....#.
######.
#......
#######
```

Reads as a snake: 1-wide S stroke with a 2-cell head at the top; strongest read in the set.

## spider  (priority 1)

```
spider/spider-v1: STRUCTURAL FAIL at connected — 11 disconnected components with sizes 7, 7, 5, 1, 1, 1, 1, 1, 1, 1, 1
spider/spider-v2: STRUCTURAL FAIL at parity — checkerboard split 16/11; need a 1-cell imbalance
spider/spider-v3: STRUCTURAL FAIL at parity — checkerboard split 14/13, but odd-cell path endpoints must have majority parity 0; bad endpoint(s): ((3, 0, 0), (3, 4, 0))
spider/spider-v4: STRUCTURAL FAIL at connected — 3 disconnected components with sizes 25, 1, 1
```

UNSAT: every recognisable spider needs 6-8 leg tips; the degree/connected screen kills it (rule 1).

## swan  (priority 1)

```
swan/swan-v1: FOUND, 5 threadings
swan/swan-v2: FOUND, 5 threadings
```

Best: `swan-v1`

```
##....
##....
.#....
.#....
.#####
######
#####.
#####.
```

Reads as a swan: head, 1-wide neck, body block. Medium-good.

## turtle  (priority 1)

```
turtle/turtle-v1: FOUND, 4 threadings
turtle/turtle-v2: FOUND, 4 threadings
turtle/turtle-v3: FOUND, 10 threadings
```

Best: `turtle-v1`

```
......##
...#####
.#######
########
###...##
```

Reads as a turtle: stepped dome shell, head on the right, two feet. Medium.

## whale  (priority 1)

```
whale/whale-v1: FOUND, 8 threadings
whale/whale-v2: FOUND, 8 threadings
whale/whale-v3: FOUND, 5 threadings
```

Best: `whale-v2`

```
......##
.....###
########
#######.
#######.
```

Reads as a whale: long body with a raised tail at the right. Good.

## ant  (priority 2)

```
ant/ant-v1: STRUCTURAL FAIL at parity — checkerboard split 11/16; need a 1-cell imbalance
ant/ant-v2: FOUND, 5 threadings
ant/ant-v3: FOUND, 3 threadings
```

Best: `ant-v2`

```
#######.##
##########
######.##.
```

Reads as a segmented bar, not an ant: legs are tips (rule 1) and 1-cell segment bridges fail parity. Weak.

## flamingo  (priority 2)

```
flamingo/flamingo-v1: FOUND, 5 threadings
flamingo/flamingo-v2: FOUND, 3 threadings
flamingo/flamingo-v3: FOUND, 3 threadings
```

Best: `flamingo-v1`

```
##....
####..
.###..
.#####
.#####
.####.
...##.
...##.
```

Reads as a flamingo/stork weakly: head, neck, body, legs down. Weak-medium.

## kangaroo  (priority 2)

```
kangaroo/kangaroo-v1: FOUND, 4 threadings
kangaroo/kangaroo-v2: FOUND, 4 threadings
```

Best: `kangaroo-v1`

```
....##
....##
....##
..####
..####
######
#####.
.##...
```

Reads as a kangaroo weakly: upright body, head, long tail on the left. Weak.

## ladybug  (priority 2)

```
ladybug/ladybug-v1: FOUND, 4 threadings
ladybug/ladybug-v2: FOUND, 3 threadings
ladybug/ladybug-v3: FOUND, 3 threadings
```

Best: `ladybug-v3`

```
######.
#..####
##.####
.######
.##.##.
```

Reads as a ladybug/beetle: dome with two spot holes and feet. Medium.

## monkey  (priority 2)

```
monkey/monkey-v1: FOUND, 5 threadings
monkey/monkey-v2: FOUND, 5 threadings
```

Best: `monkey-v2`

```
##..##
######
######
.####.
.##...
..#...
.##...
.##...
```

Reads as a bear or cat head, not a monkey; the hanging tail could not thread. Weak.

## worm  (priority 2)

```
worm/worm-v1: FOUND, 2 threadings
worm/worm-v2: FOUND, 4 threadings
worm/worm-v3: FOUND, 4 threadings
```

Best: `worm-v2`

```
####.....
#..#####.
#########
##.######
```

Reads as a caterpillar weakly: head block over a long bumpy body. Weak.

## Summary

Concepts handled: 42 (36 priority 1, 6 priority 2). Concepts with at least one FOUND variant: 40. Masks drawn and gated: 142.

**Threadable (>=1 FOUND):** bat (4), bear (2), bee (2), bird (3), butterfly (2), camel (3), cat (3), chicken (3), cow (2), crab (3), deer (1), dinosaur (3), dog (3), dolphin (3), duck (3), elephant (2), fish (3), fox (2), frog (2), giraffe (2), horse (2), mouse (3), owl (3), penguin (4), pig (2), rabbit (3), seahorse (3), shark (3), sheep (3), snail (2), snake (3), swan (2), turtle (3), whale (3), ant (2), flamingo (3), kangaroo (2), ladybug (3), monkey (2), worm (3)

**UNSAT after repair (rule that killed them):**

- octopus: UNSAT: tentacles are either 3+ tips (rule 1) or a 2-wide comb of same-side U-turns (rule 2); every variant failed parity/connected or is roll-UNSAT.
- spider: UNSAT: every recognisable spider needs 6-8 leg tips; the degree/connected screen kills it (rule 1).

**Threadable but read poorly (keep out of the library unless the blind judge disagrees):** bee, bat, penguin, fox, monkey, ant, kangaroo, crab, pig, chicken, dolphin, seahorse, worm, deer.

**Top ten by recognizability:**

1. snake (snake-v2)
2. owl (owl-v2)
3. rabbit (rabbit-v2)
4. bear (bear-v2)
5. whale (whale-v2)
6. giraffe (giraffe-v1)
7. camel (camel-v2)
8. duck (duck-v1)
9. swan (swan-v1)
10. dog (dog-v3)

Runners-up: fish (fish-v4), cat (cat-v11), turtle (turtle-v1), dinosaur (dinosaur-v1), frog (frog-v2), snail (snail-v1), ladybug (ladybug-v3), butterfly (butterfly-v2), sheep (sheep-v2), mouse (mouse-v3).

Wire-stub caveat for the fold stage is repeated here so it is not missed: add the module-1 wire stub to the collision model before folding any of these, and re-check the already-shipped handoff paths.
