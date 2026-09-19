"""The bridge: one inbound iMessage in, one fold plan and one reply out.

    text  --MiniLM-->  label  --vocab-->  handoff shape  --path.json-->  moves  -->  executor
                                                                              \
                                                                               -->  iMessage reply

`Bridge.handle()` is pure decision-making over an `InboundMessage` and is what the tests drive; the
HTTP layer in `server.py` only does transport, auth, dedupe and rate limiting.

The inbound text is treated as data throughout. It is fed to a classifier whose output space is a fixed
label set, and the only thing that reaches the robot is a shape name that was already present in
`handoff/index.json` before the message arrived. Text in a message cannot name a file, a command or a
number to message: replies go to the `chat_id` the message came from and nowhere else.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .config import Settings
from .intent import Classifier, IntentResult, IntentUnavailable
from .linq import InboundMessage, LinqClient, LinqError
from .robot import Executor, FoldPlan, ShapeLibrary, build_executor
from .vocab import (STATUS_PLANNABLE, STATUS_PLAYABLE, STATUS_REJECTED, STATUS_UNMAPPED,
                    STATUS_UNSURE, Resolution, Vocabulary)

HELP_WORDS = {"help", "?", "shapes", "shape list", "what can you do", "what can you make",
              "what shapes", "commands", "menu", "list", "options"}


@dataclass
class Outcome:
    """The full record of handling one message — logged, returned by the CLI, asserted in tests."""

    inbound: InboundMessage
    reply: str = ""
    intent: Optional[IntentResult] = None
    resolution: Optional[Resolution] = None
    plan: Optional[FoldPlan] = None
    executed: Optional[dict] = None
    replied: bool = False
    error: str = ""
    elapsed_ms: float = 0.0

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        return self.resolution.status if self.resolution else "help"

    def log_line(self) -> str:
        who = self.inbound.sender
        bits = [f"{who} {self.inbound.text!r} -> {self.status}"]
        if self.intent:
            bits.append(f"label={self.intent.label} conf={self.intent.confidence:.2f} "
                        f"margin={self.intent.margin:.2f}")
        if self.plan:
            bits.append(f"plan={self.plan.shape}/{len(self.plan.moves)}moves")
        if self.error:
            bits.append(f"error={self.error}")
        bits.append(f"{self.elapsed_ms:.0f}ms")
        return " | ".join(bits)


class Bridge:
    """Wires the classifier, the vocabulary, the handoff library and an executor together."""

    def __init__(self, settings: Settings, classifier: Optional[Classifier] = None,
                 vocabulary: Optional[Vocabulary] = None, library: Optional[ShapeLibrary] = None,
                 executor: Optional[Executor] = None, client: Optional[LinqClient] = None,
                 log=print):
        self.settings = settings
        self.log = log
        self.classifier = classifier or Classifier.from_settings(settings)
        self.vocab = vocabulary or Vocabulary(settings.handoff_dir)
        self.library = library or ShapeLibrary(settings.handoff_dir)
        self.executor = executor or build_executor(settings.executor, log=log)
        self.client = client
        self._playable_labels: Optional[dict[str, str]] = None

    def warmup(self) -> "Bridge":
        self.classifier.warmup()
        _ = self.playable_labels                  # precompute the label -> shape routing
        return self

    @property
    def playable_labels(self) -> dict[str, str]:
        if self._playable_labels is None:
            try:
                known = self.classifier.labels
            except Exception:
                known = None
            self._playable_labels = self.vocab.playable_labels(known)
        return self._playable_labels

    # -- replies -----------------------------------------------------------------------------
    def shape_list(self, limit: int = 14) -> str:
        """Concepts the robot can fold. Capped, because an 84-shape export does not fit in a text."""
        names = self.vocab.playable_concepts
        if len(names) <= limit:
            return ", ".join(names)
        return ", ".join(names[:limit]) + f" and {len(names) - limit} more"

    def help_reply(self) -> str:
        return (f"I'm CuBot — 27 cubes on a chain. Text me a shape and I'll fold into it.\n"
                f"I know {len(self.vocab.playable_concepts)} shapes: {self.shape_list()}.\n"
                f"Plain English works: \"show Hack the North some love\", \"point at the judges\".")

    def _decline(self, res: Resolution, intent: IntentResult) -> str:
        """Reply for a request that is not playable. Says what it understood, why it cannot, and
        offers the nearest thing it can actually fold."""
        heard = {
            STATUS_PLANNABLE: f"I read that as {res.icon} — I have a verified plan for it, but no fold "
                              f"path exported yet.",
            STATUS_REJECTED: f"I read that as {res.icon}, which we dropped in review because it didn't "
                             f"read clearly as a shape.",
            STATUS_UNMAPPED: f"I read that as {intent.label}, which isn't one of my shapes.",
            STATUS_UNSURE: "I couldn't tell which shape you meant.",
        }.get(res.status, "I can't fold that one.")
        if res.nearest_playable and res.nearest_score >= 0.35:
            return f"{heard}\nClosest I can fold is {res.nearest_playable} — want that? " \
                   f"Otherwise: {self.shape_list()}."
        return f"{heard}\nI can fold: {self.shape_list()}."

    def _accept(self, res: Resolution, intent: IntentResult, plan: FoldPlan) -> str:
        caption = intent.caption or f"Folding into {plan.shape}"
        line = f"{caption}. {len(plan.moves)} moves, about {plan.total_time_s:.0f}s."
        if plan.warnings:
            line += "\nHeads up: " + "; ".join(plan.warnings) + "."
        return line

    # -- the handler -------------------------------------------------------------------------
    def handle(self, inbound: InboundMessage, execute: bool = True) -> Outcome:
        """Classify, resolve, plan and (optionally) execute. Never raises; failures land in
        `Outcome.error` so the webhook can still 200 and the sender still gets a reply."""
        t0 = time.perf_counter()
        out = Outcome(inbound=inbound)
        text = inbound.text.strip()

        if text.lower().strip("!?. ") in HELP_WORDS:
            out.reply = self.help_reply()
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out

        try:
            intent = self.classifier.classify(text)
        except IntentUnavailable as e:
            out.error = str(e)
            out.reply = ("My shape model isn't loaded, so I can't read that right now. "
                         f"I can still fold: {self.shape_list()}.")
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out
        out.intent = intent

        nearest = None
        try:
            nearest = self.classifier.restricted_best(text, list(self.playable_labels))
        except Exception:                      # a suggestion is a nicety, never a reason to fail
            nearest = None
        res = self.vocab.resolve(intent.label, accepted=intent.accepted, nearest=nearest,
                                 nearest_label_map=self.playable_labels)
        out.resolution = res

        if not res.ok:
            out.reply = self._decline(res, intent)
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out

        try:
            plan = self.library.plan(res.shape)
        except (KeyError, OSError, ValueError) as e:
            out.error = f"cannot load the fold path for {res.shape}: {e}"
            out.reply = f"I know that one ({res.shape}) but its fold path won't load. Tell my operator."
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out
        out.plan = plan
        out.reply = self._accept(res, intent, plan)

        if execute:
            try:
                out.executed = self.executor.submit(plan, {
                    "sender": inbound.sender, "chat_id": inbound.chat_id, "text": text,
                    "label": intent.label, "confidence": round(intent.confidence, 4),
                    "margin": round(intent.margin, 4), "who": intent.who,
                })
            except Exception as e:
                out.error = f"executor {self.executor.name} refused the plan: {e}"
                out.reply = f"I worked out the {plan.shape} fold but couldn't start it. Tell my operator."
        out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return out

    # -- sending -----------------------------------------------------------------------------
    def send_reply(self, out: Outcome) -> Outcome:
        """Send `out.reply` back into the chat the message came from. No-op without a client or when
        auto-reply is off."""
        if not (self.settings.auto_reply and self.client and out.reply):
            return out
        try:
            self.client.reply(out.inbound.chat_id, out.reply)
            out.replied = True
        except LinqError as e:
            out.error = (out.error + "; " if out.error else "") + f"reply failed: {e}"
        return out
