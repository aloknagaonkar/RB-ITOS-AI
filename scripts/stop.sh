#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
RUNTIME_DIR="$ROOT/data/runtime"

cd "$ROOT"

read_pid() {
    local service="$1"
    local pidfile="$RUNTIME_DIR/$service.json"

    [[ -f "$pidfile" ]] || return 1

    "$PYTHON" - "$pidfile" "$ROOT" <<'PY'
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
}

stop_service() {
    local service="$1"
    local pidfile="$RUNTIME_DIR/$service.json"

    if [[ ! -f "$pidfile" ]]; then
        echo "$service: not running (no pid file)"
        return
    fi

    local pid=""
    if ! pid="$(read_pid "$service")"; then
        echo "$service: not running (invalid pid file)"
        rm -f "$pidfile"
        return
    fi

    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"

        local deadline=$((SECONDS + 10))
        while (( SECONDS < deadline )); do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.2
        done

        if kill -0 "$pid" 2>/dev/null; then
            echo "$service: graceful stop timed out; forcing PID $pid"
            kill -9 "$pid" 2>/dev/null || true
        fi

        echo "$service: stopped (PID $pid)"
    else
        echo "$service: not running (process exited)"
    fi

    rm -f "$pidfile"
}

stop_service "worker"
stop_service "api"
