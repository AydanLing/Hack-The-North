# Text the robot

Someone texts the CuBot demo number "show hackthenorth some love". The robot folds into a heart and
texts back.

```
iMessage ──► Linq webhook ──► shape-intent model ──► CuBot handoff path ──► executor
   ▲                            (this repo)             (cubot-v2)
   └──────────────── reply ──────────────────────────────────────────────┘
```

This folder holds two things: the seam to Linq's iMessage API and to `cubot-v2/handoff/`'s finalized
fold paths, and the shape-intent model itself — corpus, encoder, head and training, all in this repo.
It is self-contained: clone, train once, run.

## What each piece does

| Piece | Where it lives | What it contributes |
|---|---|---|
| Linq | `linq.py` | inbound webhook parsing, outbound replies, dedupe, rate limit |
| Corpus | `data/utterances.jsonl` | the training set, authored for CuBot's own shape vocabulary |
| Encoder | `model/encoder.py` | frozen sentence-transformer (ONNX, CPU) + numpy TF-IDF |
| Head | `model/head.py` | class-balanced multinomial softmax, fitted in numpy |
| Intent | `intent.py` | utterance → one label, offline, ~2 ms |
| Captions | `captions.py` | who is addressed, and what to say back |
| Vocabulary | `vocab.py` | labels → CuBot shape names, variant collapsing, reachability |
| Fold paths | `robot.py` → `cubot-v2/handoff/` | `path.json` → ordered moves, warnings |
| Orchestration | `bridge.py` | decide, plan, reply |
| Transport | `server.py` | stdlib HTTP, auth, queueing |

The bridge itself is standard library only. The model needs `numpy`, `onnxruntime`, `tokenizers` and
`huggingface_hub` — and only at training time and for the semantic half of the encoder; the TF-IDF
encoder (`--encoder tfidf`) is pure numpy and needs no download at all.

## Setup

```bash
cp imessage/.env.example imessage/.env      # then fill in LINQ_API_KEY and LINQ_WEBHOOK_TOKEN
python3 -m cubot_imessage.model.train       # ~1 minute, CPU only
python3 -m cubot_imessage doctor
```

`doctor` is the pre-demo check. It prints the config, verifies every shipped fold path re-derives its
own goal from its move deltas, loads the intent model, and probes it with the hero utterance.

The Linq key comes from the free Hack the North sandbox (`dashboard.linqapp.com/sandbox-signup`, or
the event portal), which also provisions the phone number people will text.

### Training the model

```bash
python3 -m cubot_imessage.model.train                   # evaluate, then fit and write the head
python3 -m cubot_imessage.model.train --eval-only       # report without writing anything
python3 -m cubot_imessage.model.train --encoder tfidf   # no download, no network
python3 -m cubot_imessage.model.train --model bge-small # a different frozen encoder
```

It reports held-out accuracy over three seeds, accuracy among *accepted* predictions, what fraction
of in-scope requests are accepted, how much chitchat the out-of-scope class catches, the weakest
classes and the most frequent confusions. Thresholds are then chosen on held-out data to hit a
precision target rather than guessed. Only then is the head refitted on everything and saved.

**There is no GPU anywhere in this.** The encoder is frozen — inference only, never fine-tuned — and
all that is fitted is a linear head on top of fixed embeddings. That is a convex problem over a few
thousand rows and it finishes on a laptop CPU in about a minute.

`doctor` warns when the corpus has changed since the head was fitted. Retrain then — not during a
demo.

## Running it

```bash
# no network, no Linq: the whole handler on fabricated messages
python3 -m cubot_imessage simulate "show hackthenorth some love" "do a T" "make a bell"

# the language layer alone, with scores
python3 -m cubot_imessage classify "point at the judges" --top 8

# what a shape actually folds
python3 -m cubot_imessage plan heart

# the vocabulary, and where every label routes
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
2. **Classify.** The hybrid encoder (frozen sentence-transformer + TF-IDF) and the trained head give
   a label, a confidence and a top-two margin. Two independent things make it decline rather than
   guess: an explicit `none` class trained on real chitchat, and the margin/confidence thresholds
   chosen on held-out data. That is why "yo whats good" folds nothing.
3. **Resolve** the label to a CuBot shape. Four outcomes, and the reply distinguishes them:
   - **playable** — a fold path exists. Go.
   - **plannable** — `cubot-v2` has a verified plan but it was never exported to `handoff/`.
     One `tools/export_handoff.py` run away.
   - **rejected** — dropped in review for poor recognizability. Not coming back.
   - **unsure / unmapped** — offers the nearest shape it *can* fold, found by re-ranking the
     classifier's scores over only the playable labels.
4. **Load the path** from `handoff/shapes/<nn>-<name>/path.json` and hand it to the executor.
5. **Reply** into the originating chat with a caption template that names whoever was addressed, so
   "show hack the north some love" comes back as *"Showing Hack the North some love with a heart."*

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

65 tests, none of which touch the network or need a trained head: the classifier is faked for the
bridge tests, the handoff folder is a fixture, and the model tests run on the pure-numpy TF-IDF
encoder. Two of them check the real artifacts when present — every shipped fold path must re-derive
its recorded goal from its move deltas, and every playable concept must resolve to a real directory.
