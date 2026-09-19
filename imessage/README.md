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
| Weights | `model/vendor.py` → `data/encoder/` | the encoder, quantized and committed, so no download |
| Head | `model/head.py` | class-balanced multinomial softmax, fitted in numpy |
| Intent | `intent.py` | utterance → one label, offline, ~2 ms |
| Captions | `captions.py` | who is addressed, and what to say back |
| Vocabulary | `vocab.py` | labels → CuBot shape names, variant collapsing, reachability |
| Fold paths | `robot.py` → `cubot-v2/handoff/` | `path.json` → ordered moves, warnings |
| Orchestration | `bridge.py` | decide, plan, reply |
| Transport | `server.py` | stdlib HTTP, auth, queueing |

The bridge itself is standard library only. The model needs `numpy` and `onnxruntime`; `tokenizers`
and `huggingface_hub` are only needed to *re-vendor* the encoder, not to run it.

## Setup

```bash
cp imessage/.env.example imessage/.env      # then fill in LINQ_API_KEY (+ LINQ_WEBHOOK_SECRET later)
pip install numpy onnxruntime
python3 -m cubot_imessage doctor
```

That is the whole setup: **both halves of the model are committed**, so there is nothing to download
and nothing to train. `data/encoder/minilm/` holds the frozen encoder and `data/intent_head.npz` the
head that was fitted on it.

## The model is in the repo, both halves

A frozen sentence encoder plus a linear head is two artifacts, and shipping only one of them is what
makes a "works on my laptop" demo. Both are committed:

| | Path | Size | What it is |
|---|---|---|---|
| Encoder | `data/encoder/minilm/model.onnx` | 23 MB | all-MiniLM-L6-v2, dynamically quantized to int8 |
| Tokenizer | `data/encoder/minilm/tokenizer.json` | 0.5 MB | its WordPiece vocabulary |
| Head | `data/intent_head.npz` | 4.7 MB | 68-class softmax + the fitted TF-IDF vocabulary |

Quantization is what makes this practical: the float weights are 90 MB, which GitHub warns about and
every clone pays for. Int8 is 23 MB. Re-vendor with:

```bash
python3 -m cubot_imessage.model.vendor          # fetch, quantize to int8, checksum
python3 -m cubot_imessage.model.vendor --check   # what is vendored, offline
python3 -m cubot_imessage.model.vendor --drift   # int8 vs float embedding similarity
python3 -m cubot_imessage.model.vendor --fp32    # don't quantize, if you have a reason
```

**Int8 costs nothing measurable here, but not for the reason you might assume.** Quantization moves
the embeddings a long way in absolute terms — mean cosine against the float weights is 0.958, not
0.999. It does not matter, because the head is a *linear* rule fitted on whatever space the encoder
produces, and it is refitted on the quantized embeddings. The drift is largely a consistent
transformation, and a linear model absorbs it:

| | float32 (90 MB) | **int8 (23 MB)** |
|---|---|---|
| Top-1 accuracy | 0.934 ± 0.004 | **0.934 ± 0.006** |
| Accuracy among accepted | 0.984 | 0.983 |
| Coverage | 84.5% | 84.2% |
| Chitchat declined | 97.4% | **98.7%** |

The corollary is the trap: **fit the head on the same weights that will serve it.** A head trained on
float embeddings and served by int8 ones is quietly mis-calibrated. `train.py` uses the vendored
weights whenever they exist, so the order is vendor first, then train, and the encoder's name in the
saved head records which it used (`hybrid:minilm@vendored:int8`) so `doctor` can show you.

`doctor` is the pre-demo check. It prints the config, verifies every shipped fold path re-derives its
own goal from its move deltas, loads the intent model, and probes it with the hero utterance.

The Linq key comes from the free Hack the North sandbox (`dashboard.linqapp.com/sandbox-signup`, or
the event portal), which also provisions the phone number people will text.

### Retraining the model

Only needed if you change the corpus. About two minutes on a laptop CPU.

```bash
python3 -m cubot_imessage.model.train                   # evaluate, then fit and write the head
python3 -m cubot_imessage.model.train --eval-only       # report without writing anything
python3 -m cubot_imessage.model.train --encoder tfidf   # pure numpy, no encoder at all
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

It also pins `?version=2026-02-03`, which selects the inbound payload layout. This matters: Linq
date-versions webhook payloads and a subscription created before that date gets a
[different field layout](https://docs.linqapp.com/guides/webhooks/events/) — the text at
`data.message.parts[]` instead of `data.parts[]`, the sender at `data.from` instead of
`data.sender_handle.handle`. `parse_inbound` reads both, so an older subscription still works, but
pinning means the shape does not depend on the day you registered.

Copy the `signing_secret` from the response into `LINQ_WEBHOOK_SECRET` right away — it is shown once.

### Two sandbox limits that shape the demo

- **A recipient must text you first.** Sending to someone who has not messaged you fails with
  `403` / [`2008`](https://docs.linqapp.com/error/codes/2xxx/2008/). The bridge only ever replies into
  the `chat_id` a message arrived on, so this is satisfied by construction — but it does mean you
  cannot pre-seed a conversation with a judge's phone.
- **100 messages/day**, resetting midnight UTC, plus 30 per 60 seconds per sender-recipient pair.
  That is the real budget for a demo day, so `BRIDGE_RATE_LIMIT_PER_MINUTE` and the `event_id` dedupe
  are protecting a quota, not just the robot.

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

Webhook deliveries are authenticated two ways, strongest first:

1. **HMAC signature** (`LINQ_WEBHOOK_SECRET`). Linq signs every delivery per the
   [Standard Webhooks](https://docs.linqapp.com/guides/webhooks/) spec — HMAC-SHA256 over
   `{webhook-id}.{webhook-timestamp}.{body}`, base64 in a `webhook-signature: v1,...` header. The
   bridge verifies it against the **raw** bytes before parsing them, rejects timestamps more than five
   minutes old, and accepts any one of several space-separated signatures so a secret rotation does not
   drop messages. `subscribe` prints the `signing_secret` in a banner because Linq returns it exactly
   once — miss it and you have to delete and recreate the subscription.
2. **Shared-secret URL token** (`LINQ_WEBHOOK_TOKEN`), compared in constant time. The fallback for
   before you have a signing secret. A URL-borne secret is only as private as the channel, so
   terminate TLS in front of it.

Either passing is enough, but a signature that is *present and wrong* is fatal no matter what the
token says — otherwise anyone who learned the URL could put words in a sender's mouth. And once a
secret is configured, an unsigned delivery is refused, so the weaker check cannot be selected by
simply omitting the header.

## Tests

```bash
python3 -m pytest imessage/tests -q
```

86 tests, none of which touch the network or need a trained head: the classifier is faked for the
bridge tests, the handoff folder is a fixture, and the model tests run on the pure-numpy TF-IDF
encoder. `test_server.py` stands the webhook endpoint up on an ephemeral port to check the
authentication gate end to end, because the mistake worth catching there is not in any one function
but in the ordering — verifying a re-serialised body, or letting a valid token wave a forged one
through. Two tests check the real artifacts when present: every shipped fold path must re-derive its
recorded goal from its move deltas, and every playable concept must resolve to a real directory.
