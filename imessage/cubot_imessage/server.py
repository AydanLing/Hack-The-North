"""Stdlib HTTP server for Linq's inbound webhooks. No framework, no new dependencies.

    POST /linq/webhook?token=...     one webhook envelope; acknowledged immediately, handled off-thread
    GET  /healthz                    liveness plus the playable vocabulary

The webhook is acknowledged with 200 as soon as the payload parses, and the classify/fold/reply work
runs on a worker thread. Linq retries on a non-2xx or a slow response, and a retry that arrives while
the robot is mid-fold is exactly what we do not want; `SeenEvents` catches the duplicates that slip
through anyway.

**Authentication.** Two independent checks, in order of strength:

1. *HMAC signature* (`LINQ_WEBHOOK_SECRET`). Linq signs every delivery per the Standard Webhooks spec
   and returns the signing secret once, when the subscription is created. This is the real check: it
   proves Linq sent the exact bytes, and the timestamp in the signed material bounds replays. Set the
   secret and nothing else is needed.
2. *Shared-secret URL token* (`LINQ_WEBHOOK_TOKEN`). A `?token=...` on the subscription URL, or an
   `X-Bridge-Token` header, compared in constant time. This is the fallback for before you have a
   signing secret in hand. A URL-borne secret is only as private as the channel, so terminate TLS in
   front of it.

Either one passing is enough, but a *present* signature that fails to verify is fatal regardless of
the token — a valid token cannot rescue a forged body.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from .bridge import Bridge, Outcome
from .config import Settings, REPO_ROOT
from .linq import RateLimiter, SeenEvents, parse_inbound, verify_signature

MAX_BODY_BYTES = 256 * 1024
DEFAULT_SIM_DIR = os.path.join(REPO_ROOT, "cubot_urdf")
SIM_PREFIX = "/sim"


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

    def _authenticate(self, query: dict, body: bytes) -> tuple[bool, str]:
        """(ok, reason-when-not) for one delivery, given the raw body bytes."""
        secret = self.server.settings.webhook_secret                 # type: ignore[attr-defined]
        signed = bool(self.headers.get("webhook-signature")
                      or self.headers.get("X-Webhook-Signature"))
        if secret and signed:
            ok, why = verify_signature(secret, body, self.headers)
            return ok, why
        if signed and not secret:
            # Linq is signing and we have nowhere to check it. Not fatal — the token still gates the
            # endpoint — but it means the strong check is sitting unused.
            self.server.bridge_log(                                  # type: ignore[attr-defined]
                "[warn] delivery is signed but LINQ_WEBHOOK_SECRET is unset; "
                "falling back to the URL token")
        elif secret and not signed:
            # Downgrading to the weaker check by simply omitting the header must not be possible.
            return False, "LINQ_WEBHOOK_SECRET is set but the delivery had no signature header"
        return (True, "") if self._token_ok(query) else (False, "bad token")

    def _file(self, path: str, content_type: str = "") -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json(404, {"ok": False, "error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path)[0]
                         or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_sim(self, route: str) -> None:
        """Serve cubot_urdf/ under /sim/ so the viewer executor can open a localhost URL."""
        sim_dir = getattr(self.server, "sim_dir", DEFAULT_SIM_DIR)  # type: ignore[attr-defined]
        rel = unquote(route[len(SIM_PREFIX):]).lstrip("/") or "fold_viewer.html"
        # no path traversal
        candidate = os.path.realpath(os.path.join(sim_dir, rel))
        if not candidate.startswith(os.path.realpath(sim_dir) + os.sep) and \
           candidate != os.path.realpath(sim_dir):
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        if os.path.isdir(candidate):
            candidate = os.path.join(candidate, "fold_viewer.html")
        if not os.path.isfile(candidate):
            self._json(404, {"ok": False, "error": f"no such file under /sim: {rel}"})
            return
        self._file(candidate)

    # -- routes ------------------------------------------------------------------------------
    def do_GET(self) -> None:                                        # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route.startswith(SIM_PREFIX):
            self._serve_sim(urlparse(self.path).path)
            return
        if route in ("/healthz", "/health", "/"):
            bridge: Bridge = self.server.bridge                      # type: ignore[attr-defined]
            self._json(200, {
                "ok": True,
                "playable": bridge.vocab.playable,
                "handoff_dir": bridge.settings.handoff_dir,
                "executor": bridge.executor.name,
                "auto_reply": bridge.settings.auto_reply,
                "react_on_receive": bridge.settings.react_on_receive,
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
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(400, {"ok": False, "error": "bad content length"})
            return
        body = self.rfile.read(length)

        # Authenticate before parsing: the signature covers the bytes as sent, so decoding and
        # re-encoding the JSON would invalidate it.
        authentic, why = self._authenticate(parse_qs(parsed.query), body)
        if not authentic:
            self.server.bridge_log(f"[warn] rejected webhook: {why}")            # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": why})
            return

        try:
            payload = json.loads(body.decode("utf-8", "replace"))
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

    def __init__(self, settings: Settings, bridge: Bridge, log=print,
                 sim_dir: str = DEFAULT_SIM_DIR):
        super().__init__((settings.host, settings.port), WebhookHandler)
        self.settings = settings
        self.bridge = bridge
        self.bridge_log = log
        self.sim_dir = sim_dir if os.path.isdir(sim_dir) else DEFAULT_SIM_DIR
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
    log(f"[boot] executor={bridge.executor.name} auto_reply={settings.auto_reply} "
        f"react={'👍/🤔' if settings.react_on_receive else 'off'}")
    log(f"[boot] fold viewer at http://{settings.host}:{settings.port}{SIM_PREFIX}/fold_viewer.html")
    if settings.webhook_secret:
        log("[boot] webhook signatures will be verified (LINQ_WEBHOOK_SECRET is set)")
    elif settings.webhook_token:
        log("[boot] NOTE: no LINQ_WEBHOOK_SECRET — authenticating on the URL token alone. Set the "
            "signing secret from the subscription response to verify signatures.")
    else:
        log("[boot] WARNING: neither LINQ_WEBHOOK_SECRET nor LINQ_WEBHOOK_TOKEN is set — "
            "the webhook endpoint accepts anyone")
    server = BridgeServer(settings, bridge, log=log).start()
    log(f"[boot] listening on http://{settings.host}:{settings.port}{settings.webhook_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\n[exit] stopping")
    finally:
        server.shutdown_all()
        time.sleep(0.1)
