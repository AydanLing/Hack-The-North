# 300 demo shapes for CuBot

A brainstorm list for the Hack the North demo: 300 things a 27-module
body-diagonal chain could fold into, filtered for *audience reaction* first and
sanity-checked against what the planner can actually thread.

The shipped vocabulary is heart, arrow, lightning, plus, H, T, N. That is seven.
This is the pool to pull the next seven — and the finale — from.

## How to read this

Every idea carries a feasibility tag:

| tag | meaning |
|-----|---------|
| **A** | Draws cleanly as a legal 27-cell mask: compact, closed or two-ended, with cells to spare. |
| **B** | Legible but budget-tight, or has a stroke junction that has to be thickened before it can be threaded at all. |
| **C** | Needs something beyond one flat 27-cell fold — a sequence, a standing finish, a prop, a second robot, or a live solver. |

**The tag rates the drawing, not the fold.** Read the reality check below before
you plan a demo around any of these.

## Reality check: threading is easy, recognition is the wall

Measured on this repo while writing this list, in three passes. The third pass
overturned the conclusion of the second, so read to the end before planning
anything.

**Pass one — geometry alone is worthless.** Ten sketches were snapped to masks
that pass *every* geometry screen this codebase checks: exactly 27 cells,
face-connected, 14/13 checkerboard split, at most two correctly-coloured
endpoints, confirmed Hamiltonian. All were handed to the exact shipped-roll
solver. **Nine out of nine threaded: zero.** Drawing a legal mask and drawing a
foldable one are different problems.

**Pass two — the neighbourhood is rich.** The same fourteen sketches were each
given ~10,000 legal variants generated near them, roll-tested best-overlap
first. **Fourteen out of fourteen threaded**, each re-confirmed independently
with `cubot screen`. Feasibility was never the blocker.

**Pass three — then I rendered them and looked.** This is the part that
matters, and it is where my own IoU-based guesses fell apart. IoU against the
sketch turns out to be a *bad* proxy for recognition: a mask can keep 90% of
the drawn cells and still lose the one feature the eye uses to identify it.

| sketch | variants | rank | IoU | reads as the thing, judged from the render? |
|--------|---------:|-----:|----:|---------------------------------------------|
| spiral | 9,058 | **13** | 0.81 | **yes — unambiguous** |
| cloud | 10,877 | 211 | 0.86 | marginal; a lumpy blob, which is arguably what a cloud is |
| cat-face | 10,020 | 93 | 0.82 | marginal; two eye holes and one ear |
| mushroom | 10,306 | 92 | 0.90 | **no** — reads as a plus or a lowercase t |
| skull | 9,641 | 97 | 0.84 | **no** — reads as a building with windows |
| star | 9,826 | 353 | 0.77 | no |
| donut | 10,639 | 1,172 | 0.81 | no — the hole drifted off-centre |
| rabbit | 9,820 | 425 | 0.82 | no |
| smiley | 10,174 | 481 | 0.77 | no — eyes lost |
| space-invader | 9,665 | 122 | 0.74 | no |
| goose | 9,758 | 1,222 | 0.65 | no |
| pacman | 10,466 | 1,954 | 0.63 | no — the wedge is gone |
| ghost | 10,351 | 3,394 | 0.53 | no |
| maple-leaf | 9,997 | 3,004 | 0.50 | no — a blob with a hole |

**One shape out of fourteen survived.** Not one in fourteen *threaded* — all of
them threaded — one stayed recognisable. The renders are in
`docs/sketches/renders/`; judge them yourself on `contact-sheet-blind.png`
before trusting any row above, including the three I marked yes or marginal.

The real lesson, which is not the one I expected:

- **Threading is a solved compute problem.** Roughly 1 in 100 to 1 in 3,000
  legal variants threads. Point enough CPU at any sketch and you get a
  foldable goal pose. This is not where the risk lives.
- **Recognition is the actual constraint, and IoU does not measure it.**
  Mushroom kept the highest overlap of anything tested (0.90) and still stopped
  being a mushroom, because the search flattened the dome. Rank was a better
  signal than IoU but still not reliable — skull threaded at rank 97 and reads
  as a building.
- **Shapes defined by their *path* survive; shapes defined by *features* do
  not.** The spiral won because any inward self-avoiding coil still reads as a
  spiral — there is no small feature for the search to destroy. A cat needs
  its ears in the right place, Pac-Man needs its wedge, a smiley needs two eyes
  at the right spacing, and the variant walk eats exactly those. **Prefer
  shapes whose identity is topological: spirals, mazes, zigzags, knots,
  concentric rings, space-filling curves.** This reorders the whole shortlist.
- **A near-legal sketch still helps**, because it keeps the search from walking
  far — but it is necessary, not sufficient. The maple leaf was disconnected
  with four endpoints and failed at rank 3,004; the mushroom was near-legal,
  threaded at rank 92, and failed anyway.
- **Threading is still not a fold.** Every mask above is a *goal pose* with no
  move order. `cubot fold` comes next, and that is where lightning died.

The fourteen masks are checked in at `docs/sketches/threadable-targets.txt`,
the sketches that produced them in `docs/sketches/demo-sketches.txt`, and the
renders plus labelled and blind contact sheets in `docs/sketches/renders/`.
See `docs/sketches/README.md`.

Treat this document as a ranked list of what to spend search time on, with a
strong prior toward section 13.

## The five rules that decide whether a shape is foldable

Learned from the seven shipped icons; check a sketch against these *before*
you spend a harvest on it.

1. **Exactly 27 cells.** Not 26, not 28. A filled 5×5 is 25 and reads as a
   blob; a 1-cell-wide outline of a 6×6 is 20 and leaves 7 for detail. Detail
   is the scarce resource — spend it on the feature that makes the shape
   *recognisable*, not on symmetry.
2. **At most two loose ends.** The chain is a path, so the silhouette needs a
   Hamiltonian path, and a path has two endpoints. A one-cell-wide stroke
   drawing with three dangling tips (E, sun-with-rays, spider, hamburger menu)
   is *impossible* as drawn. The fix is always the same: fatten the junction to
   2 cells wide so the path can double back through it. Closed loops (O, donut,
   ring) have zero tips and are the safest shapes in the whole list.
3. **Checkerboard parity must split 14/13.** Colour the mask like a chessboard.
   With 27 cells you need a one-cell imbalance, and both path endpoints must sit
   on the *majority* colour. This kills more pretty sketches than anything else,
   and it is not fixable by eye — toggle a cell and re-screen.
4. **It has to thread on the shipped roll.** Geometry passing is necessary, not
   sufficient. The roll word constrains which turn sequences the chain can
   actually make. Run `cubot screen`.
5. **The fold order has to stay off the table.** A shape can be perfectly
   threadable and still fail, because some move swings a long tail through where
   the table is. Compact shapes that fold inward beat long cantilevers. Prefer
   candidates that finish flat; a standing finish is a *feature* for some shapes
   (T, N) and a liability for others.

## Screening a candidate

```bash
# geometry + shipped-roll threading, from an ASCII mask
uv run cubot screen my-sketch.txt

# if it threads, look for a fold order that survives the loose profile
uv run cubot fold my-sketch.txt --profile loose

# full run with renders and a contact sheet
uv run cubot pipeline my-sketch.txt --profile loose --out out/runs
```

`tools/sketch_fit.py` (see the appendix) snaps a rough sketch to the nearest
legal 27-cell mask so you are not hand-counting checkerboards at 3 a.m.

---

## 1. Letters, numbers and marks (1–30)

H, T and N already ship. The rest of the alphabet is the cheapest way to go from
seven shapes to thirty-three, and a robot that folds *any letter a judge names*
is a better demo than a robot with seven memorised tricks.

1. **A** — closed counter, zero loose ends, crossbar is nearly free. The best letter in the alphabet for this machine. `[A]`
2. **B** — two counters in 27 cells is tight; drop to a single fat counter and let the spine carry it. `[B]`
3. **C** — open arc, exactly two ends, no junctions. Near-ideal. `[A]`
4. **D** — one counter, zero tips, wide flat stem. Safest letter after O. `[A]`
5. **E** — three arms off a spine = three tips, impossible as a thin stroke. Fatten the spine to 2 wide. `[B]`
6. **F** — same three-arm problem as E but one arm shorter, so more budget for the fat spine. `[B]`
7. **G** — C plus a spur; the spur is the second endpoint, which works out exactly. `[A]`
8. **I** — serif version only; a bare bar is a boring fold and reads as a line. `[A]`
9. **J** — hook plus stem, two ends, cheap. Good "we can do lowercase too" beat. `[A]`
10. **K** — four-way junction at the spine. Needs a 2×2 thickened joint to survive. `[B]`
11. **L** — trivially foldable, low wow alone. Use it as the opening beat of a word. `[A]`
12. **M** — four tips as drawn; fatten the valleys. Worth it, M reads hugely. `[B]`
13. **N** — shipped. Finishes standing, which actually looks deliberate. `[A]`
14. **O** — a pure ring. Zero endpoints, perfect parity, folds inward. If a new shape has to work on the first try, fold O. `[A]`
15. **P** — counter plus stem; the same shape family as D with a tail. `[A]`
16. **Q** — O plus a tail; the tail is your only endpoint pair, so it lands clean. `[A]`
17. **R** — P with a leg; the leg is a third tip unless the bowl absorbs it. `[B]`
18. **S** — two ends, sinuous, unmistakable at cube resolution. Underrated. `[A]`
19. **U** — two ends, wide, simple. `[A]`
20. **V** — diagonal strokes are stair-steps on a lattice; make it fat or it reads as a checkmark. `[B]`
21. **W** — four tips and a lot of diagonal. The hardest common letter. `[C]`
22. **Y** — three-way junction dead centre. Thicken it or skip it. `[B]`
23. **X** — crossing strokes eat the budget fast and the diagonals stair-step. `[B]`
24. **Z** — three strokes, two ends, reads instantly. A good sibling to the shipped N. `[A]`
25. **Lowercase a / e / g** — the counters are tiny at this resolution; a stunt for a second robot with more modules. `[C]`
26. **Ampersand** — the most impressive glyph in the set if you land it; a spiral with one crossing. `[B]`
27. **Digits 0–9** — 0 is a ring (trivial), 1 and 7 are near-free, 8 needs two counters and is the hard one. Fold a live countdown. `[A]`
28. **@** — spiral inside a ring. Visually the most "how is that one chain?" glyph available. `[B]`
29. **? and !** — the dot is a separate component; bridge it with one cell or fold the mark and let the dot be implied. `[B]`
30. **A judge's initials, on request** — two letters is two folds; the *request* is the demo, not the letters. `[C]`

## 2. Hack the North, Waterloo and Canada (31–50)

Local recognition beats universal recognition in a demo room. Nobody claps for
a generic star; everybody claps for the goose.

31. **Maple leaf** — the single highest-value shape in this document. Fat lobes, a stem as one endpoint, folds compact. `[B]`
32. **Canada goose** — Waterloo's mascot-by-hostility. The laugh is guaranteed and the silhouette (body + neck + beak) has exactly two ends. `[B]`
33. **HTN monogram** — the three shipped letters folded back-to-back as a titled sequence. Zero new planning, big perceived leap. `[A]`
34. **"HACK" spelled over four folds** — four folds, one word, one continuous take. The montage is the demo. `[C]`
35. **CN Tower** — tall, thin, one bulge; finishes standing, which is exactly right for a tower. `[A]`
36. **Black squirrel** — Waterloo campus in-joke; body plus fat tail curl, two ends. `[B]`
37. **Hockey stick and puck** — stick is a fat L, puck is the second component; bridge or imply. `[B]`
38. **Toque** — dome plus brim plus pom. Reads cold, reads Canadian. `[A]`
39. **Beaver** — chunky body, flat tail. Forgiving at this resolution. `[B]`
40. **Poutine** — a fries pile with gravy blobs; abstract enough that the caption does the work. `[C]`
41. **Maple syrup jug** — the little handle loop is the whole joke and costs 4 cells. `[A]`
42. **Snowflake** — six arms, six tips: impossible thin. A three-arm fat version reads fine. `[B]`
43. **Igloo** — dome with an arched door. The door arch is a hole, which the chain likes. `[A]`
44. **Moose antlers** — pure tip problem, but the silhouette is unmistakable if you get it. `[C]`
45. **Loonie** — a ring with a bird glyph inside; the inside is a second component. `[C]`
46. **Trillium** — three fat petals meeting at a thick centre; the junction is naturally thick. `[B]`
47. **E7 / campus building silhouette** — a skyline block with window holes. Cheap and site-specific. `[A]`
48. **Waterloo "W"** — four tips as drawn, same problem as M. `[B]`
49. **Canadian flag** — two bars flanking a leaf; three components unless you bridge them. `[C]`
50. **Ice skate** — blade plus boot, two ends, strong profile. `[B]`

## 3. Tech and sponsor-shaped marks (51–65)

The audience already knows these glyphs, so recognition is free — you spend the
budget on the fold, not on legibility. Ask the sponsor at their booth first;
they will almost always say yes and then film it.

51. **Cloud** — three fat lobes on a flat base, zero tips, ideal parity. Folds like a dream. `[A]`
52. **Chat bubble** — rounded rectangle with a tail. The tail is your endpoint. `[A]`
53. **Infinity loop** — two rings sharing a thick crossing. Zero tips. Genuinely impressive. `[B]`
54. **Terminal prompt `>_`** — chevron plus an underscore bar; two components, or join them into one glyph. `[B]`
55. **Git branch glyph** — a spine with a branching curve; the branch point needs thickening. `[B]`
56. **Cat silhouette (the repo-host one)** — ears are two tips, which is exactly the budget. `[B]`
57. **Rocket** — nose, body, two fins. Fins are tips three and four; fold one fin or fatten the base. `[B]`
58. **Shield** — closed outline, zero tips, folds inward. Very safe. `[A]`
59. **Lightbulb** — bulb plus screw base; the base stripes are free detail. `[A]`
60. **Gear** — teeth are many short tips; a 6-tooth fat version works, a 12-tooth one does not. `[B]`
61. **Database cylinder** — stacked ellipses; cheap, reads instantly to any engineer. `[A]`
62. **Globe with meridians** — a ring with interior bars; the bars are interior, so they thread. `[B]`
63. **Padlock** — body plus shackle loop. Zero tips if the shackle closes. `[A]`
64. **Robot head** — square head, two eye holes, an antenna as the single tip. On-theme and self-referential. `[A]`
65. **Spark / asterisk mark** — radial arms, so a tip problem, but a fat 4-arm version lands. `[B]`

## 4. UI and app icons (66–90)

The whole set shares a visual language, so folding four of them in a row reads
as a *system*, not four tricks.

66. **Play triangle** — stair-stepped diagonal, solid, trivially connected. `[A]`
67. **Pause** — two bars, two components. Bridge at the bottom or skip. `[C]`
68. **Power symbol** — a broken ring with a stem through the gap. Two ends. Iconic. `[A]`
69. **Wifi arcs** — three nested arcs, three components. Fold one thick arc plus the dot instead. `[C]`
70. **Battery** — rectangle outline, nub, interior fill bars. Very forgiving. `[A]`
71. **Hamburger menu** — three disconnected bars. Impossible as drawn; fold it as a bracketed stack. `[C]`
72. **Mouse cursor arrow** — solid, one tail, unmistakable. Excellent first-try shape. `[A]`
73. **Magnifying glass** — ring plus a fat handle. Zero-to-two tips, folds compact. `[A]`
74. **Folder** — tab plus body, closed outline. Cheap. `[A]`
75. **Envelope** — rectangle with a V flap; the flap is interior detail, which threads well. `[A]`
76. **Bell** — dome, flare, clapper. The clapper is the endpoint. `[A]`
77. **Star (favourite)** — five points is five tips; the fat-bodied version has two. Worth the redraw, everyone knows it. `[B]`
78. **Bookmark / ribbon** — rectangle with a notched bottom. Nearly free. `[A]`
79. **Trash can** — body, lid, handle. Lid is a separate bar unless you attach it. `[B]`
80. **Download arrow into a tray** — the shipped arrow rotated plus a tray. Reuses solved geometry. `[A]`
81. **Refresh circular arrow** — a ring with a gap and an arrowhead. The arrowhead is the tip. `[B]`
82. **Location pin** — teardrop with a hole. The hole makes the parity work out. `[A]`
83. **Calendar** — grid outline with two hanger tabs; tabs are two tips exactly. `[A]`
84. **Camera** — body, lens ring, a bump on top. Reads instantly. `[A]`
85. **Speaker / volume** — box plus a flared cone plus waves; drop the waves, keep the cone. `[A]`
86. **Checkmark** — two strokes, two ends, one of the cheapest legible shapes available. `[A]`
87. **X / close** — a crossing junction; fatten the centre. `[B]`
88. **Sliders / settings** — parallel bars with knobs; multiple components. `[C]`
89. **Loading spinner** — a broken ring. Zero-to-two tips, and it *implies motion*, which pairs with the fold. `[A]`
90. **QR finder square** — nested squares, a real scannable-looking motif in 27 cells. `[A]`

## 5. Emoji and reactions (91–110)

The fastest path to a phone coming out of a pocket.

91. **Smiley** — face ring with eye and mouth holes. The holes fix the parity for you. `[A]`
92. **Winking face** — one eye a bar, one a dot. One-cell difference from the smiley, which is a nice "we can do variations" beat. `[A]`
93. **Sad face** — invert the mouth. Pairs with the smiley for a mood-swing bit. `[A]`
94. **Thumbs up** — fist block plus a thumb. The thumb is the single tip. Huge reaction for a cheap shape. `[A]`
95. **Peace sign** — two fingers off a fist; two tips, exactly the budget. `[B]`
96. **Waving hand** — four fingers is four tips. Fold a mitten-hand instead. `[C]`
97. **Fire flame** — asymmetric teardrop with a notch. Forgiving, and looks alive. `[A]`
98. **"100"** — three digits across; needs a wider box than 27 cells allows. Two digits works. `[C]`
99. **Skull** — dome, two eye holes, a jaw. The holes make it legible *and* help the parity. Top-tier shape. `[B]`
100. **Pile of poop** — three stacked lobes plus eyes. It will get the biggest laugh of any shape in this document. `[B]`
101. **Sparkles** — a fat four-point star plus two small ones; the small ones are separate components. `[B]`
102. **Crying-laughing face** — smiley plus tear drops; the drops are detached. `[C]`
103. **Eyes 👀** — two ovals side by side. Two components, but a shared bridge bar reads fine and is *funny*. `[B]`
104. **Alien head** — inverted teardrop with two big slanted eye holes. Very legible. `[A]`
105. **Ghost** — dome with a scalloped hem and two eye holes. The hem scallops are tips; keep to two. `[B]`
106. **Party popper** — cone plus scattered bits; the bits are detached. `[C]`
107. **Flexed bicep** — arm block with a bulge. Reads if you keep the fist. `[B]`
108. **Handshake** — two interlocking blocks; genuinely hard, genuinely impressive if landed. `[C]`
109. **Brain** — a maze-like folded outline. The convolutions are *literally* a snake path, which is thematically perfect. `[B]`
110. **Broken heart** — the shipped heart with a crack. If a single detent turns the finished heart into a broken one, that is the best five seconds in the demo. `[B]`

## 6. Animals (111–140)

Animal silhouettes are the classic "wow" category because the audience reads
them as *organic*, which a grid of cubes has no business being.

111. **Cat, sitting** — the profile (ears, back curve, tail) is the most recognisable animal outline at low resolution. Ears are two tips. `[B]`
112. **Cat face** — triangle ears on a round head, two eye holes. Simpler than the body and nearly as good. `[A]`
113. **Dog, sitting** — like the cat but with a droop ear and a snout. Slightly less legible. `[B]`
114. **Fish** — body plus a forked tail. The fork is two tips; the budget fits exactly. `[A]`
115. **Butterfly** — four wing lobes around a thin body, perfectly symmetric, zero tips if the wings close. Beautiful fold. `[B]`
116. **Bird in flight** — two swept wings and a body; reads from across the room. `[B]`
117. **Penguin** — body blob, flippers, beak. Very forgiving; high cuteness per cell. `[A]`
118. **Owl** — round body, two huge eye holes, ear tufts. The eye holes are free parity help. `[A]`
119. **Rabbit** — body plus two long ears. Two ears is exactly two tips. Clean. `[A]`
120. **Turtle** — dome shell plus four stubby legs and a head: five tips. Fold the shell with two legs showing. `[B]`
121. **Snail** — a spiral shell plus a body. The spiral is a chain doing what a chain does. Underrated. `[A]`
122. **Snake** — the robot *is* a snake. Fold it into a coiled snake and let the joke land. `[A]`
123. **Octopus** — eight arms, eight tips. Impossible as drawn; a three-arm version still reads. `[C]`
124. **Crab** — body plus two big claws; the claws are fat, not thin, so tips stay at two. `[B]`
125. **Whale** — body plus a fluke plus a spout. Big simple mass, very legible. `[A]`
126. **Dolphin** — curved body, dorsal fin, fluke. Elegant, three tips, needs a fat fin. `[B]`
127. **Elephant** — body, trunk, one big ear. The trunk is the endpoint. Great silhouette. `[B]`
128. **Giraffe** — long neck plus a body. Tall, thin, and finishes standing, which suits it. `[B]`
129. **Horse** — four legs is four tips. Needs a fat two-leg profile. `[C]`
130. **T-rex** — big head, tiny arms, thick tail, two legs. One of the best low-res silhouettes in existence. `[B]`
131. **Dragon** — body, wing, tail. Ambitious, and the payoff matches. `[C]`
132. **Bee** — striped body plus two wings. Stripes are interior detail, which threads well. `[A]`
133. **Ant** — three segments plus legs; drop the legs, keep the segments. `[B]`
134. **Spider** — eight legs. Fold a fat-bodied two-leg version or skip. `[C]`
135. **Frog** — squat body, two big eye bumps, folded legs. Cute and compact. `[A]`
136. **Bear** — round body, two round ears, a snout. Very forgiving. `[A]`
137. **Fox** — pointed snout and a huge tail. The tail carries the recognition. `[B]`
138. **Duck** — body, neck, beak. Two ends, compact, cheap. `[A]`
139. **Pig** — round body, snout, curly tail. The curl is a chain flourish. `[A]`
140. **Unicorn** — horse problem plus a horn. Pure stunt. `[C]`

## 7. Food and drink (141–160)

Hackathon-native. Half of these get a laugh from people who have been awake for
thirty hours.

141. **Pizza slice** — triangle with crust and pepperoni holes. The holes help parity. `[A]`
142. **Burger** — stacked bands (bun, patty, bun). Trivially connected, instantly legible. `[A]`
143. **Coffee cup** — cup plus a handle loop plus steam. Drop the steam, keep the handle. `[A]`
144. **Donut** — a ring. Zero tips, perfect parity, folds inward from every side. The single safest non-letter shape here. `[A]`
145. **Ice cream cone** — cone plus scoop lobes. Two-lobe version is clean. `[A]`
146. **Cupcake** — wrapper trapezoid plus a swirl top. The swirl is a spiral, which threads naturally. `[B]`
147. **Apple** — round body, a stem, one leaf. Stem and leaf are the two tips. Exact fit. `[A]`
148. **Banana** — a fat crescent with two squared ends. Cheap, and funny for no reason. `[A]`
149. **Cherries** — two circles on stems; two components joined at the stem junction. `[B]`
150. **Strawberry** — heart-ish body plus a leafy crown; reuses the solved heart geometry. `[A]`
151. **Taco** — a folded shell (a fold, folding a fold) with filling bumps. `[A]`
152. **Hot dog** — bun bands plus a wavy line of mustard. The wave is interior. `[A]`
153. **Fries** — a carton plus vertical sticks; the sticks are separate tips. Fold the carton with three fat fries. `[B]`
154. **Sushi roll** — a ring with a filled centre. Concentric and very clean. `[A]`
155. **Fried egg** — a blob with an interior yolk hole. Free parity help. `[A]`
156. **Cookie** — circle with chip holes. The holes are the whole idea. `[A]`
157. **Popsicle** — rounded rectangle plus a stick. One tip. Nearly free. `[A]`
158. **Bottle** — body, shoulder, neck, cap. Finishes standing, which suits it perfectly. `[A]`
159. **Wine glass** — bowl, stem, foot. Thin stem, needs care, looks great standing. `[B]`
160. **Energy drink can** — cylinder with a tab. The caption does the joke. `[A]`

## 8. Space and sci-fi (161–180)

161. **Rocket, launching** — nose cone, body, fins, exhaust plume. The plume can be the interior detail. `[B]`
162. **Saturn** — a body with a ring crossing it. The ring makes it unmistakable and costs less than you think. `[B]`
163. **Crescent moon** — a fat crescent, two ends, zero junctions. One of the cheapest beautiful shapes available. `[A]`
164. **Sun with rays** — eight rays, eight tips. Impossible thin; a fat four-ray version works. `[C]`
165. **Four-point star / twinkle** — fat arms, reads as "sparkle", compact. `[A]`
166. **UFO** — dome plus a saucer bar plus light dots. Classic low-res silhouette. `[A]`
167. **Astronaut helmet** — sphere with a visor cut. The visor is an interior hole. `[A]`
168. **Satellite** — body plus two panel wings. Symmetric, two tips. `[B]`
169. **Alien head** — see #104; it belongs to both categories. `[A]`
170. **Space invader** — the canonical pixel-art sprite. Purpose-built for a cube grid, and everyone in the room knows it. High value. `[B]`
171. **Planet with an orbit ring** — two concentric elements; the orbit crossing is the hard part. `[B]`
172. **Comet** — a head with a streaked tail. The streak is a fat stroke; two ends. `[A]`
173. **Big Dipper** — seven disconnected stars. Fold the *connecting line* version instead. `[C]`
174. **Telescope on a tripod** — tube plus legs; legs are tips. `[C]`
175. **Black hole** — a ring with a bright accretion arc. Concentric, zero tips. `[A]`
176. **Lightsaber** — hilt plus blade. A fat line with a textured handle; finishes standing, which is exactly right. `[A]`
177. **Death-star-ish sphere** — circle with an interior dish hole and an equatorial trench. `[B]`
178. **Portal / wormhole** — nested rings. Concentric shapes thread beautifully. `[A]`
179. **Galaxy spiral** — an arm spiralling in. A chain is a natural spiral; this is one of the most "how?" shapes in the list. `[A]`
180. **Launch gantry** — a tower with cross-bracing; finishes standing. `[B]`

## 9. Nature and weather (181–198)

181. **Tree** — trunk plus a fat canopy. The canopy is a blob, the trunk is the tip. Very safe. `[A]`
182. **Leaf** — pointed oval with a centre vein. The vein is interior detail. `[A]`
183. **Flower** — five fat petals around a centre hole. Symmetric and legible. `[B]`
184. **Cactus** — column plus two arms. Two arms, two tips. Exactly the budget, and it finishes standing. `[A]`
185. **Mushroom** — cap plus stem, with gill detail. Chunky and forgiving. `[A]`
186. **Cloud** — see #51. Still the best. `[A]`
187. **Rain cloud** — cloud plus drops; the drops detach. Attach three as a fringe. `[B]`
188. **Lightning bolt** — shipped, and currently the *only* icon with no passing fold route. Re-planning it is a demo win in itself. `[B]`
189. **Snowflake** — see #42. `[B]`
190. **Sun, simple** — a disc with a few fat rays. `[B]`
191. **Rainbow** — nested arcs; three components unless the arcs touch at the ends. `[B]`
192. **Mountain range** — two peaks with a snow line. Peaks are two tips exactly. `[A]`
193. **Wave** — a curling breaker with a spiral lip. Gorgeous, and spirals thread well. `[A]`
194. **Volcano** — trapezoid with a crater notch and a plume. `[A]`
195. **Fire** — see #97. `[A]`
196. **Water drop** — teardrop with a highlight hole. Nearly free, and very clean. `[A]`
197. **Tornado** — a spiral funnel, wide at the top. Reads as motion. `[A]`
198. **Palm tree** — curved trunk plus fronds; fronds are many tips. Two-frond version only. `[B]`

## 10. Objects and tools (199–218)

199. **House** — square plus a roof, with a door hole and a window hole. The holes carry the parity. A reliable early shape. `[A]`
200. **Key** — a bow ring plus a shaft plus teeth. The teeth are short tips; two teeth only. `[B]`
201. **Padlock** — see #63. `[A]`
202. **Hammer** — head block plus a handle. Two ends, dead simple, reads instantly. `[A]`
203. **Wrench** — shaft with two open jaws; the jaws are forks. Single-ended version is cleaner. `[B]`
204. **Scissors** — two blades and two handle loops. The loops are rings, which helps, but it is four tips. `[C]`
205. **Paperclip** — literally a bent wire, which is literally what the robot is. Thematically perfect, and trivially threadable. `[A]`
206. **Pencil** — hexagonal body, a point, an eraser band. One tip. Near-free and very legible. `[A]`
207. **Open book** — two pages with a spine valley. Symmetric, zero tips. `[A]`
208. **Light bulb** — see #59. `[A]`
209. **Umbrella** — canopy dome plus a J-handle. The handle hook is the second end. `[A]`
210. **Anchor** — ring, shank, two flukes, a crossbar. Four tips, but the shape is so iconic it is worth the redraw. `[B]`
211. **Crown** — band plus three points. Three tips; make the points fat. `[B]`
212. **Diamond / gem** — faceted outline with interior facet lines. Symmetric, zero tips, looks expensive. `[A]`
213. **Sword** — blade, crossguard, pommel. Finishes standing, which is the best possible finish for a sword. `[A]`
214. **Shield** — see #58. `[A]`
215. **Bomb** — sphere plus a fuse curl. The fuse is a spiral flourish. `[A]`
216. **Hourglass** — two triangles meeting at a waist, in a frame. Symmetric and thematically great next to a countdown. `[A]`
217. **Clock** — ring with two interior hands. Hands are interior, so they thread; set them to the demo time. `[B]`
218. **Glasses** — two lens rings plus a bridge plus arms. Two rings joined is very threadable. `[B]`

## 11. Games and play (219–240)

219. **Tetromino stack** — a few interlocked tetrominoes. On-the-nose for a cube robot, and the audience gets it instantly. `[A]`
220. **Chess pawn** — base, waist, head. Finishes standing, which is the entire point of a chess piece. `[A]`
221. **Chess knight** — the horse-head profile is the most recognisable game silhouette there is. Standing finish. `[B]`
222. **Dice face** — square with pip holes. The pips are holes, so parity works out, and you can fold different numbers. `[A]`
223. **Spade** — inverted heart plus a stem. Reuses the solved heart geometry, which makes it nearly free. `[A]`
224. **Club** — three lobes plus a stem. Slightly tighter than the spade. `[B]`
225. **Diamond (suit)** — a fat rhombus. Stair-stepped diagonals; the simplest suit. `[A]`
226. **Game controller** — body with two grips and button holes. Reads instantly to anyone under forty. `[B]`
227. **Arcade joystick** — base plus stick plus ball top. Standing finish. `[A]`
228. **D-pad** — the shipped plus with a rounded frame. Free re-skin of solved work. `[A]`
229. **Pac-Man** — a disc with a wedge bitten out. Trivially connected, universally known, and the wedge makes it unmistakable. Top-tier. `[A]`
230. **Pac-Man ghost** — dome plus a scalloped hem plus two eye holes. Pairs with #229 for a two-shape bit. `[B]`
231. **Power-up mushroom** — cap with spot holes plus a stubby stem. `[A]`
232. **Coin / question block** — square with an interior glyph. `[A]`
233. **Pixel sword (RPG)** — stair-stepped blade with a jewelled hilt. `[A]`
234. **Health bar** — a frame with a partial interior fill. Fold it, then *drain* it one module at a time. `[B]`
235. **Domino** — rectangle with a divider bar and pip holes. `[A]`
236. **Dartboard** — concentric rings with a bullseye. Concentric shapes are the chain's happy place. `[A]`
237. **Soccer ball** — circle with interior pentagon lines. The interior lines thread well. `[B]`
238. **Basketball** — circle with two curved interior seams. `[A]`
239. **Bowling pin** — a standing profile, and it finishes standing. `[A]`
240. **Rubik's cube face** — a 3×3 grid with a thick border. A cube robot folding a cube puzzle is the most self-aware shape in this list. `[B]`

## 12. Computing, maths and science (241–262)

241. **π** — two legs off a bar. Three tips as drawn; fatten the bar. `[B]`
242. **Σ** — zigzag with two bars, two ends. Cheap and reads as "maths". `[A]`
243. **∞** — see #53. `[B]`
244. **∫ integral** — an elongated S with serifs. Two ends, tall, standing finish. `[A]`
245. **√ radical** — a checkmark plus a horizontal bar. Two ends. `[A]`
246. **≠** — an equals pair with a slash; three components without the slash joining them, but the slash *does* join them. Neat trick. `[A]`
247. **Binary "01"** — two digits side by side; the tightest legible pair. `[B]`
248. **Curly braces `{}`** — two components. Fold one brace at demo size, or bridge them into a glyph. `[C]`
249. **Semicolon** — two dots; the developer joke is worth more than the shape. `[C]`
250. **Terminal cursor block** — a filled rectangle. Boring alone; brilliant as the *first* fold that then becomes a letter. `[A]`
251. **Git merge glyph** — two lines converging into one, with node dots. The convergence is a thick junction. `[B]`
252. **Binary tree** — a root with two levels of branches. Branch junctions need thickening; the shape is worth it for a CS audience. `[B]`
253. **Linked list** — boxes joined by arrows. Chain-of-nodes, folded by a chain. On the nose in the best way. `[A]`
254. **Stack frames** — stacked bars with a pointer arrow. Cheap. `[A]`
255. **DNA double helix** — two interleaved sine strands with rungs. The single most impressive shape a chain can make, because the crossings look impossible. `[B]`
256. **Atom** — nucleus plus elliptical orbit rings. Concentric and crossing; ambitious but legible. `[B]`
257. **Benzene ring** — hexagon with an interior circle. Zero tips, perfectly symmetric. `[A]`
258. **Circuit trace** — right-angle traces with pads. This is *literally* a self-avoiding lattice path; it is what the planner produces anyway. `[A]`
259. **Resistor zigzag** — a zigzag between two leads. Two ends. Nearly free. `[A]`
260. **Neural net** — three layers of nodes with edges. Dense; abstract it to a fat three-layer glyph. `[C]`
261. **Rising bar chart** — bars of increasing height sharing a baseline. Trivially connected, and great for a "our numbers went up" beat. `[A]`
262. **Sine wave** — a smooth stair-stepped wave. Two ends, no junctions. One of the very safest shapes here. `[A]`

## 13. Abstract, geometric and art (263–280)

These are the shapes where the *fold* is the content — nobody is admiring the
subject, they are admiring that a chain of cubes did that.

263. **Archimedean spiral** — the chain's most natural shape and still the most impressive. Zero junctions, two ends, folds inward. `[A]`
264. **Yin-yang** — two interlocking teardrops with eye holes. The interlock looks impossible in a single chain. `[B]`
265. **Hilbert curve, order 2** — a space-filling curve folded by a space-filling robot. The most conceptually satisfying shape available. `[A]`
266. **Möbius band** — a flat rendering of a twisted loop. Zero tips. `[B]`
267. **Penrose triangle** — an impossible object in a medium that makes it look real. High effort, high payoff. `[C]`
268. **Celtic knot** — over-under weave. Stunning, and the crossings are the hard part. `[C]`
269. **Maze** — a 7×7 maze with one solution path. The audience will try to solve it, which means they are staring at your robot. `[A]`
270. **Checkerboard patch** — alternating blocks; note this fights the parity rule directly, so it needs care. `[B]`
271. **Dither gradient** — a density ramp from solid to sparse. Abstract but genuinely pretty. `[B]`
272. **Koch snowflake edge** — one fractal iteration as a bumpy line. `[A]`
273. **Sierpinski triangle** — two iterations, with the holes doing the work. Holes help parity. `[B]`
274. **Concentric squares** — nested rings. Zero tips, dead simple, looks deliberate. `[A]`
275. **Op-art zigzag** — dense parallel chevrons that shimmer. `[B]`
276. **Ouroboros** — a ring that eats its own tail; a chain robot forming a closed loop is a statement. `[A]`
277. **Recycle symbol** — three chasing arrows. Three components; a single-loop version with one arrowhead works. `[B]`
278. **Hexagram** — two overlapping triangles. Symmetric with a hole in the middle. `[B]`
279. **Triskele** — three spiral arms from a centre. Three tips; fatten the hub. `[B]`
280. **Impossible staircase** — stepped blocks that loop. Ambitious, and it photographs beautifully. `[C]`

## 14. Stunts, sequences and performance beats (281–300)

The shapes above are *what* you fold. This section is *how you show it*, and
honestly this is where the jaw actually drops. A judge who has watched four
teams show a robot doing one impressive thing will remember the team whose
robot did a thing *they chose*.

281. **Heart → broken heart in one detent** — fold the shipped heart, pause, then one move cracks it. Five seconds, enormous reaction, and it reuses a certified path. `[B]`
282. **H, T, N back to back** — three shipped shapes as one continuous sequence with a title card. Zero new planning; it just needs editing. `[A]`
283. **Audience vote** — a live poll on the projector picks the next shape from a pre-solved set of eight. The crowd feels responsible for the outcome. `[B]`
284. **Voice command** — "CuBot, fold a heart." The shapes are pre-solved; the speech layer is thin. Reads as magic. `[B]`
285. **Sketch to fold** — a judge draws on a tablet, the planner snaps it to the nearest legal 27-cell mask, the robot folds it. This is the single most impressive demo in this document and the hardest. `[C]`
286. **Speedrun** — T is six moves. Put a timer on screen and race it. Fastest-fold is a category nobody else is competing in. `[A]`
287. **Two robots, mating halves** — two chains fold complementary shapes that interlock. Doubles the hardware and quadruples the impact. `[C]`
288. **Standing sculpture** — lean into the fact that T, N and lightning finish vertical. A shape that stands up is a shape that photographs. `[A]`
289. **Shadow puppet** — light the standing shape so its shadow on the wall is the icon. The reveal is the shadow, not the robot. `[C]`
290. **Blind challenge** — a judge names a letter, the planner solves it live on screen, the robot folds it. Terrifying and unforgettable. `[C]`
291. **Scannable QR** — 27 cells will not hold a real QR, but a QR *finder pattern* plus a sign that says "scan the real one" is a good gag. Do not promise a working scan. `[C]`
292. **Countdown** — fold 3, then 2, then 1, then the finale shape. Structure for free. `[B]`
293. **Sponsor logo on demand** — walk the robot to each sponsor booth and fold their mark. Ask first; they will film it and post it. `[B]`
294. **Morph loop** — shape A, unfold to straight, shape B, without a human touching it. Proves it is reversible and autonomous, which is the actual engineering claim. `[B]`
295. **Solver on screen** — project the fold search running live beside the robot. The search *is* the product; let people see it. `[A]`
296. **Sim and hardware in lockstep** — MuJoCo replaying the same path beside the physical fold, in sync. The most credible thing an engineering judge can be shown. `[B]`
297. **Fold around an object** — close the chain around a judge's badge or a pen and hand it back wrapped. Physical, memorable, and they keep the object. `[C]`
298. **Roll away** — fold into a closed loop and let it roll. Locomotion out of a folding robot is a second project's worth of wow. `[C]`
299. **Self-portrait** — fold the CuBot logo, or a 27-cell robot-head glyph. `[A]`
300. **The finale nobody asked for** — end on one shape you never showed in the pitch, revealed silently while you stop talking. Let the room fill the gap. `[A]`

---

## 15. The shortlist

If you only have search time for a handful, spend it here. Ranked by
reaction-per-CPU-hour, not by how cool they are in the abstract.

| rank | shape | # | why this one |
|-----:|-------|---|--------------|
| 1 | **Maple leaf** | 31 | Highest reaction of any shape in this document at this event. **Measured: threaded only at rank 3,004 and came back a blob** — worth the search time, but it needs a much better sketch than the one I drew. |
| 2 | **Pac-Man** | 229 | Universally recognised, and I assumed a disc-minus-wedge would be search-friendly. **It was not: rank 1,954, IoU 0.63, likeness lost.** The wedge is what drift destroys first. Redraw it near-legal before searching. |
| 3 | **Canada goose** | 32 | The local joke. Reaction is out of all proportion to the engineering. |
| 4 | **Broken heart** | 110 | Reuses a *certified* path. The engineering cost is one extra detent and the payoff is the best five seconds of the demo. |
| 5 | **Space invader** | 170 | Pixel art designed for a square grid in the first place, which is exactly what this machine makes. |
| 6 | **Skull** | 99 | The eye and jaw holes both improve legibility and help the parity, so the constraint works *for* you for once. |
| 7 | **Spiral** | 263 | **Promote this to #1.** Threaded at rank 13, the cheapest of anything tested, and the *only* one of fourteen that stayed unambiguously recognisable. Its identity is topological, so the variant search cannot destroy it. If one new shape has to land, it is this one. |
| 8 | **Donut / ring** | 144 | Zero endpoints, folds inward from every side, survives variant drift better than anything else here. The shape to fall back on when a search fails at 4 a.m. |
| 9 | **Cloud** | 51 | **Verified threadable, rank 211.** The most recognisable of the blobby shapes tested, though only marginally — a checked-in fallback, not a headline. |
| 10 | **Cat face** | 112 | Best animal-per-cell ratio, and the best of the animals tested — but only marginally readable at rank 93. Ears are exactly what the search eats; draw them fat or expect to lose them. |
| 11 | **Solver on screen** | 295 | Costs no folding at all. Projecting the search next to the robot converts "neat toy" into "they built a planner", which is what the engineering judges are scoring. |
| 12 | **Sketch to fold** | 285 | The highest ceiling in the document, and now genuinely reachable — the tool in the appendix is most of it. A judge draws, the search snaps and threads, the robot folds. |

Three notes on sequencing the actual demo:

- **Open with a shipped icon, not a new one.** Heart or plus. The first fold
  establishes that it works; the new shape is the payoff, not the opener.
- **The standing finishes are an asset.** T, N and lightning end vertical. A
  shape that stands photographs and films far better than one lying flat, so
  put a standing shape where the camera is.
- **The riskiest thing goes last.** If sketch-to-fold fails live, it fails
  after you have already shown four things that worked.

## Appendix: `tools/sketch_fit.py`

Written alongside this list, because hand-drawing legal masks does not work.

It takes a rough ASCII sketch, runs simulated-annealing walks over cell sets
(keeping exactly 27 cells and face-connectivity as hard invariants, steered by
parity/tip violations and overlap with the sketch), collects every legal mask
the walks pass through, ranks them by IoU against the sketch, and hands them to
the exact shipped-roll solver best-first.

```bash
uv run python tools/sketch_fit.py sketches.txt --out fitted.txt \
    --walks 16 --steps 6000 --tests 4000
```

Input and output are both `=== name` blocks of `.`/`#` rows. Only masks that
thread are written out. Tune `--walks`/`--steps` for how many legal variants to
generate and `--tests` for how many to roll-test; on this machine a walk
produces roughly 300 legal variants in a couple of seconds, and each roll test
costs about 15 ms.

Fourteen sketches were run through it at `--walks 16 --steps 6000
--tests 4000`; all fourteen produced a threadable target, at a cost of roughly
two minutes of CPU each. The two extremes:

```
   spiral sketch      threaded, rank 13, IoU 0.81      <- likeness survived
   #######            #######
   #.....#            #.....#
   #.###.#            #.....#
   #.#...#            #.....#
   #.#####            #.#####
   #......            #.#....
   #######            ######.

   maple sketch       threaded, rank 3004, IoU 0.50    <- likeness destroyed
   ##.#.##            .######
   .##.##.            .#..###
   #######            .#..###
   .#####.            .######
   ..####.            ...#...
   ...##..            #.##...
                      ###....
```

Same tool, same budget. The difference is that the spiral sketch was already
nearly legal and the maple sketch was disconnected with four endpoints, so the
search had to walk 3,000 variants away from it to find anything threadable.

Two things that appendix is *not*:

- It is not a fold. A threadable mask is a goal pose with no move order; run
  `cubot fold` next, and expect table-incursion failures like lightning's.
- It is not a recognition judge. IoU 0.86 kept the cloud; IoU 0.62 turned a
  maple leaf into a blob. Every survivor still needs a human to look at it,
  which is what the blind contact sheet is for.
