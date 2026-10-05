#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/data/hilega-wma-gap-forward-publisher.pid"
if [ ! -f "$PID_FILE" ]; then echo "Hilega WMA-gap forward publisher: STOPPED"; exit 0; fi
PID="$(cat "$PID_FILE")"
kill "$PID" 2>/dev/null || true
for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.25; done
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Hilega WMA-gap forward publisher stopped"
