"""Bridge tests. Everything here runs without a network and without a trained head: the classifier is
faked, and the handoff folder is a small fixture (plus the real one when it is present)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubot_imessage.bridge import Bridge                                    # noqa: E402
from cubot_imessage.config import Settings                                  # noqa: E402
from cubot_imessage.intent import IntentResult                              # noqa: E402
from cubot_imessage.linq import (WEBHOOK_VERSION, InboundMessage, LinqClient,   # noqa: E402
                                 RateLimiter, SeenEvents, parse_inbound,
                                 pin_version, text_of, verify_signature)
from cubot_imessage.openai_fallback import OpenAIFallback                   # noqa: E402
from cubot_imessage.robot import (DryRunExecutor, ShapeLibrary,             # noqa: E402
                                  states_match_goal)
from cubot_imessage.vocab import (STATUS_PLANNABLE, STATUS_PLAYABLE,        # noqa: E402
                                  STATUS_UNSURE, Vocabulary, icon_key,
                                  label_to_icon, strip_variant)

REAL_HANDOFF = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "cubot-v2", "handoff")


# ------------------------------------------------------------------------------- fixtures

def _path_doc(name: str, number: int, moves: list[tuple[int, int, str]], flat: bool = True,
              ok: bool = True) -> dict:
    return {
        "schema": "cubot.handoff.v1", "name": name, "demo_number": number,
        "status": {"complete": True, "loose_hard_ok": ok,
                   "loose_violations": [] if ok else ["ground", "ground"]},
        "summary": {"moves": len(moves), "total_time_s": 2.0 * len(moves),
                    "ends_flat_on_table": flat, "peak_demand_nm": 7.5},
        "goal": {"silhouette": ["##", "##"]},
        "start": {"base": 0}, "final_tracked": {"base": 3},
        "snake_pipeline": {},
        "moves": [{"step": i + 1, "joint": j, "delta": d, "side": s, "duration_s": 2.0,
                   "moving_side_snake_pipeline": "parent" if s == "in" else "child",
                   "state_after": d, "hard_ok": True,
                   "checks": {"measurements": {"peak_demand_nm": 1.0}}}
                  for i, (j, d, s) in enumerate(moves)],
    }


@pytest.fixture
def handoff(tmp_path):
    """A miniature handoff folder with a variant pair, to exercise concept grouping."""
    shapes = [
        ("heart", 1, [(1, -1, "in"), (6, 1, "in")], True, True),
        ("t", 6, [(3, 1, "out")], False, True),
        ("j", 12, [(2, 1, "out")], True, True),
        ("u", 18, [(4, -1, "in")], True, True),
        ("spiral", 32, [(2, 1, "out"), (4, -1, "out"), (7, 1, "in")], True, True),
        ("spiral-v01", 55, [(2, 1, "out")], False, True),     # fewer moves but finishes standing
        ("spiral-v02", 56, [(5, 1, "out")], True, False),     # flat but fails its hard checks
    ]
    index = {"schema": "cubot.handoff.index.v1", "roll": "1200130013310123033323321 0".replace(" ", ""),
             "pitch_mm": 82.0, "shapes": []}
    for name, number, moves, flat, ok in shapes:
        d = tmp_path / "shapes" / f"{number:02d}-{name}"
        d.mkdir(parents=True)
        (d / "path.json").write_text(json.dumps(_path_doc(name, number, moves, flat, ok)))
        index["shapes"].append({"number": number, "name": name, "dir": f"shapes/{number:02d}-{name}",
                                "moves": len(moves), "complete": True, "loose_hard_ok": ok,
                                "ends_flat_on_table": flat, "aliases": []})
    (tmp_path / "index.json").write_text(json.dumps(index))
    return str(tmp_path)


class FakeClassifier:
    """Returns a scripted label, so bridge behaviour is tested without the model."""

    def __init__(self, label="heart", confidence=0.8, margin=0.4, accepted=True):
        self.label, self.confidence, self.margin, self.accepted = label, confidence, margin, accepted
        self.labels = ["heart", "letter_t", "letter_j", "letter_u", "spiral", "star", "bell", "digit_0"]
        self.encoder_name = "fake"
        self.load_seconds = 0.0

    def warmup(self):
        return self

    def classify(self, text, top_k=5):
        return IntentResult(text=text, label=self.label, confidence=self.confidence,
                            margin=self.margin, accepted=self.accepted,
                            caption=f"Making a {self.label}", who=None,
                            ranked=[(self.label, self.confidence)])

    def restricted_best(self, text, allowed):
        return (allowed[0], 0.5) if allowed else None


def _settings(handoff_dir: str) -> Settings:
    return Settings(handoff_dir=handoff_dir, auto_reply=False, executor="dryrun")


def _bridge(handoff_dir: str, classifier=None) -> Bridge:
    return Bridge(_settings(handoff_dir), classifier=classifier or FakeClassifier(),
                  executor=DryRunExecutor(log=lambda *a: None), log=lambda *a: None)


def _inbound(text: str, sender="+15555550123") -> InboundMessage:
    return InboundMessage(event_id="e1", message_id="m1", chat_id="c1", sender=sender, text=text)


# ------------------------------------------------------------------------------- vocab

def test_strip_variant_and_icon_key():
    assert strip_variant("check-v01") == "check"
    assert strip_variant("spiral-v12") == "spiral"
    assert strip_variant("heart") == "heart"
    assert icon_key("check-v01") == "checkmark"      # alias applied after the suffix
    assert icon_key("digit-3") == "d3"
    assert icon_key("7") == "d7"


def test_label_to_icon_mechanical_and_aliased():
    assert label_to_icon("letter_H") == "h"
    assert label_to_icon("digit_0") == "d0"
    assert label_to_icon("heart") == "heart"
    assert label_to_icon("circle") == "ring"
    assert label_to_icon("check") == "checkmark"
    assert label_to_icon("arrow_right") == "arrow"
    assert label_to_icon("wave") == "square-wave"


def test_out_of_scope_label_names_no_shape(handoff):
    """'none' is the classifier's explicit chitchat class; it must never reach a fold path."""
    assert label_to_icon("none") == ""
    vocab = Vocabulary(handoff)
    assert vocab.shape_for_icon("") is None
    # even if a caller wrongly marks it accepted, it must not resolve to a shape
    resolution = vocab.resolve("none", accepted=True)
    assert resolution.status == STATUS_UNSURE and not resolution.shape


def test_variants_collapse_to_one_concept(handoff):
    vocab = Vocabulary(handoff)
    assert set(vocab.concepts["spiral"]) == {"spiral", "spiral-v01", "spiral-v02"}
    # passing hard checks wins over finishing flat, which wins over fewer moves
    assert vocab.shape_for_icon("spiral") == "spiral"
    assert "spiral-v01" not in vocab.playable_concepts
    assert vocab.playable_concepts == ["heart", "t", "j", "u", "spiral"]


def test_variant_ranking_prefers_a_passing_plan(tmp_path):
    """A concept whose only flat mask fails its checks should still pick the passing one."""
    index = {"roll": "x", "shapes": [
        {"number": 60, "name": "ring-v01", "dir": "shapes/60-ring-v01", "moves": 3,
         "loose_hard_ok": False, "ends_flat_on_table": True},
        {"number": 61, "name": "ring-v02", "dir": "shapes/61-ring-v02", "moves": 9,
         "loose_hard_ok": True, "ends_flat_on_table": False},
    ]}
    (tmp_path / "index.json").write_text(json.dumps(index))
    assert Vocabulary(str(tmp_path)).shape_for_icon("ring") == "ring-v02"


def test_resolve_playable_plannable_and_unsure(handoff):
    vocab = Vocabulary(handoff)
    assert vocab.resolve("heart").status == STATUS_PLAYABLE
    assert vocab.resolve("heart").shape == "heart"
    assert vocab.resolve("bell").status == STATUS_PLANNABLE        # verified in cubot, not exported
    assert vocab.resolve("heart", accepted=False).status == STATUS_UNSURE


def test_flagged_shapes_are_reported(handoff):
    vocab = Vocabulary(handoff)
    flagged, why = vocab.is_flagged("t")
    assert flagged and "standing" in why


def test_playable_labels_routes_only_what_exists(handoff):
    routing = Vocabulary(handoff).playable_labels(["heart", "letter_T", "spiral", "star", "digit_0"])
    assert routing == {"heart": "heart", "letter_T": "t", "spiral": "spiral"}


# ------------------------------------------------------------------------------- linq

def test_parse_inbound_happy_path():
    msg = parse_inbound({
        "event_type": "message.received", "event_id": "evt-1",
        "data": {"id": "m-1", "direction": "inbound", "chat": {"id": "chat-1", "is_group": False},
                 "sender_handle": {"handle": "+12025559876", "is_me": False},
                 "parts": [{"type": "text", "value": "show hack the north some love"}]}})
    assert msg is not None
    assert (msg.chat_id, msg.sender, msg.text) == ("chat-1", "+12025559876",
                                                   "show hack the north some love")


@pytest.mark.parametrize("payload", [
    {"event_type": "message.delivered", "data": {}},                                  # wrong event
    {"event_type": "message.received", "data": {"chat": {"id": "c"}, "parts": []}},   # no text
    {"event_type": "message.received", "data": {"parts": [{"type": "text", "value": "hi"}],
                                                "sender_handle": {"handle": "+1", "is_me": True}}},
    "not a dict", None, {},
])
def test_parse_inbound_rejects_everything_else(payload):
    assert parse_inbound(payload) is None


def test_text_of_ignores_attachments_and_strips_control_chars():
    assert text_of([{"type": "text", "value": "make\x00 a heart"},
                    {"type": "image", "url": "..."}]) == "make a heart"


def test_seen_events_dedupes_and_bounds():
    seen = SeenEvents(capacity=2)
    assert seen.add("a") and not seen.add("a")
    seen.add("b"), seen.add("c")
    assert seen.add("a")                       # evicted by the bound, so it is new again


def test_rate_limiter_windows_per_sender():
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("+1", now=0) and limiter.allow("+1", now=1)
    assert not limiter.allow("+1", now=2)
    assert limiter.allow("+2", now=2)           # a different sender is unaffected
    assert limiter.allow("+1", now=70)          # window slid


def test_client_dry_run_records_without_sending():
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    client.reply("chat-1", "hello")
    assert client.sent[0]["url"].endswith("/chats/chat-1/messages")
    # the v3 reference wraps parts in `message`, unlike the quickstart's flat form
    assert client.sent[0]["body"] == {"message": {"parts": [{"type": "text", "value": "hello"}]}}


def test_client_react_posts_a_like_tapback():
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    client.react("msg-99", "like")
    assert client.sent[0]["url"].endswith("/messages/msg-99/reactions")
    assert client.sent[0]["body"] == {"operation": "add", "type": "like"}


def test_client_react_posts_a_custom_thinking_emoji():
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    client.react("msg-99", "custom", custom_emoji="🤔")
    assert client.sent[0]["body"] == {"operation": "add", "type": "custom", "custom_emoji": "🤔"}


def test_react_like_only_when_playable(handoff):
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    bridge = Bridge(_settings(handoff), classifier=FakeClassifier(),
                    executor=DryRunExecutor(log=lambda *a: None), client=client,
                    log=lambda *a: None)
    inbound = _inbound("show hackthenorth some love")
    inbound.message_id = "msg-heart"
    out = bridge.handle(inbound)
    assert out.resolution and out.resolution.ok
    reacts = [c["body"] for c in client.sent if c["url"].endswith("/messages/msg-heart/reactions")]
    assert reacts == [{"operation": "add", "type": "like"}]


def test_react_thinking_when_unsure(handoff):
    """Only when NOTHING can be resolved (no playable labels) do we 🤔."""
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    # Empty playable set forces a real decline.
    class EmptyVocab:
        playable_concepts = []
        def playable_labels(self, labels=None):
            return {}
        def resolve(self, label, accepted=True, nearest=None, nearest_label_map=None):
            from cubot_imessage.vocab import Resolution, STATUS_UNSURE
            return Resolution(status=STATUS_UNSURE, label=label, icon="", shape="",
                              nearest_playable="", nearest_score=0.0)

    bridge = Bridge(_settings(handoff),
                    classifier=FakeClassifier(label="none", accepted=False, confidence=0.2, margin=0.0),
                    vocabulary=EmptyVocab(),
                    executor=DryRunExecutor(log=lambda *a: None), client=client,
                    openai=OpenAIFallback(api_key="", log=lambda *a: None),
                    log=lambda *a: None)
    inbound = _inbound("whats for lunch")
    inbound.message_id = "msg-huh"
    out = bridge.handle(inbound)
    assert out.status == STATUS_UNSURE
    reacts = [c["body"] for c in client.sent if c["url"].endswith("/messages/msg-huh/reactions")]
    assert reacts == [{"operation": "add", "type": "custom", "custom_emoji": "🤔"}]


def test_letter_fallback_when_openai_returns_none(handoff):
    """Vague chitchat must ask again — never invent cheese→C or a random glyph."""
    class NoneOpenAI:
        enabled = True

        def resolve(self, text, allowed_labels):
            from cubot_imessage.openai_fallback import first_letter_fallback, clarify_guess
            return first_letter_fallback(text, allowed_labels) or clarify_guess()

    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    clf = FakeClassifier(label="none", accepted=False, confidence=0.1, margin=0.0)
    clf.labels = list(clf.labels) + ["letter_c", "letter_j", "triangle"]
    bridge = Bridge(_settings(handoff), classifier=clf,
                    executor=DryRunExecutor(log=lambda *a: None), client=client,
                    openai=NoneOpenAI(), log=lambda *a: None)
    import json as _json
    from pathlib import Path
    root = Path(handoff)
    for number, name in ((90, "triangle"), (91, "c")):
        if not (root / "shapes" / f"{number}-{name}").exists():
            d = root / "shapes" / f"{number}-{name}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "path.json").write_text(_json.dumps(_path_doc(name, number, [(1, 1, "out")])))
            idx = _json.loads((root / "index.json").read_text())
            idx["shapes"].append({"number": number, "name": name, "dir": f"shapes/{number}-{name}",
                                  "moves": 1, "complete": True, "loose_hard_ok": True,
                                  "ends_flat_on_table": True, "aliases": []})
            (root / "index.json").write_text(_json.dumps(idx))
    from cubot_imessage.vocab import Vocabulary
    from cubot_imessage.robot import ShapeLibrary
    bridge.vocab = Vocabulary(handoff)
    bridge.library = ShapeLibrary(handoff)
    bridge._playable_labels = None

    inbound = _inbound("i like cheese")
    inbound.message_id = "msg-cheese"
    out = bridge.handle(inbound)
    assert out.status == STATUS_UNSURE
    assert out.via == "clarify"
    assert out.plan is None
    assert "not sure" in (out.reply or "").lower() or "name a shape" in (out.reply or "").lower()
    reacts = [c["body"] for c in client.sent if c["url"].endswith("/messages/msg-cheese/reactions")]
    assert reacts == [{"operation": "add", "type": "custom", "custom_emoji": "🤔"}]


def test_explicit_letter_still_folds_without_openai(handoff):
    """Bare / explicit letter asks still map without inventing other shapes."""
    class NoneOpenAI:
        enabled = True

        def resolve(self, text, allowed_labels):
            from cubot_imessage.openai_fallback import first_letter_fallback, clarify_guess
            return first_letter_fallback(text, allowed_labels) or clarify_guess()

    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    clf = FakeClassifier(label="none", accepted=False, confidence=0.1, margin=0.0)
    clf.labels = list(clf.labels) + ["letter_c", "c"]
    bridge = Bridge(_settings(handoff), classifier=clf,
                    executor=DryRunExecutor(log=lambda *a: None), client=client,
                    openai=NoneOpenAI(), log=lambda *a: None)
    import json as _json
    from pathlib import Path
    root = Path(handoff)
    if not (root / "shapes" / "91-c").exists():
        d = root / "shapes" / "91-c"
        d.mkdir(parents=True, exist_ok=True)
        (d / "path.json").write_text(_json.dumps(_path_doc("c", 91, [(1, 1, "out")])))
        idx = _json.loads((root / "index.json").read_text())
        idx["shapes"].append({"number": 91, "name": "c", "dir": "shapes/91-c",
                              "moves": 1, "complete": True, "loose_hard_ok": True,
                              "ends_flat_on_table": True, "aliases": []})
        (root / "index.json").write_text(_json.dumps(idx))
    from cubot_imessage.vocab import Vocabulary
    from cubot_imessage.robot import ShapeLibrary
    bridge.vocab = Vocabulary(handoff)
    bridge.library = ShapeLibrary(handoff)
    bridge._playable_labels = None

    inbound = _inbound("make a C")
    inbound.message_id = "msg-letter-c"
    out = bridge.handle(inbound)
    assert out.resolution and out.resolution.ok
    assert out.plan is not None
    reacts = [c["body"] for c in client.sent if c["url"].endswith("/messages/msg-letter-c/reactions")]
    assert reacts == [{"operation": "add", "type": "like"}]


def test_openai_fallback_recovers_when_minilm_is_unsure(handoff):
    """MiniLM says none; OpenAI maps a joke to a playable letter and we fold."""
    from cubot_imessage.openai_fallback import OpenAIGuess

    class FakeOpenAI:
        enabled = True

        def resolve(self, text, allowed_labels):
            assert "letter_j" in allowed_labels
            return OpenAIGuess(label="letter_j", caption="Jerry — that starts with J",
                               confidence=0.91)

    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    clf = FakeClassifier(label="none", accepted=False, confidence=0.15, margin=0.0)
    clf.labels = list(clf.labels) + ["letter_j", "letter_u"]
    bridge = Bridge(_settings(handoff), classifier=clf,
                    executor=DryRunExecutor(log=lambda *a: None), client=client,
                    openai=FakeOpenAI(), log=lambda *a: None)
    inbound = _inbound("whats my name")
    inbound.message_id = "msg-name"
    out = bridge.handle(inbound)
    assert out.via == "openai"
    assert out.resolution and out.resolution.ok and out.plan and out.plan.shape == "j"
    assert "deciphered with ChatGPT" in out.reply
    reacts = [c["body"] for c in client.sent if c["url"].endswith("/messages/msg-name/reactions")]
    assert reacts == [{"operation": "add", "type": "like"}]


def test_accept_reply_credits_local_minilm(handoff):
    bridge = _bridge(handoff)
    out = bridge.handle(_inbound("make a heart"))
    assert out.via == "minilm"
    assert "deciphered using local MiniLM" in out.reply


def test_viewer_executor_builds_a_deep_link(handoff, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: opened.append(args[-1]) or type("P", (), {"pid": 0})())
    from cubot_imessage.robot import ViewerExecutor, ShapeLibrary
    plan = ShapeLibrary(handoff).plan("heart")
    result = ViewerExecutor(viewer_base="http://127.0.0.1:8787/sim", log=lambda *a: None).submit(plan, {})
    assert result["opened"] is True
    assert "shape=heart" in result["url"] and "play=1" in result["url"]
    assert opened and "shape=heart" in opened[0]


def test_parse_inbound_reads_the_2025_payload_layout():
    """A subscription created before 2026-02-03 nests the message and flattens the handles. Reading
    only the newer layout would drop every one of these silently."""
    msg = parse_inbound({
        "event_type": "message.received", "event_id": "evt-9",
        "webhook_version": "2025-01-01",
        "data": {"chat_id": "chat-7", "is_from_me": False, "is_group": True,
                 "from": "+12025550000",
                 "message": {"id": "m-9",
                             "parts": [{"type": "text", "value": "do a T"}]}}})
    assert msg is not None
    assert (msg.chat_id, msg.sender, msg.text) == ("chat-7", "+12025550000", "do a T")
    assert msg.event_id == "evt-9" and msg.is_group


def test_parse_inbound_ignores_our_own_echo_in_both_layouts():
    """`is_from_me` (2025-01-01) and `direction` (2026-02-03) both mean the robot's own reply came
    back. Replying to that is an infinite loop against a 100-message daily sandbox budget."""
    text = [{"type": "text", "value": "Showing Hack the North some love with a heart."}]
    assert parse_inbound({"event_type": "message.received",
                          "data": {"chat_id": "c", "from": "+1", "is_from_me": True,
                                   "message": {"parts": text}}}) is None
    assert parse_inbound({"event_type": "message.received",
                          "data": {"chat": {"id": "c"}, "direction": "outbound",
                                   "sender_handle": {"handle": "+1"}, "parts": text}}) is None


def test_pin_version_adds_the_payload_version_but_respects_an_explicit_one():
    assert pin_version("https://x.invalid/hook") == f"https://x.invalid/hook?version={WEBHOOK_VERSION}"
    assert pin_version("https://x.invalid/hook?token=t") == \
        f"https://x.invalid/hook?token=t&version={WEBHOOK_VERSION}"
    assert pin_version("https://x.invalid/hook?version=2025-01-01") == \
        "https://x.invalid/hook?version=2025-01-01"


def test_subscription_pins_the_payload_version():
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    client.create_subscription("https://tunnel.invalid/linq/webhook?token=abc")
    assert client.sent[0]["body"]["target_url"].endswith(f"version={WEBHOOK_VERSION}")


# ---------------------------------------------------------------- webhook signature verification

def _sign(secret: str, body: bytes, webhook_id: str = "evt-1",
          timestamp: str | None = None) -> dict:
    """Headers Linq would send for `body`, per the Standard Webhooks scheme."""
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    key = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    raw = base64.b64decode(key) if secret.startswith("whsec_") else key.encode()
    digest = hmac.new(raw, f"{webhook_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return {"webhook-id": webhook_id, "webhook-timestamp": timestamp,
            "webhook-signature": "v1," + base64.b64encode(digest).decode()}


SECRET = "whsec_" + base64.b64encode(b"cubot-test-signing-key").decode()


def test_verify_signature_accepts_a_genuine_delivery():
    body = json.dumps({"event_type": "message.received"}).encode()
    ok, why = verify_signature(SECRET, body, _sign(SECRET, body))
    assert ok, why


def test_verify_signature_rejects_a_tampered_body():
    """The whole point: a forged body cannot be made to match a signature over the original."""
    body = json.dumps({"event_type": "message.received", "data": {"parts": []}}).encode()
    headers = _sign(SECRET, body)
    ok, why = verify_signature(SECRET, body.replace(b"message.received", b"message.injected"), headers)
    assert not ok and "mismatch" in why


def test_verify_signature_rejects_a_replay_outside_the_tolerance():
    body = b"{}"
    stale = str(int(time.time()) - 3600)
    ok, why = verify_signature(SECRET, body, _sign(SECRET, body, timestamp=stale))
    assert not ok and "timestamp" in why


def test_verify_signature_rejects_the_wrong_secret_and_a_missing_header():
    body = b"{}"
    other = "whsec_" + base64.b64encode(b"a-different-key").decode()
    assert not verify_signature(SECRET, body, _sign(other, body))[0]
    assert not verify_signature(SECRET, body, {})[0]


def test_verify_signature_accepts_any_of_several_rotated_signatures():
    """Linq space-separates signatures while a secret is being rotated; one match is enough."""
    body = b'{"event_type":"message.received"}'
    good = _sign(SECRET, body)
    good["webhook-signature"] = "v1,AAAAinvalidAAAA " + good["webhook-signature"]
    ok, why = verify_signature(SECRET, body, good)
    assert ok, why


# ------------------------------------------------------------------------------- robot

def test_plan_loads_moves_and_warnings(handoff):
    plan = ShapeLibrary(handoff).plan("t")
    assert len(plan.moves) == 1 and plan.moves[0].side == "out"
    assert plan.moves[0].moving_side == "child"
    assert plan.ends_flat_on_table is False
    assert not any("standing" in w for w in plan.warnings)


def test_replay_reaches_goal_when_recorded(handoff):
    assert states_match_goal(ShapeLibrary(handoff).plan("heart"))


# ------------------------------------------------------------------------------- bridge

def test_handle_playable_plans_and_executes(handoff):
    bridge = _bridge(handoff)
    out = bridge.handle(_inbound("show hack the north some love"))
    assert out.status == STATUS_PLAYABLE
    assert out.plan is not None and out.plan.shape == "heart"
    assert out.executed == {"executor": "dryrun", "accepted": True, "moves": 2}
    assert "2 moves" in out.reply


def test_handle_warns_on_a_flagged_shape(handoff):
    out = _bridge(handoff, FakeClassifier(label="letter_T")).handle(_inbound("do a T"))
    assert out.status == STATUS_PLAYABLE and "standing" in out.reply


def test_handle_declines_below_threshold_without_executing(handoff):
    """MiniLM miss + no clear shape → ask again, do not invent a fold."""
    class ClarifyOpenAI:
        enabled = True

        def resolve(self, text, allowed_labels):
            from cubot_imessage.openai_fallback import clarify_guess
            return clarify_guess("Not sure what to fold — name a shape?")

    clf = FakeClassifier(label="none", accepted=False, margin=0.02, confidence=0.1)
    clf.labels = list(clf.labels) + ["letter_h", "heart"]
    bridge = _bridge(handoff, clf)
    bridge.openai = ClarifyOpenAI()
    out = bridge.handle(_inbound("hey what's up"))
    assert out.status == STATUS_UNSURE
    assert out.via == "clarify"
    assert out.plan is None
    assert "name a shape" in (out.reply or "").lower() or "not sure" in (out.reply or "").lower()


def test_handle_offers_the_nearest_playable_for_a_plannable_shape(handoff):
    out = _bridge(handoff, FakeClassifier(label="bell")).handle(_inbound("make a bell"))
    assert out.status == STATUS_PLANNABLE
    assert out.plan is None
    assert "heart" in out.reply                       # the fake's nearest suggestion


def test_help_short_circuits_the_classifier(handoff):
    out = _bridge(handoff).handle(_inbound("help"))
    assert out.status == "help" and out.intent is None
    assert "heart" in out.reply and "spiral" in out.reply


def test_reply_is_never_sent_without_a_client(handoff):
    bridge = _bridge(handoff)
    out = bridge.send_reply(bridge.handle(_inbound("make a heart")))
    assert out.replied is False


def test_reply_goes_only_to_the_originating_chat(handoff):
    settings = _settings(handoff)
    settings.auto_reply = True
    client = LinqClient("key", "https://example.invalid/v3", dry_run=True)
    bridge = Bridge(settings, classifier=FakeClassifier(), client=client,
                    executor=DryRunExecutor(log=lambda *a: None), log=lambda *a: None)
    bridge.send_reply(bridge.handle(_inbound("make a heart")))
    # thumbs-up only after a playable classify, then a text reply into the same chat — nowhere else
    assert len(client.sent) == 2
    assert client.sent[0]["url"].endswith("/messages/m1/reactions")
    assert client.sent[0]["body"] == {"operation": "add", "type": "like"}
    assert client.sent[1]["url"].endswith("/chats/c1/messages")
    assert "+15555550123" not in json.dumps(client.sent)

# ------------------------------------------------------------------------------- the real handoff

@pytest.mark.skipif(not os.path.isdir(REAL_HANDOFF), reason="cubot-v2/handoff not present")
def test_real_handoff_is_internally_consistent():
    """Every shipped path's deltas must reach its recorded goal, and every concept must resolve."""
    vocab, library = Vocabulary(REAL_HANDOFF), ShapeLibrary(REAL_HANDOFF)
    assert vocab.playable_concepts, "handoff/index.json lists no shapes"
    for name in library.names:
        plan = library.plan(name)
        assert plan.moves, f"{name} has no moves"
        assert states_match_goal(plan), f"{name}: replaying the deltas misses the recorded goal"
    for concept in vocab.playable_concepts:
        assert vocab.shape_for_icon(concept) in library.names
