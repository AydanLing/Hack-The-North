"""The bridge: one inbound iMessage in, one fold plan and one reply out.

    text  --MiniLM-->  label  --vocab-->  handoff shape  --path.json-->  moves  -->  executor
                 \\                                                    /
                  `--OpenAI (only if MiniLM is unsure)---------------'

`Bridge.handle()` is pure decision-making over an `InboundMessage` and is what the tests drive; the
HTTP layer in `server.py` only does transport, auth, dedupe and rate limiting.

The inbound text is treated as data throughout. It is fed to a classifier whose output space is a fixed
label set (MiniLM first; OpenAI only as a fallback that must still pick from that same set), and the
only thing that reaches the robot is a shape name that was already present in `handoff/index.json`
before the message arrived. Text in a message cannot name a file, a command or a number to message:
replies go to the `chat_id` the message came from and nowhere else.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .config import Settings
from .intent import Classifier, IntentResult, IntentUnavailable
from .linq import InboundMessage, LinqClient, LinqError
from .openai_fallback import OpenAIFallback
from .robot import Executor, FoldPlan, ShapeLibrary, build_executor
from .vocab import (STATUS_PLANNABLE, STATUS_PLAYABLE, STATUS_REJECTED, STATUS_UNMAPPED,
                    STATUS_UNSURE, CUBOT_ALIASES, Resolution, Vocabulary)

THINKING_EMOJI = "🤔"

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
    via: str = "minilm"          # "minilm" | "openai" | "help"

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        return self.resolution.status if self.resolution else "help"

    def log_line(self) -> str:
        who = self.inbound.sender
        bits = [f"{who} {self.inbound.text!r} -> {self.status}"]
        if self.via and self.via != "minilm":
            bits.append(f"via={self.via}")
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
                 openai: Optional[OpenAIFallback] = None, log=print):
        self.settings = settings
        self.log = log
        self.classifier = classifier or Classifier.from_settings(settings)
        self.vocab = vocabulary or Vocabulary(settings.handoff_dir)
        self.library = library or ShapeLibrary(settings.handoff_dir)
        self.executor = executor or build_executor(settings.executor, log=log)
        self.client = client
        self._playable_labels: Optional[dict[str, str]] = None
        self.react_on_receive = bool(getattr(settings, "react_on_receive", True))
        if openai is not None:
            self.openai = openai
        elif getattr(settings, "openai_fallback", True):
            self.openai = OpenAIFallback(
                api_key=getattr(settings, "openai_api_key", ""),
                model=getattr(settings, "openai_model", "gpt-4o-mini"),
                timeout_s=min(12.0, float(getattr(settings, "timeout_s", 15.0) or 15.0)),
                log=log,
            )
        else:
            self.openai = OpenAIFallback(api_key="", log=log)

    def warmup(self) -> "Bridge":
        self.classifier.warmup()
        _ = self.playable_labels                  # precompute the label -> shape routing
        return self

    def react(self, inbound: InboundMessage, *, ok: bool) -> None:
        """Tapback after classify/resolve: 👍 when we can fold, 🤔 when we cannot decipher."""
        if not (self.react_on_receive and self.client and inbound.message_id):
            return
        try:
            if ok:
                self.client.react(inbound.message_id, "like")
                self.log(f"[react] like on {inbound.message_id}")
            else:
                self.client.react(inbound.message_id, "custom", custom_emoji=THINKING_EMOJI)
                self.log(f"[react] {THINKING_EMOJI} on {inbound.message_id}")
        except LinqError as e:
            self.log(f"[warn] react failed: {e}")

    @property
    def playable_labels(self) -> dict[str, str]:
        if self._playable_labels is None:
            try:
                known = self.classifier.labels
            except Exception:
                known = None
            base = self.vocab.playable_labels(known)
            # Handoff concepts MiniLM has never seen (e.g. volumetric paperclip/hammer) must still
            # be choosable by the OpenAI fallback — expose them as underscore labels.
            for concept in self.vocab.playable_concepts:
                shape = self.vocab.shape_for_icon(concept)
                if not shape:
                    continue
                for lab in {concept, concept.replace("-", "_")}:
                    base.setdefault(lab, shape)
            # Expose aliases (cube/block → cube-frame) so OpenAI can name them directly.
            for alias, canonical in CUBOT_ALIASES.items():
                shape = self.vocab.shape_for_icon(canonical)
                if not shape:
                    continue
                for lab in {alias, alias.replace("-", "_")}:
                    base.setdefault(lab, shape)
            self._playable_labels = base
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

    def _model_pretty(self, via: str) -> str:
        if via == "openai":
            model = (getattr(self.settings, "openai_model", "") or "gpt-4o-mini").strip()
            return ("ChatGPT " + model[4:]) if model.startswith("gpt-") else model
        return "local MiniLM"

    def _deciphered_note(self, via: str) -> str:
        """Attribution line so the booth demo shows which brain picked the shape."""
        return f"(deciphered with {self._model_pretty(via)})" if via == "openai" \
            else "(deciphered using local MiniLM)"

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
            body = (f"{heard}\nClosest I can fold is {res.nearest_playable} — want that? "
                    f"Otherwise: {self.shape_list()}.")
        else:
            body = f"{heard}\nI can fold: {self.shape_list()}."
        tried = self._model_pretty("minilm")
        if self.openai.enabled:
            tried += f" and {self._model_pretty('openai')}"
        return f"{body}\n(could not decipher with {tried})"

    def _accept(self, res: Resolution, intent: IntentResult, plan: FoldPlan,
                via: str = "minilm") -> str:
        caption = (intent.caption or "").strip().rstrip(".")
        if not caption:
            # Last resort only — prefer a human concept name over the raw dir id when we can.
            nice = (res.icon or plan.shape or "that shape").replace("_", " ").replace("-", " ")
            caption = f"Folding {nice}"
        line = (f"{caption}. {len(plan.moves)} moves, about {plan.total_time_s:.0f}s.\n"
                f"{self._deciphered_note(via)}")
        if plan.warnings:
            line += "\nHeads up: " + "; ".join(plan.warnings) + "."
        return line

    def _try_openai(self, text: str, out: Outcome) -> Optional[tuple[IntentResult, Resolution]]:
        """Second opinion when MiniLM declined. Always tries to land on a playable shape."""
        allowed = list(self.playable_labels.keys()) or list(getattr(self.classifier, "labels", []) or [])
        # Even without an API key, letter-fallback must still fire so the booth never blanks.
        from .openai_fallback import first_letter_fallback
        guess = self.openai.resolve(text, allowed) if self.openai.enabled \
            else first_letter_fallback(text, allowed)
        if guess is None:
            return None
        self.log(f"[openai] {text!r} -> {guess.label} ({guess.confidence:.2f}, "
                 f"{getattr(guess, 'via', 'openai')}, {guess.latency_ms:.0f}ms)")
        if guess.label == "none":
            guess = first_letter_fallback(text, allowed)
            if guess is None:
                return None
            self.log(f"[openai] forced letter fallback -> {guess.label}")
        intent = IntentResult(
            text=text, label=guess.label, confidence=guess.confidence, margin=guess.confidence,
            accepted=True, caption=guess.caption or "", who=None, latency_ms=guess.latency_ms,
            ranked=[(guess.label, guess.confidence)],
        )
        res = self.vocab.resolve(intent.label, accepted=True, nearest=None,
                                 nearest_label_map=self.playable_labels)
        if not res.ok:
            # Last ditch: walk playable labels until one resolves.
            for label in allowed:
                res2 = self.vocab.resolve(label, accepted=True, nearest=None,
                                          nearest_label_map=self.playable_labels)
                if res2.ok:
                    intent = IntentResult(
                        text=text, label=label, confidence=0.2, margin=0.2, accepted=True,
                        caption=f"Going with {label.replace('_', ' ')}", who=None,
                        ranked=[(label, 0.2)],
                    )
                    res = res2
                    break
            else:
                return None
        out.via = "openai" if getattr(guess, "via", "openai") == "openai" else "openai"
        out.intent = intent
        out.resolution = res
        return intent, res

    def _finish_plan(self, out: Outcome, inbound: InboundMessage, text: str,
                     intent: IntentResult, res: Resolution, execute: bool, t0: float) -> Outcome:
        try:
            plan = self.library.plan(res.shape)
        except (KeyError, OSError, ValueError) as e:
            out.error = f"cannot load the fold path for {res.shape}: {e}"
            out.reply = f"I know that one ({res.shape}) but its fold path won't load. Tell my operator."
            self.react(inbound, ok=False)
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out
        out.plan = plan
        out.reply = self._accept(res, intent, plan, via=out.via)
        self.react(inbound, ok=True)

        if execute:
            try:
                out.executed = self.executor.submit(plan, {
                    "sender": inbound.sender, "chat_id": inbound.chat_id, "text": text,
                    "label": intent.label, "confidence": round(intent.confidence, 4),
                    "margin": round(intent.margin, 4), "who": intent.who,
                    "via": out.via,
                })
            except Exception as e:
                out.error = f"executor {self.executor.name} refused the plan: {e}"
                out.reply = f"I worked out the {plan.shape} fold but couldn't start it. Tell my operator."
            else:
                # Hardware executor may still run MuJoCo with the bus unplugged —
                # keep the accept reply, but tell the sender the robot is offline.
                executed = out.executed or {}
                if executed.get("hardware_offline") or executed.get("sim_only"):
                    out.error = executed.get("error") or "robot offline"
                    out.reply = (
                        out.reply.rstrip()
                        + "\n(The physical robot isn't plugged in right now — "
                          "playing the fold in simulation instead.)"
                    )
        out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return out

    # -- the handler -------------------------------------------------------------------------
    def handle(self, inbound: InboundMessage, execute: bool = True) -> Outcome:
        """Classify, resolve, plan and (optionally) execute. Never raises; failures land in
        `Outcome.error` so the webhook can still 200 and the sender still gets a reply."""
        t0 = time.perf_counter()
        out = Outcome(inbound=inbound)
        text = inbound.text.strip()

        if text.lower().strip("!?. ") in HELP_WORDS:
            out.via = "help"
            out.reply = self.help_reply()
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out

        try:
            intent = self.classifier.classify(text)
        except IntentUnavailable as e:
            recovered = self._try_openai(text, out)
            if recovered:
                intent, res = recovered
                return self._finish_plan(out, inbound, text, intent, res, execute, t0)
            out.error = str(e)
            out.reply = ("My shape model isn't loaded, so I can't read that right now. "
                         f"I can still fold: {self.shape_list()}.")
            self.react(inbound, ok=False)
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
            # Always invent a fold for "I have no idea" — never blank the booth.
            # Plannable/rejected keep their honest decline (we know the shape, we just can't fold it).
            if res.status in (STATUS_UNSURE, STATUS_UNMAPPED):
                recovered = self._try_openai(text, out)
                if recovered:
                    intent, res = recovered
                    return self._finish_plan(out, inbound, text, intent, res, execute, t0)
            out.reply = self._decline(res, intent)
            self.react(inbound, ok=False)
            out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return out

        return self._finish_plan(out, inbound, text, intent, res, execute, t0)

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
