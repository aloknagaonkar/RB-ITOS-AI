#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/data/hilega-wma-gap-forward-publisher.pid"
LOG_FILE="$ROOT/data/logs/hilega-wma-gap-forward-publisher.log"
mkdir -p "$ROOT/data/logs"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Hilega WMA-gap forward publisher already running (PID $(cat "$PID_FILE"))"
  exit 0
fi
nohup env PYTHONPATH="$ROOT/backend:$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$ROOT/.venv/bin/python" "$ROOT/scripts/hilega_wma_gap_forward_publisher.py" \
  --serve --interval-seconds 900 >> "$LOG_FILE" 2>&1 < /dev/null &
echo $! > "$PID_FILE"
sleep 0.5
kill -0 "$(cat "$PID_FILE")" 2>/dev/null || { echo "publisher failed; check $LOG_FILE"; exit 1; }
echo "Hilega WMA-gap forward publisher started (PID $(cat "$PID_FILE"))"
