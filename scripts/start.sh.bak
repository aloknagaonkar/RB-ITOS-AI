#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
RUNTIME_DIR="$ROOT/data/runtime"
LOG_DIR="$ROOT/data/logs"
HEALTH_URL="http://127.0.0.1:8123/api/health"

cd "$ROOT"

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python environment missing: $PYTHON"
    exit 1
fi

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

if [[ ! -f "$ROOT/.env" ]]; then
    echo "ERROR: .env not found at $ROOT/.env"
    exit 1
fi

if ! grep -qE '^UPSTOX_ACCESS_TOKEN=.+' "$ROOT/.env"; then
    echo "ERROR: UPSTOX_ACCESS_TOKEN is missing or empty in .env"
    exit 1
fi

service_running() {
    local service="$1"
    local pidfile="$RUNTIME_DIR/$service.json"

    [[ -f "$pidfile" ]] || return 1

    local pid
    pid="$("$PYTHON" - "$pidfile" "$ROOT" <<'PY'
import json, os, sys
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
)" || return 1

    kill -0 "$pid" 2>/dev/null || return 1
    printf '%s' "$pid"
}

start_service() {
    local service="$1"

    local pid=""
    if pid="$(service_running "$service")"; then
        echo "$service: already running (PID $pid)"
        return
    fi

    rm -f "$RUNTIME_DIR/$service.json"

    nohup "$PYTHON" -m market_lab.runtime "$service"         >> "$LOG_DIR/$service.log"         2>> "$LOG_DIR/$service-error.log"         < /dev/null &

    local deadline=$((SECONDS + 10))
    while (( SECONDS < deadline )); do
        sleep 0.2
        if pid="$(service_running "$service")"; then
            if [[ "$service" == "worker" ]]; then
                sleep 0.75
                if ! pid="$(service_running "$service")"; then
                    echo "ERROR: worker exited during startup."
                    echo "Check data/logs/worker-error.log"
                    exit 1
                fi
            fi
            echo "$service: started (PID $pid)"
            return
        fi
    done

    echo "ERROR: $service failed to start."
    echo "Check data/logs/$service-error.log"
    exit 1
}

start_service "api"
start_service "worker"

deadline=$((SECONDS + 10))
while (( SECONDS < deadline )); do
    if curl -fsS --max-time 1 "$HEALTH_URL" >/dev/null 2>&1; then
        echo "dashboard: AVAILABLE at http://127.0.0.1:8123"
        exit 0
    fi
    sleep 0.25
done

echo "ERROR: API process started but health check failed."
echo "Check data/logs/api-error.log"
exit 1
