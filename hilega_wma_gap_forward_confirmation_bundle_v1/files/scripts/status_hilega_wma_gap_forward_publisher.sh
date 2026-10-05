#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/data/hilega-wma-gap-forward-publisher.pid"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Hilega WMA-gap forward publisher: RUNNING (PID $(cat "$PID_FILE"))"
else
  echo "Hilega WMA-gap forward publisher: STOPPED"
fi
REPORT="$ROOT/data/historical-evidence/hilega-wma-gap-forward-confirmation-v1/report.json"
if [ -f "$REPORT" ]; then
  "$ROOT/.venv/bin/python" - "$REPORT" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
print({"forward_sessions":x.get("forward_sessions"),"selected_dates":x.get("selected_dates"),"signals":x.get("signals"),"candidate_points":x.get("candidate_points"),"frozen_parent":x.get("frozen_parent")})
PY
else
  echo "Forward report: not published yet"
fi
