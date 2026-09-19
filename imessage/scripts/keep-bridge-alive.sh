#!/bin/bash
# Keep the CuBot Linq webhook bridge listening on :8787.
# Does NOT restart cloudflared (that would change the trycloudflare URL and break the Linq subscription).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${CUBOT_VENV:-/tmp/cubot-venv}"
PY="$VENV/bin/python"
LOG="${CUBOT_BRIDGE_LOG:-/tmp/cubot-bridge.log}"
PIDFILE="${CUBOT_BRIDGE_PID:-/tmp/cubot-bridge.pid}"
HEALTH="http://127.0.0.1:8787/health"
INTERVAL="${CUBOT_BRIDGE_WATCH_S:-5}"

is_up() {
  curl -sf -m 2 "$HEALTH" >/dev/null 2>&1
}

start_bridge() {
  cd "$ROOT" || exit 1
  # clear stale pid
  if [[ -f "$PIDFILE" ]]; then
    old=$(cat "$PIDFILE" 2>/dev/null || true)
    if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
      kill "$old" 2>/dev/null || true
      sleep 0.5
    fi
  fi
  pkill -f 'cubot_imessage serve' 2>/dev/null || true
  sleep 0.3
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting cubot_imessage serve" >>"$LOG"
  nohup env PYTHONPATH="$ROOT" PYTHONUNBUFFERED=1 "$PY" -u -m cubot_imessage serve >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] bridge pid $(cat "$PIDFILE")" >>"$LOG"
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] keep-bridge-alive watching $HEALTH every ${INTERVAL}s" >>"$LOG"
while true; do
  if ! is_up; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] health check failed — restarting bridge" >>"$LOG"
    start_bridge
    # give it a moment, then verify
    sleep 2
    if is_up; then
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] bridge healthy again" >>"$LOG"
    else
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] bridge still down after restart" >>"$LOG"
    fi
  fi
  sleep "$INTERVAL"
done
