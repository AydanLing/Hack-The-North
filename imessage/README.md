# Text the robot

Someone texts the CuBot demo number "show hackthenorth some love". The robot folds into a heart and
texts back.

```
iMessage ──► Linq webhook ──► MiniLM intent head ──► CuBot handoff path ──► executor
   ▲                            (snake_pipeline)        (cubot-v2)
   └──────────────── reply ───────────────────────────────────────────────┘
```

This folder is the seam between three things that already existed: Linq's iMessage API, the sentence
classifier in `snake_pipeline`, and the finalized fold paths in `cubot-v2/handoff/`. It adds no model
and no planner of its own.

## What each piece does

| Piece | Where it lives | What it contributes |
|---|---|---|
| Linq | `linq.py` | inbound webhook parsing, outbound replies, dedupe, rate limit |
| Intent | `intent.py` → `snake_pipeline/snakeshape/local_model.py` | utterance → one of 139 labels, offline, ~2 ms |
| Vocabulary | `vocab.py` | 139 labels → CuBot shape names, variant collapsing, reachability |
| Fold paths | `robot.py` → `cubot-v2/handoff/` | `path.json` → ordered moves, warnings |
| Orchestration | `bridge.py` | decide, plan, reply |
| Transport | `server.py` | stdlib HTTP, auth, queueing |

No dependencies outside the standard library. The classifier's numpy/onnxruntime come from the
`snake_pipeline` checkout it borrows.

## Setup

```bash
cp imessage/.env.example imessage/.env      # then fill in LINQ_API_KEY and LINQ_WEBHOOK_TOKEN
python3 -m cubot_imessage doctor
```

`doctor` is the pre-demo check. It prints the config, verifies every shipped fold path re-derives its
own goal from its move deltas, loads the intent model, and probes it with the hero utterance.

The Linq key comes from the free Hack the North sandbox (`dashboard.linqapp.com/sandbox-signup`, or
the event portal), which also provisions the phone number people will text.

### Pointing at the two repos

Both are found automatically when the layout is the usual one; override if not:

```bash
export CUBOT_HANDOFF_DIR=/path/to/Hack-The-North/cubot-v2/handoff
export SNAKE_PIPELINE_DIR=/path/to/snake_pipeline
```

`snake_pipeline` must already have a trained head at `data/intent_head.npz`. If it does not, run
`python3 train_intent.py --no-llm` there first — about 90 seconds on CPU. Do not let it retrain
during the demo.

## Running it

```bash
# no network, no Linq: the whole handler on fabricated messages
python3 -m cubot_imessage simulate "show hackthenorth some love" "do a T" "make a bell"

# the language layer alone, with scores
python3 -m cubot_imessage classify "point at the judges" --top 8

# what a shape actually folds
python3 -m cubot_imessage plan heart

# the vocabulary, and where all 139 labels route
python3 -m cubot_imessage vocab --labels

# serve
python3 -m cubot_imessage serve --spool out/queue.jsonl
```

Then expose the port and register the webhook. `subscribe` appends your `LINQ_WEBHOOK_TOKEN` to the
URL, and prints the request without sending it unless you pass `--send`:

```bash
python3 -m cubot_imessage subscribe --url https://<your-tunnel>/linq/webhook
python3 -m cubot_imessage subscribe --url https://<your-tunnel>/linq/webhook --send
```

## What it does with a message

1. **Help words** (`help`, `shapes`, `what can you do`) short-circuit to the shape list.
2. **Classify.** The hybrid encoder (frozen MiniLM ONNX + TF-IDF) and the trained head give a label,
   a confidence and a top-two margin. Below `margin 0.15 / confidence 0.3` the head declines rather
   than guessing — which is why "yo whats good" does not fold anything.
3. **Resolve** the label to a CuBot shape. Four outcomes, and the reply distinguishes them:
   - **playable** — a fold path exists. Go.
   - **plannable** — `cubot-v2` has a verified plan but it was never exported to `handoff/`.
     One `tools/export_handoff.py` run away.
   - **rejected** — dropped in review for poor recognizability. Not coming back.
   - **unsure / unmapped** — offers the nearest shape it *can* fold, found by re-ranking the
     classifier's scores over only the playable labels.
4. **Load the path** from `handoff/shapes/<nn>-<name>/path.json` and hand it to the executor.
5. **Reply** into the originating chat, using `snake_pipeline`'s caption template — which fills in the
   greeted entity, so "show hack the north some love" comes back as *"Showing Hack the North some love
   with a heart."*

Warnings from the handoff travel all the way to the text. Ask for lightning and the reply says it has
six table-incursion violations and is expected to fail physically, because `index.json` says so.

## Shape variants

A handoff directory is one *mask*, not one concept. In the 84-shape export, dirs 50–84 carry a `-vNN`
suffix, so `spiral`, `spiral-v01` and `spiral-v02` are three drawings of one idea — about 67 concepts
across 84 directories. A text says "spiral"; `vocab.py` groups the masks and picks one, preferring in
order: passes its hard checks → finishes flat rather than on edge → fewer moves → lower demo number.
That last tiebreak keeps the reviewed demo seven winning their own concepts.

The playable set is read from `index.json` at startup. Exporting more shapes changes what the robot
answers to without touching this code.

## Executors

The bridge decides *what* to fold; it does not drive servos.

- `dryrun` (default) — logs the plan. What you want on a laptop.
- `spool` — appends one JSON line per request to a queue file for the sim or hardware owner to
  consume. This is the boundary `handoff/README.md` asks for: it wants back `formed`, drift, peak
  torque and the face it landed on.
- `none` — accept and discard, for load-testing the language path.

Implement `submit(plan, context)` to add a real one.

## Security

The inbound text is data, never instructions. It reaches a classifier whose output space is a fixed
label set, and the only value that escapes into the robot is a shape name that was already in
`index.json` before the message arrived. A message cannot name a file, a command, or a number to
text — replies go to the `chat_id` the message came from and nowhere else.

On top of that: a shared-secret token on the webhook URL compared in constant time, an optional
sender allowlist (`LINQ_ALLOWED_SENDERS`), a per-sender rate limit, `event_id` dedupe so a webhook
retry cannot fold twice, a 256 KB body cap, and control-character stripping on every inbound string.

One caveat worth knowing: Linq's public docs specify the subscription `target_url` but no request
signing scheme, so the URL token is the floor, not the ceiling. Terminate TLS in front of this and
treat the token as a credential. If Linq documents an HMAC header, verify that instead.

## Tests

```bash
python3 -m pytest imessage/tests -q
```

28 tests, no network and no `snake_pipeline` needed — the classifier is faked and the handoff folder
is a fixture. The last test additionally verifies the *real* `cubot-v2/handoff/` when present: every
shipped path must re-derive its recorded goal from its move deltas.
