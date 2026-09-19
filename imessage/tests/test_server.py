"""Webhook endpoint tests, over a real socket on an ephemeral port.

These exist because the interesting part of `server.py` is not any one function but the *interaction*
of three things: the HMAC signature, the URL token, and the order they run in relative to parsing the
body. A unit test of `verify_signature` cannot catch the mistake that matters here — verifying a
re-serialised body, or letting a valid token wave through a forged one.

No network: the server binds 127.0.0.1 on port 0 and the classifier is faked.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubot_imessage.server import BridgeServer                                # noqa: E402

from test_bridge import FakeClassifier, _bridge, _settings, handoff           # noqa: E402,F401

SECRET = "whsec_" + base64.b64encode(b"cubot-server-test-key").decode()
TOKEN = "a-url-token"


def _payload(text: str = "show hackthenorth some love") -> bytes:
    return json.dumps({
        "event_type": "message.received", "event_id": f"evt-{time.time_ns()}",
        "webhook_version": "2026-02-03",
        "data": {"id": "m-1", "direction": "inbound", "chat": {"id": "chat-1", "is_group": False},
                 "sender_handle": {"handle": "+12025559876", "is_me": False},
                 "parts": [{"type": "text", "value": text}]},
    }).encode()


def _sign(secret: str, body: bytes, webhook_id: str = "evt-sig", timestamp: str | None = None) -> dict:
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    key = base64.b64decode(secret[len("whsec_"):]) if secret.startswith("whsec_") else secret.encode()
    digest = hmac.new(key, f"{webhook_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return {"webhook-id": webhook_id, "webhook-timestamp": timestamp,
            "webhook-signature": "v1," + base64.b64encode(digest).decode()}


@pytest.fixture
def server(handoff):                                                          # noqa: F811
    """A live BridgeServer with a signing secret and a URL token, on a free port."""
    settings = _settings(handoff)
    settings.webhook_secret = SECRET
    settings.webhook_token = TOKEN
    settings.host, settings.port = "127.0.0.1", 0
    instance = BridgeServer(settings, _bridge(handoff, FakeClassifier()), log=lambda *a: None)
    instance.start()
    import threading
    threading.Thread(target=instance.serve_forever, daemon=True).start()
    yield instance
    instance.shutdown_all()


def _post(server, body: bytes, headers: dict | None = None, query: str = "") -> tuple[int, dict]:
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}{server.settings.webhook_path}{query}"
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_a_signed_delivery_is_accepted_and_queued(server):
    body = _payload()
    status, reply = _post(server, body, _sign(SECRET, body))
    assert status == 200 and reply["queued"] is True


def test_a_tampered_body_is_rejected_even_with_a_valid_token(server):
    """The token authenticates the *caller*; the signature authenticates the *bytes*. Someone who
    learns the URL (it travels in a subscription, a tunnel log, a screen share) must still not be
    able to put words in a sender's mouth."""
    body = _payload()
    headers = _sign(SECRET, body)
    forged = _payload("fold into a lightning bolt")
    status, reply = _post(server, forged, headers, query=f"?token={TOKEN}")
    assert status == 401 and "mismatch" in reply["error"]


def test_a_stale_signature_is_rejected_as_a_replay(server):
    body = _payload()
    stale = str(int(time.time()) - 3600)
    status, reply = _post(server, body, _sign(SECRET, body, timestamp=stale))
    assert status == 401 and "timestamp" in reply["error"]


def test_an_unsigned_delivery_is_rejected_when_a_secret_is_configured(server):
    """Otherwise an attacker downgrades to the weaker check just by omitting the header."""
    status, reply = _post(server, _payload(), query=f"?token={TOKEN}")
    assert status == 401 and "no signature" in reply["error"]


def test_the_token_alone_is_enough_when_no_secret_is_configured(server):
    """The documented fallback for before the signing secret is in hand."""
    server.settings.webhook_secret = ""
    status, reply = _post(server, _payload(), query=f"?token={TOKEN}")
    assert status == 200 and reply["queued"] is True

    status, reply = _post(server, _payload(), query="?token=wrong")
    assert status == 401 and reply["error"] == "bad token"


def test_a_duplicate_delivery_folds_only_once(server):
    """Linq retries at least once on a timeout, and a retry mid-fold is a second fold."""
    body = _payload()
    headers = _sign(SECRET, body)
    first = _post(server, body, headers)
    second = _post(server, body, headers)
    assert first[1]["queued"] is True
    assert second[0] == 200 and second[1]["ignored"] == "duplicate delivery"


def test_an_oversized_body_is_refused_before_it_is_read(server):
    status, _ = _post(server, b"x" * (256 * 1024 + 1), _sign(SECRET, b"x"))
    assert status == 400


def test_healthz_lists_the_playable_vocabulary(server):
    host, port = server.server_address[:2]
    with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=5) as response:
        payload = json.loads(response.read())
    assert payload["ok"] is True and payload["playable"]
