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

service_status "api"
service_status "worker"

if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    execution="$(curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("execution","unknown"))' 2>/dev/null || echo unknown)"
    echo "dashboard: AVAILABLE at http://127.0.0.1:8123 (execution: $execution)"
else
    echo "dashboard: UNAVAILABLE at http://127.0.0.1:8123"
fi
