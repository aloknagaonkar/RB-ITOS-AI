#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
RUNTIME_DIR="$ROOT/data/runtime"
HEALTH_URL="http://127.0.0.1:8123/api/health"

cd "$ROOT"

service_status() {
    local service="$1"
    local pidfile="$RUNTIME_DIR/$service.json"

    if [[ ! -f "$pidfile" ]]; then
        echo "$service: STOPPED (no pid file)"
        return
    fi

    local pid
    pid="$("$PYTHON" - "$pidfile" "$ROOT" <<'PY'
import json, sys
from pathlib import Path

pidfile = Path(sys.argv[1])
root = str(Path(sys.argv[2]).resolve())
try:
    data = json.loads(pidfile.read_text(encoding="utf-8"))
    if str(Path(data["project_root"]).resolve()) != root:
        raise SystemExit(1)
    print(int(data["pid"]))
except Exception:
    raise SystemExit(1)
PY
)" || {
        echo "$service: STOPPED (invalid pid file)"
        return
    }

    if kill -0 "$pid" 2>/dev/null; then
        echo "$service: RUNNING (PID $pid)"
    else
        echo "$service: STOPPED (process exited)"
    fi
}

if "$PYTHON" "$ROOT/scripts/hilega_supervised_control.py" mode; then
    "$PYTHON" "$ROOT/scripts/hilega_supervised_control.py" status
else
    supervision_rc=$?
    if [[ "$supervision_rc" -ne 10 ]]; then
        echo "ERROR: supervision requires review; legacy launch/stop blocked."
        exit "$supervision_rc"
    fi
service_status "api"
service_status "worker"
fi

PUBLISHER_PID_FILE="$ROOT/data/midpoint-historical-publisher.pid"
if [[ -f "$PUBLISHER_PID_FILE" ]]; then
    publisher_pid="$(cat "$PUBLISHER_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$publisher_pid" ]] && kill -0 "$publisher_pid" 2>/dev/null; then
        echo "midpoint-history: RUNNING (PID $publisher_pid)"
    else
        echo "midpoint-history: STOPPED (stale pid file)"
    fi
else
    echo "midpoint-history: STOPPED (no pid file)"
fi

if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    execution="$(curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("execution","unknown"))' 2>/dev/null || echo unknown)"
    echo "dashboard: AVAILABLE at http://127.0.0.1:8123 (execution: $execution)"
else
    echo "dashboard: UNAVAILABLE at http://127.0.0.1:8123"
fi

if [ -f data/operational-readiness.pid ] && kill -0 "$(cat data/operational-readiness.pid)" 2>/dev/null; then
    echo "readiness-monitor: RUNNING (UI-only)"
else
    echo "readiness-monitor: STOPPED"
fi

# Independent observation service status.
bash "$ROOT/scripts/status_hilega_vwap_collector.sh" || echo "VWAP collector: status unavailable"

bash "$ROOT/scripts/status_hilega_policy_observer.sh" || echo "Policy observer: status warning"

# Supervised analytics and readiness process status.
systemctl --user show \
  hilega-observation-analytics.service \
  hilega-observation-readiness.service \
  -p Id -p ActiveState -p SubState -p MainPID -p Result
