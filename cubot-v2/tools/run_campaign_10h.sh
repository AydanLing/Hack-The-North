#!/usr/bin/env bash
# Overnight / multi-machine CuBot shape campaign (gate+fold), resume-safe.
#
# From a fresh clone on any machine with uv/python + cubot-v2 deps:
#
#   cd cubot-v2
#   chmod +x tools/run_campaign_10h.sh
#   ./tools/run_campaign_10h.sh                 # ~8 hours wall clock (default)
#   ./tools/run_campaign_10h.sh 8               # explicit
#   ./tools/run_campaign_10h.sh 12              # custom hours
#
# Prefer a plain terminal + nohup/tmux — not a Cursor/Cloud Agent chat.
# An IDE session can idle-disconnect; this script is meant to outlive the editor.
#
# What it does:
#   1) Re-fold friend's pick-key concepts (recover paths that lived under out/)
#   2) Fold as many other candidate masks as time allows (places/vehicles first,
#      then the rest of data/candidates/)
#   3) Periodically summarize PASSes
#
# Outputs land under out/campaign-<stamp>/ (gitignored). To ship into handoff
# later, build a manifest from PASSes and run tools/export_handoff.py or
# tools/patch_handoff_shapes.py.
#
# Keep --workers at 3 on an 8-core laptop (see docs/METHOD.md / FINDINGS.md).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOURS="${1:-8}"
WORKERS="${CAMPAIGN_WORKERS:-3}"
BUDGET="${CAMPAIGN_TIME_BUDGET:-200}"
K="${CAMPAIGN_K:-4}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${CAMPAIGN_OUT:-$ROOT/out/campaign-$STAMP}"
LOG="$OUT/campaign.log"
DEADLINE_EPOCH=$(( $(date +%s) + HOURS * 3600 ))

mkdir -p "$OUT"
exec > >(tee -a "$LOG") 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] campaign start hours=$HOURS workers=$WORKERS budget=${BUDGET}s out=$OUT"
echo "Profile: gentle (hard gates: holding≤6Nm, ground≤15mm, pivot_dip≤25mm, balance≥-50mm, stall≤10.6Nm)."
echo "Only complete+hard_ok+goal_is_mask rows count as PASS — violators are never export candidates."
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="${CAMPAIGN_PYTHON:-python3}"
if [[ -x /tmp/cubot-venv/bin/python ]]; then
  PY=/tmp/cubot-venv/bin/python
elif command -v uv >/dev/null 2>&1; then
  PY="uv run python"
fi

run_batch() {
  local queue="$1"
  local dest="$2"
  local label="$3"
  if [[ ! -s "$queue" ]]; then
    echo "[skip] empty queue $queue ($label)"
    return 0
  fi
  local now
  now=$(date +%s)
  if (( now >= DEADLINE_EPOCH )); then
    echo "[stop] deadline reached before $label"
    return 1
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === $label ($(wc -l < "$queue") items) ==="
  # explore_batch is resume-safe: re-running skips done (name, variant) pairs.
  $PY tools/explore_batch.py \
    --queue "$queue" \
    --out "$dest" \
    --workers "$WORKERS" \
    --time-budget "$BUDGET" \
    -k "$K" \
    --max-candidates 8 || true
  $PY tools/explore_summary.py --root "$dest" 2>/dev/null | tee "$dest/summary.txt" || true
  return 0
}

# --- queues -----------------------------------------------------------------
$PY tools/build_campaign_queue.py --mode pick-key -o "$OUT/queue-pick.jsonl"
$PY tools/build_campaign_queue.py --mode places-vehicles -o "$OUT/queue-places-vehicles.jsonl"
$PY tools/build_campaign_queue.py --mode candidates -o "$OUT/queue-all-candidates.jsonl"
$PY tools/build_campaign_queue.py --mode loose-handoff -o "$OUT/queue-loose-handoff.jsonl"

# Phase A: recover friend's 66 pick-key shapes (highest value)
run_batch "$OUT/queue-pick.jsonl" "$OUT/pick-key" "pick-key recover" || exit 0

# Phase B: gentle-optimize existing loose handoff shapes
run_batch "$OUT/queue-loose-handoff.jsonl" "$OUT/loose-handoff" "loose-handoff gentle replan" || exit 0

# Phase C: friend's new places/vehicles masks + the rest until the clock runs out
run_batch "$OUT/queue-places-vehicles.jsonl" "$OUT/places-vehicles" "places+vehicles breadth" || exit 0
run_batch "$OUT/queue-all-candidates.jsonl" "$OUT/all-candidates" "all candidates breadth" || exit 0

# Retry violators once if time remains
now=$(date +%s)
if (( now < DEADLINE_EPOCH )); then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === retry-violating pick-key ==="
  $PY tools/explore_batch.py --out "$OUT/pick-key" --retry-violating \
    --only-unpassed-concepts --workers "$WORKERS" --time-budget 280 -k "$K" || true
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] campaign finished"
echo "PASSes live under $OUT/*/results.jsonl — export with explore_summary + export_handoff when ready."
