"""Linq iMessage API client and inbound-webhook parsing (stdlib only).

API shape, from https://docs.linqapp.com/channel/imessage/ :

    POST {base}/messages                  {"to": ["+1555..."], "message": {"parts": [{"type","value"}]}}
    POST {base}/chats/{chat_id}/messages  {"parts": [{"type": "text", "value": "..."}]}
    POST {base}/webhook-subscriptions     {"target_url": "...", "subscribed_events": [...]}

    Authorization: Bearer $LINQ_API_KEY

Inbound `message.received` events arrive as a common envelope wrapping `data`::

    {"event_type": "message.received", "event_id": "...", "data": {
        "chat": {"id": "...", "is_group": false}, "id": "...", "direction": "inbound",
        "sender_handle": {"handle": "+1555...", "is_me": false},
        "parts": [{"type": "text", "value": "show hack the north some love"}]}}

Everything in that payload is untrusted input from whoever texted the number. `InboundMessage.text`
is *data* for the classifier, never a command: the bridge's only outputs are one of the shape labels
in the handoff vocabulary and a templated reply.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

INBOUND_EVENT = "message.received"
DEFAULT_EVENTS = ("message.received",)
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


def parse_inbound(payload: Any) -> Optional[InboundMessage]:
    """InboundMessage for a `message.received` envelope, or None for any other event or a payload
    that is missing what a reply needs (chat id, sender, non-empty text). Never raises."""
    if not isinstance(payload, dict):
        return None
    if payload.get("event_type") != INBOUND_EVENT:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    if data.get("direction") not in (None, "inbound"):
        return None

    chat = data.get("chat") if isinstance(data.get("chat"), dict) else {}
    handle = data.get("sender_handle") if isinstance(data.get("sender_handle"), dict) else {}
    if handle.get("is_me") is True:                      # our own echo coming back: never reply to it
        return None

    text = text_of(data.get("parts"))
    chat_id = str(chat.get("id") or "")
    sender = _clean(str(handle.get("handle") or ""), 64)
    if not (text and chat_id and sender):
        return None
    return InboundMessage(
        event_id=str(payload.get("event_id") or data.get("id") or ""),
        message_id=str(data.get("id") or ""),
        chat_id=chat_id,
        sender=sender,
        text=text,
        is_group=bool(chat.get("is_group")),
        raw=payload,
    )


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
        bridge can never message a number that did not message it first."""
        if not chat_id:
            raise LinqError("reply() needs a chat_id")
        return self._post(f"/chats/{chat_id}/messages", {"parts": self._parts(text)})

    # -- webhooks ----------------------------------------------------------------------------
    def create_subscription(self, target_url: str, events: tuple[str, ...] = DEFAULT_EVENTS) -> dict:
        return self._post("/webhook-subscriptions",
                          {"target_url": target_url, "subscribed_events": list(events)})


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
