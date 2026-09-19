# Utterance corpus — confusability audit

`data/utterances.jsonl` is the merged, cleaned training corpus for the intent head
(`cubot_imessage/model/`). It is built from the per-category files in `data/utterances/`, which are
left in place as provenance. One JSON object per line, keys `text` and `label`, shuffled
deterministically (`random.Random(20260919)` over a canonically sorted list), so rebuilding the same
inputs reproduces the same file byte for byte.

**4186 rows, 68 classes** (67 shapes + `none`). Minimum 50 rows per class, so the 40-row floor is
met everywhere with no top-ups needed.

## Rows per label (ascending)

| rows | labels |
| --- | --- |
| 50 | letter_q |
| 52 | digit_0, digit_1, digit_2, digit_3, digit_4, digit_5, digit_6, digit_7, digit_8, digit_9, letter_o, letter_p |
| 53 | letter_d, letter_e, letter_g, letter_k, letter_l, letter_m, letter_r |
| 54 | anchor, bell, boat, chair, checkmark, crown, diamond, dumbbell, flag, hook, hourglass, letter_a, letter_b, letter_c, letter_f, letter_i, letter_j, letter_s, letter_u, letter_v, letter_x, mug, mushroom, music_note, rocket, spiral, square, square_wave, staircase, table, tree, triangle, umbrella |
| 55 | letter_w, letter_y, letter_z |
| 56 | ring |
| 68 | letter_n, letter_t |
| 70 | letter_h |
| 71 | arrow_down |
| 72 | arrow_left |
| 73 | arrow_up |
| 79 | plus |
| 83 | arrow |
| 84 | lightning |
| 85 | heart |
| 385 | none |

`heart, arrow, lightning, plus, letter_h, letter_t, letter_n` are the seven demo shapes and are
deliberately over-represented; `none` is the out-of-scope class.

## 1. Duplicate texts across labels

**None found — 0 deletions on this count.** Every row was compared after lower-casing, stripping
punctuation and collapsing whitespace, then again after stripping filler words (`pls`, `plz`, `yo`,
`hey`, `thanks`, `lets go`, …). No text appears under two labels, and no exact duplicate appears
anywhere in the corpus (4186 distinct texts).

One collision existed only under normalization, and it was real poison:

| deleted | label | why |
| --- | --- | --- |
| `✓` | checkmark | strips to the empty string under any ASCII-only preprocessor, making it identical to `none`'s punctuation-only rows (`.`, `...`, `?`, `!`, `??`) |
| `✓ pls` | checkmark | strips to bare `pls`, which is a politeness marker shared by ~every class, not a checkmark signal |

If the encoder's tokenizer is confirmed to preserve `✓`, those two rows can be restored; nothing else
in the corpus depends on non-ASCII text.

## 2. Semantic collisions

Every named danger pair was read row by row. Fixes applied — 4 deletions, 2 rewrites:

| pair | verdict | action |
| --- | --- | --- |
| letter_s / spiral / square_wave | violation | deleted 3 square_wave rows whose only content word was "squiggle" (`fold into a squiggle`, `squiggle pls`, `sqiggle shape`) — a bare squiggle reads as easily as spiral's `swirly shape`. square_wave keeps `squiggly line shape`, `do a wavy line`, `up down up down`, which are not ambiguous. |
| letter_z / lightning / square_wave | clean | the word *zigzag* occurs **only** under square_wave (14 rows); lightning uses bolt/thunder/electric/zeus and letter_z always says "letter z". One exception was fixed: letter_m's `zigzag into the letter m` → **`the letter m with its two peaks`**. `vocab.py` aliases `zigzag -> square-wave`, so exclusive ownership matches the planner. |
| letter_a / the article "a" | clean, 1 fix | letter_u's `the letter a u turn is named after` contained the literal string "the letter a" → rewritten to **`the letter that a u turn is named after`**. |
| music_note / none | violation | deleted `play me a tune` from music_note — its natural reading is "play music at me", which is an action request and belongs with `none`'s `sing me a song` / `beatbox` / `whistle`. |
| letter_o / ring / digit_0 | clean | ring never uses "o" or "zero" (it uses circle/loop/hoop/donut/wheel/bagel); digit_0 rows always carry number/digit/numeral/zero; letter_o rows always carry letter/capital/alphabet. |
| letter_x / plus / checkmark | clean | plus owns cross/first-aid/add; checkmark owns check/tick; letter_x is always letter-cued (one row even says `the letter x, alphabet letter not a symbol`). |
| letter_i / digit_1 | clean | digit_1's idioms all keep a numeric cue (`we're #1, flash it`, `gold medal number, the digit 1`); letter_i is always letter-cued. |
| digit_8 / hourglass | clean | every pinched-shape idiom (`narrow waist`, `two triangles tip to tip`, `bow tie shape`) names *hourglass* in the same row. |
| tree / triangle | clean | disjoint vocabularies — triangle: pyramid/tent/roof/yield sign/pizza slice/delta; tree: pine/fir/evergreen/oak/trunk and branches. |
| bell / ring | clean | the 4 bell rows containing "ring" all also contain "bell" (`ring the bell`), and no ring row is the bare word `ring`. |
| mug / ring | clean | mug is cup/coffee/tea/handle/caffeine; no overlap with ring's round-object idioms. |
| letter_j / hook | borderline, kept | hook keeps `hook like a j` and `j shaped hook pls`; both have *hook* as the head noun, so the human reading is unambiguous, but these are the two rows most likely to show up in a letter_j↔hook confusion. |
| arrow / arrow_up / arrow_down / arrow_left | clean | there is no `arrow_right` class, and `vocab.py` maps `arrow_right -> arrow`, so `arrow` correctly carries both *direction unspecified* (`point that way`, `lead the way`) and *rightward* (`point right`, `eastward arrow`). The up/down/left files mirror those idioms with their own direction word; nothing is direction-contradictory. |
| letter_c / "see", letter_u / "u", digit_2 / "to", digit_4 / "for" | clean | no homophone row exists without its letter/number cue. |

Two unlisted pairs I also checked: **staircase / square_wave** (monotonic `going up in steps` vs
alternating `up down up down` — clean) and **letter_v / checkmark** (checkmark never says "v" — clean).

## 3. Register balance

No rebalancing was needed. The heaviest `make a` / `do a` opening share is **plus at 15.2%**
(12/79), then triangle and square_wave at 13.0%, ring at 12.5%; every other label is under 12% and
the letter/digit families sit at 2–10%. Nothing approaches the 30% ceiling, so no rows were
rewritten for register.

## 4. Coverage floor

Every label was already at 50+ rows, so nothing had to be topped up to reach 40. Six rows were added
only to replace the deletions above, in each label's existing style, so no label lost content:

- square_wave — `the boxy wave one pls`, `flat topped wave shape please`, `digital clock signal shape`
- checkmark — `the mark that means passed`, `done and dusted, check mark`
- music_note — `band practice, music note shape`

## Known weaknesses (honest list)

1. **`none` is 385 rows, ~7× any shape class and 9% of the corpus.** It is the right class to be
   biggest — most texts to a demo robot are chitchat — but a head trained without class weighting
   will lean toward `none` and reject borderline shape requests. Prefer class weights or a
   confidence/margin threshold tuned on the split, rather than deleting `none` rows.
2. **The 13 "icons" labels are near-isomorphic templates.** anchor, bell, boat, chair, dumbbell,
   flag, mug, mushroom, music_note, rocket, table, tree, umbrella share the same ~35 carrier phrases
   with the noun swapped (`i'd love a X`, `do that X thing`, `u should do a X`, `next up: X`,
   `X pose`). They are separable only by the noun, so these classes teach the model almost nothing
   about phrasing, and a novel phrasing with a known noun is the untested case. Fixable by rewriting
   a third of each file; not fixed here because it would mean regenerating 700 rows.
3. **Idiom depth is uneven.** heart, lightning, plus, arrow, digit_1, mug, rocket, dumbbell have
   genuinely indirect rows (`show hack the north some love`, `channel zeus`, `the medics want their
   symbol`, `point us in the right direction`, `top of the leaderboard, that number`). The
   26 letters and most digits are nearly pure "the letter/number X" paraphrase, with only NATO and
   alphabet-position variation. If a texter says something oblique about a letter, expect a miss.
   letter_q is the thinnest class in the corpus (50 rows) and the hardest to write idioms for.
4. **`hook like a j` / `j shaped hook pls`** (hook) and **`that thing that holds a boat in place`**
   (anchor) are correctly labelled but token-heavy in a sibling's vocabulary. Watch letter_j↔hook and
   anchor↔boat in the confusion matrix.
5. **Corpus/planner mismatch, not a corpus defect but worth knowing.** `vocab.py` lists
   `music-note` under `CUBOT_REJECTED`, and letters b, d, g, o, p, q, r, x, z are neither demo nor
   `CUBOT_PLANNABLE` — the classifier can confidently return a label the planner cannot fold. The
   `rejected` / `unmapped` status path in `vocab.py` is what has to carry those replies.
