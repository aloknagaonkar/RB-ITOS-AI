#!/usr/bin/env bash
set -euo pipefail
ROOT="$(pwd -P)"
PIDFILE="data/runtime/api.json"
[[ -f "$PIDFILE" ]] || { echo 'STOP: managed API pid file missing'; exit 1; }
API_PID="$(.venv/bin/python - <<'PYAPI'
import json,os
from pathlib import Path
p=json.loads(Path('data/runtime/api.json').read_text())
if p.get('service')!='api' or Path(p.get('project_root','')).resolve()!=Path.cwd().resolve():
 raise SystemExit('STOP: pid file does not identify this API')
pid=int(p['pid'])
cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ')
if b'market_lab.runtime api' not in cmd:
 raise SystemExit('STOP: PID command is not the managed API')
print(pid)
PYAPI
)"
BEFORE="$(cat data/live-shadow-worker.pid 2>/dev/null || true)"
kill -TERM "$API_PID"
for n in $(seq 1 50); do
  if ! kill -0 "$API_PID" 2>/dev/null; then break; fi
  sleep 0.2
done
if kill -0 "$API_PID" 2>/dev/null; then echo 'STOP: old API did not exit'; exit 1; fi
nohup .venv/bin/python -m market_lab.runtime api >> data/logs/api.log 2>> data/logs/api-error.log < /dev/null &
for n in $(seq 1 50); do
  if curl -fsS --max-time 1 http://127.0.0.1:8123/api/health >/dev/null 2>&1; then
    AFTER="$(cat data/live-shadow-worker.pid 2>/dev/null || true)"
    echo "API healthy; live shadow worker PID before=$BEFORE after=$AFTER"
    exit 0
  fi
  sleep 0.2
done
echo 'API health failed; inspect data/logs/api-error.log'; exit 1
