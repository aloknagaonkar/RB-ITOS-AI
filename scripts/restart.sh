#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT/scripts/stop.sh"
"$ROOT/scripts/start.sh"
"$ROOT/scripts/status.sh"


# ===== LIVE SHADOW WORKER V1 =====
SHADOW_PID_FILE="data/live-shadow-worker.pid"
SHADOW_LOG_FILE="data/live-shadow-worker.log"

mkdir -p data

# Stop previous shadow worker.
if [ -f "$SHADOW_PID_FILE" ]; then
    SHADOW_PID="$(cat "$SHADOW_PID_FILE" 2>/dev/null || true)"
    if [ -n "$SHADOW_PID" ] && kill -0 "$SHADOW_PID" 2>/dev/null; then
        kill "$SHADOW_PID" 2>/dev/null || true

        for _ in $(seq 1 20); do
            if ! kill -0 "$SHADOW_PID" 2>/dev/null; then
                break
            fi
            sleep 0.25
        done

        if kill -0 "$SHADOW_PID" 2>/dev/null; then
            kill -9 "$SHADOW_PID" 2>/dev/null || true
        fi

        echo "live-shadow: stopped (PID $SHADOW_PID)"
    else
        echo "live-shadow: stale pid file"
    fi
    rm -f "$SHADOW_PID_FILE"
else
    # Covers a shadow worker previously started manually.
    EXISTING_SHADOW_PID="$(pgrep -f '[m]arket_lab.live_shadow_worker_v1' | head -1 || true)"
    if [ -n "$EXISTING_SHADOW_PID" ]; then
        kill "$EXISTING_SHADOW_PID" 2>/dev/null || true
        echo "live-shadow: stopped unmanaged process (PID $EXISTING_SHADOW_PID)"
    else
        echo "live-shadow: not running"
    fi
fi

# Start observation-only shadow worker.
nohup "$PWD/.venv/bin/python" \
    -m market_lab.live_shadow_worker_v1 \
    >> "$SHADOW_LOG_FILE" 2>&1 &

SHADOW_PID=$!
echo "$SHADOW_PID" > "$SHADOW_PID_FILE"

sleep 1

if kill -0 "$SHADOW_PID" 2>/dev/null; then
    echo "live-shadow: started (PID $SHADOW_PID)"
else
    echo "live-shadow: FAILED TO START"
    echo "Check: $SHADOW_LOG_FILE"
    exit 1
fi

echo "live-shadow: OBSERVATION ONLY (execution disabled)"
# ===== END LIVE SHADOW WORKER V1 =====

