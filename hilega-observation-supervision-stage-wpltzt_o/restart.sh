#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

"$ROOT/scripts/stop.sh"
"$ROOT/scripts/start.sh"
"$ROOT/scripts/status.sh"


# Analytics startup is supervised through scripts/start.sh.

# ===== MIDPOINT HISTORICAL AUTO-PUBLISHER =====
PUBLISHER_PID_FILE="data/midpoint-historical-publisher.pid"
PUBLISHER_LOG_FILE="data/logs/midpoint-historical-publisher.log"

mkdir -p data/logs
if [ -f "$PUBLISHER_PID_FILE" ]; then
    PUBLISHER_PID="$(cat "$PUBLISHER_PID_FILE" 2>/dev/null || true)"
    if [ -n "$PUBLISHER_PID" ] && kill -0 "$PUBLISHER_PID" 2>/dev/null; then
        kill "$PUBLISHER_PID" 2>/dev/null || true
    fi
fi

nohup env PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" \
    "$ROOT/.venv/bin/python" \
    "$ROOT/scripts/midpoint_auto_publish_historical.py" \
    --interval-seconds 900 \
    >> "$PUBLISHER_LOG_FILE" 2>&1 < /dev/null &
PUBLISHER_PID=$!
echo "$PUBLISHER_PID" > "$PUBLISHER_PID_FILE"
sleep 0.5
if kill -0 "$PUBLISHER_PID" 2>/dev/null; then
    echo "midpoint-history: publisher started (PID $PUBLISHER_PID)"
else
    echo "midpoint-history: publisher failed; check $PUBLISHER_LOG_FILE"
    exit 1
fi
# ===== END MIDPOINT HISTORICAL AUTO-PUBLISHER =====

# ===== HILEGA WMA-GAP FORWARD-CONFIRMATION PUBLISHER =====
"$ROOT/scripts/stop_hilega_wma_gap_forward_publisher.sh" || true
"$ROOT/scripts/start_hilega_wma_gap_forward_publisher.sh"
# ===== END HILEGA WMA-GAP FORWARD-CONFIRMATION PUBLISHER =====

# UI-only operational readiness
bash "$ROOT/scripts/start_operational_readiness.sh"
