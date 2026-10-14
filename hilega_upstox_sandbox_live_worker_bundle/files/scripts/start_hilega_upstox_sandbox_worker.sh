#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PID_FILE="data/hilega-upstox-sandbox-worker.pid"
LOG_FILE="data/logs/hilega-upstox-sandbox-worker.log"
mkdir -p data/logs

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Hilega sandbox worker already running (PID $(cat "$PID_FILE"))"
  exit 0
fi

nohup env PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" \
  "$ROOT/.venv/bin/python" -m market_lab.hilega_upstox_sandbox_live_worker_v1 \
  --serve --interval-seconds 10 \
  >> "$LOG_FILE" 2>&1 < /dev/null &

echo "$!" > "$PID_FILE"
echo "Hilega sandbox worker started (PID $!)"
