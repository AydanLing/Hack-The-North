"""Linq Partner API v3 client and inbound-webhook parsing (stdlib only).

API shape, from https://docs.linqapp.com/api/ :

    POST {base}/messages                  {"to": ["+1555..."], "message": {"parts": [{"type","value"}]}}
    POST {base}/chats/{chat_id}/messages  {"message": {"parts": [{"type": "text", "value": "..."}]}}
    POST {base}/webhook-subscriptions     {"target_url": "...", "subscribed_events": [...]}

    Authorization: Bearer $LINQ_API_KEY

Inbound `message.received` events arrive as a common envelope wrapping `data`. **Two payload layouts
exist** and the one you get is pinned by a `?version=` query parameter on the `target_url` you
register (https://docs.linqapp.com/guides/webhooks/events/). They disagree about where the text
lives, so both are parsed here — a subscription created before 2026-02-03 speaks the older dialect
and reading only the newer one would silently drop every message::

    2026-02-03   data.parts[].value   data.sender_handle.handle   data.chat.id    data.direction
    2025-01-01   data.message.parts[].value   data.from           data.chat_id    data.is_from_me

Deliveries are signed with HMAC-SHA256 per the Standard Webhooks spec; see `verify_signature`.

Everything in that payload is untrusted input from whoever texted the number. `InboundMessage.text`
is *data* for the classifier, never a command: the bridge's only outputs are one of the shape labels
in the handoff vocabulary and a templated reply.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

INBOUND_EVENT = "message.received"
DEFAULT_EVENTS = ("message.received",)

# The payload layout this bridge prefers. Pinned on the subscription's target_url, because Linq
# otherwise hands out whatever is newest at creation time.
WEBHOOK_VERSION = "2026-02-03"

# Standard Webhooks: reject replays older than this. 5 minutes is the value Linq's own examples use.
SIGNATURE_TOLERANCE_S = 300

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class LinqError(RuntimeError):
    """A non-2xx response from the Linq API, or a transport failure."""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class InboundMessage:
    """One inbound iMessage, flattened out of the webhook envelope."""

    event_id: str
    message_id: str
    chat_id: str
    sender: str
    text: str
    is_group: bool = False
    raw: dict = field(default_factory=dict, repr=False)


def _clean(text: str, limit: int = 2000) -> str:
    """Strip control characters and collapse whitespace; cap the length so a wall of text cannot
    blow up the encoder or a log line."""
    return _CONTROL.sub("", " ".join(str(text).split()))[:limit]


def text_of(parts: Any) -> str:
    """Join the `text` parts of a message body, ignoring attachments and unknown part types."""
    if not isinstance(parts, list):
        return ""
    chunks = [str(p.get("value", "")) for p in parts
              if isinstance(p, dict) and p.get("type", "text") == "text" and p.get("value")]
    return _clean(" ".join(chunks))


def pin_version(target_url: str, version: str = WEBHOOK_VERSION) -> str:
    """Add `?version=` to a webhook URL, leaving an explicit one alone.

    Also the documented way to reuse a host: Linq allows each `target_url` only once per account, so
    the query string is what distinguishes two subscriptions.
    """
    if not version:
        return target_url
    parts = urllib.parse.urlsplit(target_url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if any(key == "version" for key, _ in query):
        return target_url
    query.append(("version", version))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def parse_inbound(payload: Any) -> Optional[InboundMessage]:
    """InboundMessage for a `message.received` envelope, or None for any other event or a payload
    that is missing what a reply needs (chat id, sender, non-empty text). Never raises.

    Accepts both documented payload versions. The newer layout is tried first and the older one is
    used to fill whatever it left empty, so neither dialect needs to be detected up front — the
    `webhook_version` field is advisory and absent from hand-rolled test payloads.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("event_type") != INBOUND_EVENT:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    # Direction: the new layout says so explicitly, the old one inverts a boolean. Either saying
    # "this came from us" means our own echo is coming back, and replying to it would loop.
    if str(data.get("direction") or "inbound") != "inbound":
        return None
    if data.get("is_from_me") is True:
        return None

    chat = _dict(data.get("chat"))
    message = _dict(data.get("message"))                 # 2025-01-01 nests the message
    sender_handle = _dict(data.get("sender_handle")) or _dict(data.get("from_handle"))
    if sender_handle.get("is_me") is True:
        return None

    text = text_of(data.get("parts")) or text_of(message.get("parts"))
    chat_id = str(chat.get("id") or data.get("chat_id") or "")
    sender = _clean(str(sender_handle.get("handle") or data.get("from") or ""), 64)
    if not (text and chat_id and sender):
        return None
    return InboundMessage(
        event_id=str(payload.get("event_id") or message.get("id") or data.get("id") or ""),
        message_id=str(data.get("id") or message.get("id") or ""),
        chat_id=chat_id,
        sender=sender,
        text=text,
        is_group=bool(chat.get("is_group") or data.get("is_group")),
        raw=payload,
    )


# ------------------------------------------------------------------------------ signature checking

def _signing_key(secret: str) -> bytes:
    """Raw HMAC key from a Linq signing secret. Linq's secrets are `whsec_` + base64 of the key
    bytes; anything else is used as raw UTF-8 so a hand-set test secret still works."""
    raw = str(secret)
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_"):]
        try:
            return base64.b64decode(raw, validate=True)
        except (ValueError, TypeError):
            pass
    return raw.encode()


def verify_signature(secret: str, body: bytes, headers: Any,
                     tolerance_s: float = SIGNATURE_TOLERANCE_S,
                     now: Optional[float] = None) -> tuple[bool, str]:
    """Verify a Standard Webhooks signature. Returns (ok, reason-when-not).

    Linq signs `{webhook-id}.{webhook-timestamp}.{body}` with HMAC-SHA256 and sends the result
    base64-encoded in `webhook-signature` as `v1,<sig>`, space-separating several during a secret
    rotation — so any one match is enough. Documented at https://docs.linqapp.com/guides/webhooks/ .

    `body` must be the bytes as received. Parsing and re-serialising JSON changes key order and
    whitespace, which changes the digest.
    """
    def header(name: str) -> str:
        getter = getattr(headers, "get", None)
        return str(getter(name) or "") if getter else ""

    webhook_id = header("webhook-id")
    timestamp = header("webhook-timestamp")
    signature = header("webhook-signature")
    legacy = header("X-Webhook-Signature")

    if not signature and not legacy:
        return False, "no webhook-signature header"

    if timestamp:
        # A valid signature over a very old body is still a replay, so the timestamp is part of the
        # check rather than metadata.
        try:
            sent_at = float(timestamp)
        except ValueError:
            return False, "malformed webhook-timestamp"
        drift = abs((time.time() if now is None else now) - sent_at)
        if tolerance_s and drift > tolerance_s:
            return False, f"timestamp is {drift:.0f}s away (tolerance {tolerance_s:.0f}s)"

    key = _signing_key(secret)
    if signature:
        expected = base64.b64encode(
            hmac.new(key, f"{webhook_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
        ).decode()
        for candidate in signature.split():
            version, _, value = candidate.partition(",")
            if version == "v1" and hmac.compare_digest(value, expected):
                return True, ""
        return False, "signature mismatch"

    # Deprecated header, still sent alongside the modern one. Linq documents it as a hex HMAC-SHA256
    # but not what it covers; body-only is the assumption. Only ever reached if `webhook-signature`
    # is absent, and a wrong guess fails closed.
    if hmac.compare_digest(legacy.lower(), hmac.new(key, body, hashlib.sha256).hexdigest()):
        return True, ""
    return False, "legacy signature mismatch"


class LinqClient:
    """Thin Linq v3 client. `dry_run=True` records calls instead of performing them, which is what the
    tests and `--dry-run` use — nothing leaves the machine."""

    def __init__(self, api_key: str, base_url: str, timeout_s: float = 15.0, from_number: str = "",
                 dry_run: bool = False):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.from_number = from_number
        self.dry_run = dry_run
        self.sent: list[dict] = []

    # -- transport ---------------------------------------------------------------------------
    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        if self.dry_run:
            self.sent.append({"url": url, "body": body})
            return {"dry_run": True, "url": url, "body": body}
        if not self.api_key:
            raise LinqError("LINQ_API_KEY is not set; cannot call the Linq API")
        raw = json.dumps(body).encode()
        req = urllib.request.Request(url, data=raw, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:800]
            raise LinqError(f"Linq {e.code} on POST {path}: {detail}", e.code, detail) from None
        except urllib.error.URLError as e:
            raise LinqError(f"cannot reach Linq at {url}: {e.reason}") from None
        self.sent.append({"url": url, "body": body})
        try:
            return json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            return {"raw": text}

    # -- messaging ---------------------------------------------------------------------------
    @staticmethod
    def _parts(text: str) -> list[dict]:
        return [{"type": "text", "value": _clean(text)}]

    def send_to(self, to: list[str], text: str) -> dict:
        """Start (or continue) a chat with `to` — E.164 numbers. Returns Linq's response, whose
        `chat_id` is what `reply` wants."""
        body: dict = {"to": list(to), "message": {"parts": self._parts(text)}}
        if self.from_number:
            body["from"] = self.from_number
        return self._post("/messages", body)

    def reply(self, chat_id: str, text: str) -> dict:
        """Reply inside an existing chat. This is the only send the webhook handler performs, so the
        bridge can never message a number that did not message it first — which is also what Linq's
        sandbox requires, since sending to someone who has not texted you fails with 403/2008."""
        if not chat_id:
            raise LinqError("reply() needs a chat_id")
        return self._post(f"/chats/{chat_id}/messages", {"message": {"parts": self._parts(text)}})

    def react(self, message_id: str, reaction: str = "like", operation: str = "add") -> dict:
        """Tapback on an inbound message. `like` is the iMessage thumbs-up.

        Docs: POST /v3/messages/{messageId}/reactions with operation add|remove and type like|love|…
        """
        if not message_id:
            raise LinqError("react() needs a message_id")
        return self._post(f"/messages/{message_id}/reactions",
                          {"operation": operation, "type": reaction})

    # -- webhooks ----------------------------------------------------------------------------
    def create_subscription(self, target_url: str, events: tuple[str, ...] = DEFAULT_EVENTS,
                            version: str = WEBHOOK_VERSION) -> dict:
        """Subscribe to inbound events. The payload layout is pinned on the URL rather than left to
        Linq's default, so the shape `parse_inbound` sees does not depend on the day the subscription
        happened to be created."""
        return self._post("/webhook-subscriptions",
                          {"target_url": pin_version(target_url, version),
                           "subscribed_events": list(events)})


class SeenEvents:
    """Bounded set of delivered `event_id`s. Webhooks retry, and replaying a delivery would fold the
    robot twice, so every handler run is gated on this."""

    def __init__(self, capacity: int = 4096):
        self.capacity = capacity
        self._order: list[str] = []
        self._seen: set[str] = set()

    def add(self, event_id: str) -> bool:
        """True if this is the first time we see `event_id` (and it is now recorded)."""
        if not event_id:
            return True
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        self._order.append(event_id)
        if len(self._order) > self.capacity:
            self._seen.discard(self._order.pop(0))
        return True


class RateLimiter:
    """Sliding-window cap per sender: the robot takes 12-46 s to fold, so a flood has to be dropped
    rather than queued."""

    def __init__(self, per_minute: int = 6, window_s: float = 60.0):
        self.per_minute = per_minute
        self.window_s = window_s
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic() if now is None else now
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
        if len(hits) >= self.per_minute:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True
