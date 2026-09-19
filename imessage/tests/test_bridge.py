"""Bridge tests. Everything here runs without snake_pipeline and without a network: the classifier is
faked, and the handoff folder is a small fixture (plus the real one when it is present)."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubot_imessage.bridge import Bridge                                    # noqa: E402
from cubot_imessage.config import Settings                                  # noqa: E402
from cubot_imessage.intent import IntentResult                              # noqa: E402
from cubot_imessage.linq import (InboundMessage, LinqClient, RateLimiter,   # noqa: E402
                                 SeenEvents, parse_inbound, text_of)
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
        self.labels = ["heart", "letter_T", "spiral", "star", "bell", "digit_0"]
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


def test_variants_collapse_to_one_concept(handoff):
    vocab = Vocabulary(handoff)
    assert set(vocab.concepts["spiral"]) == {"spiral", "spiral-v01", "spiral-v02"}
    # passing hard checks wins over finishing flat, which wins over fewer moves
    assert vocab.shape_for_icon("spiral") == "spiral"
    assert "spiral-v01" not in vocab.playable_concepts
    assert vocab.playable_concepts == ["heart", "t", "spiral"]


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
    assert client.sent[0]["body"] == {"parts": [{"type": "text", "value": "hello"}]}


# ------------------------------------------------------------------------------- robot

def test_plan_loads_moves_and_warnings(handoff):
    plan = ShapeLibrary(handoff).plan("t")
    assert len(plan.moves) == 1 and plan.moves[0].side == "out"
    assert plan.moves[0].moving_side == "child"
    assert any("standing" in w for w in plan.warnings)


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
    bridge = _bridge(handoff, FakeClassifier(label="star", accepted=False, margin=0.02))
    out = bridge.handle(_inbound("hey what's up"))
    assert out.status == STATUS_UNSURE
    assert out.plan is None and out.executed is None
    assert "couldn't tell" in out.reply.lower()


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
    assert len(client.sent) == 1
    assert client.sent[0]["url"].endswith("/chats/c1/messages")


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
