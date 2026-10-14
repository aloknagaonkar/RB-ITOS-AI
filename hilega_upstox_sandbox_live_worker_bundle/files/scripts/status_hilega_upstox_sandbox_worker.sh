#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PID_FILE="data/hilega-upstox-sandbox-worker.pid"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Hilega sandbox worker: RUNNING (PID $(cat "$PID_FILE"))"
else
  echo "Hilega sandbox worker: STOPPED"
fi
PYTHONPATH=backend:. .venv/bin/python -m market_lab.hilega_upstox_sandbox_live_worker_v1 --status
