#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p data/logs
if [ -f data/operational-readiness.pid ]; then
    PID="$(cat data/operational-readiness.pid)"
    if kill -0 "$PID" 2>/dev/null && [[ "$(tr '\0' ' ' < "/proc/$PID/cmdline")" == *market_lab.operational_readiness_v1* ]]; then
        echo "readiness-monitor: already running (PID $PID)"; exit 0
    fi
fi
nohup env PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" "$ROOT/.venv/bin/python" -m market_lab.operational_readiness_v1 >> data/logs/operational-readiness.log 2>&1 < /dev/null &
PID=$!
echo "$PID" > data/operational-readiness.pid
sleep 0.5
kill -0 "$PID"
echo "readiness-monitor: started (PID $PID); UI notifications only"
