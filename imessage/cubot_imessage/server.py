"""Stdlib HTTP server for Linq's inbound webhooks. No framework, no new dependencies.

    POST /linq/webhook?token=...     one webhook envelope; acknowledged immediately, handled off-thread
    GET  /healthz                    liveness plus the playable vocabulary

The webhook is acknowledged with 200 as soon as the payload parses, and the classify/fold/reply work
runs on a worker thread. Linq retries on a non-2xx or a slow response, and a retry that arrives while
the robot is mid-fold is exactly what we do not want; `SeenEvents` catches the duplicates that slip
through anyway.

**Authentication.** Linq's public docs specify the subscription's `target_url` but no request-signing
scheme, so the bridge authenticates with a shared secret that you put in the subscription URL
(`?token=...`, or an `X-Bridge-Token` header) and compares in constant time. A URL-borne secret is only
as private as the channel, so terminate TLS in front of this (a tunnel's HTTPS URL is fine) and treat
the token as a credential. If Linq later documents an HMAC signature header, verify that instead: this
token check is the floor, not the ceiling.
"""
from __future__ import annotations

import hmac
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .bridge import Bridge, Outcome
from .config import Settings
from .linq import RateLimiter, SeenEvents, parse_inbound

MAX_BODY_BYTES = 256 * 1024


class _Worker(threading.Thread):
    """Serializes the folding work: one robot, one queue, one at a time."""

    def __init__(self, bridge: Bridge, log=print):
        super().__init__(daemon=True, name="cubot-bridge-worker")
        self.bridge = bridge
        self.log = log
        self.q: "queue.Queue" = queue.Queue(maxsize=64)
        self.outcomes: list[Outcome] = []
        self._stop = threading.Event()

    def submit(self, inbound) -> bool:
        try:
            self.q.put_nowait(inbound)
            return True
        except queue.Full:
            self.log(f"[warn] queue full, dropping message from {inbound.sender}")
            return False

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                inbound = self.q.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                out = self.bridge.handle(inbound)
                self.bridge.send_reply(out)
                self.outcomes.append(out)
                self.log("[msg] " + out.log_line() + (" | replied" if out.replied else ""))
            except Exception as e:                       # a worker must never die on one bad message
                self.log(f"[error] handling {inbound.sender}: {type(e).__name__}: {e}")
            finally:
                self.q.task_done()

    def stop(self) -> None:
        self._stop.set()


class WebhookHandler(BaseHTTPRequestHandler):
    """Per-request handler. The server instance carries `bridge`, `settings`, `worker`, `seen`, `limiter`."""

    server_version = "CuBotBridge/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:       # BaseHTTPRequestHandler logs to stderr
        self.server.bridge_log(f"[http] {self.address_string()} {fmt % args}")   # type: ignore[attr-defined]

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self, query: dict) -> bool:
        expected = self.server.settings.webhook_token                # type: ignore[attr-defined]
        if not expected:
            return True                                              # open by choice; `doctor` warns
        supplied = (query.get("token", [""])[0]
                    or self.headers.get("X-Bridge-Token", "")
                    or "")
        return hmac.compare_digest(str(supplied), str(expected))

    # -- routes ------------------------------------------------------------------------------
    def do_GET(self) -> None:                                        # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route in ("/healthz", "/health", "/"):
            bridge: Bridge = self.server.bridge                      # type: ignore[attr-defined]
            self._json(200, {
                "ok": True,
                "playable": bridge.vocab.playable,
                "handoff_dir": bridge.settings.handoff_dir,
                "executor": bridge.executor.name,
                "auto_reply": bridge.settings.auto_reply,
                "queued": self.server.worker.q.qsize(),              # type: ignore[attr-defined]
                "handled": len(self.server.worker.outcomes),         # type: ignore[attr-defined]
            })
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:                                       # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        settings: Settings = self.server.settings                    # type: ignore[attr-defined]
        if route != settings.webhook_path.rstrip("/"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._token_ok(parse_qs(parsed.query)):
            self.server.bridge_log("[warn] rejected webhook with a bad token")   # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "bad token"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(400, {"ok": False, "error": "bad content length"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return

        # From here on, answer 200 for anything well-formed: a 4xx/5xx makes Linq retry, and a retry
        # is a second fold.
        inbound = parse_inbound(payload)
        if inbound is None:
            self._json(200, {"ok": True, "ignored": "not an inbound text message"})
            return
        if not self.server.seen.add(inbound.event_id):               # type: ignore[attr-defined]
            self._json(200, {"ok": True, "ignored": "duplicate delivery"})
            return
        if settings.allowed_senders and inbound.sender not in settings.allowed_senders:
            self.server.bridge_log(f"[warn] ignoring {inbound.sender}: not in LINQ_ALLOWED_SENDERS")  # type: ignore[attr-defined]
            self._json(200, {"ok": True, "ignored": "sender not allowed"})
            return
        if not self.server.limiter.allow(inbound.sender):            # type: ignore[attr-defined]
            self.server.bridge_log(f"[warn] rate limiting {inbound.sender}")     # type: ignore[attr-defined]
            self._json(200, {"ok": True, "ignored": "rate limited"})
            return

        queued = self.server.worker.submit(inbound)                  # type: ignore[attr-defined]
        self._json(200, {"ok": True, "queued": queued, "event_id": inbound.event_id})


class BridgeServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the bridge and its per-run state."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, settings: Settings, bridge: Bridge, log=print):
        super().__init__((settings.host, settings.port), WebhookHandler)
        self.settings = settings
        self.bridge = bridge
        self.bridge_log = log
        self.seen = SeenEvents()
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self.worker = _Worker(bridge, log=log)

    def start(self) -> "BridgeServer":
        self.worker.start()
        return self

    def shutdown_all(self) -> None:
        self.worker.stop()
        self.shutdown()
        self.server_close()


def serve(settings: Settings, bridge: Optional[Bridge] = None, log=print) -> None:
    """Run until Ctrl-C. Warms the model up first so the first text of the demo is not the slow one."""
    bridge = bridge or Bridge(settings, log=log)
    try:
        bridge.warmup()
        log(f"[boot] intent model ready ({bridge.classifier.encoder_name}, "
            f"{len(bridge.classifier.labels)} labels, {bridge.classifier.load_seconds:.1f}s)")
    except Exception as e:
        log(f"[boot] WARNING: intent model not ready: {e}")
    log(f"[boot] playable shapes: {', '.join(bridge.vocab.playable)}")
    log(f"[boot] executor={bridge.executor.name} auto_reply={settings.auto_reply}")
    if not settings.webhook_token:
        log("[boot] WARNING: LINQ_WEBHOOK_TOKEN is empty — the webhook endpoint accepts anyone")
    server = BridgeServer(settings, bridge, log=log).start()
    log(f"[boot] listening on http://{settings.host}:{settings.port}{settings.webhook_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\n[exit] stopping")
    finally:
        server.shutdown_all()
        time.sleep(0.1)
