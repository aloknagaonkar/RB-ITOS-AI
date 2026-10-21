#!/usr/bin/env bash
set -euo pipefail
BEFORE="$(cat data/live-shadow-worker.pid 2>/dev/null || true)"
API_PID="$(.venv/bin/python - <<'PY'
import json,os
from pathlib import Path
p=Path('data/runtime/api.json')
if not p.is_file():print(0);raise SystemExit
d=json.loads(p.read_text());pid=int(d['pid'])
if d.get('service')!='api' or Path(d.get('project_root','')).resolve()!=Path.cwd().resolve():raise SystemExit('STOP: API identity mismatch')
try:
    cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ')
    cwd=Path(f'/proc/{pid}/cwd').resolve(strict=True)
except FileNotFoundError:print(0);raise SystemExit
if b'market_lab.runtime api' not in cmd or cwd!=Path.cwd().resolve():raise SystemExit('STOP: managed PID is not this API')
print(pid)
PY
)"
if [[ "$API_PID" != "0" ]]; then
  kill -TERM "$API_PID" 2>/dev/null || true
  for n in $(seq 1 50); do
    if ! kill -0 "$API_PID" 2>/dev/null; then break; fi
    sleep 0.2
  done
  if kill -0 "$API_PID" 2>/dev/null; then echo 'STOP: API did not stop'; exit 1; fi
fi
.venv/bin/python - <<'PY'
import socket
with socket.socket() as s:
    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:s.bind(('127.0.0.1',8123))
    except OSError:raise SystemExit('STOP: port 8123 is already occupied; not starting duplicate API')
PY
mkdir -p data/logs
nohup .venv/bin/python -m market_lab.runtime api >>data/logs/api.log 2>>data/logs/api-error.log </dev/null &
for n in $(seq 1 50); do
  if curl -fsS --max-time 1 http://127.0.0.1:8123/api/health >/dev/null 2>&1; then
    AFTER="$(cat data/live-shadow-worker.pid 2>/dev/null || true)"
    echo "API healthy; strategy worker PID before=$BEFORE after=$AFTER"
    [[ "$BEFORE" == "$AFTER" ]] || { echo 'STOP: strategy worker identity changed independently'; exit 1; }
    exit 0
  fi
  sleep 0.2
done
echo 'API health failed; inspect data/logs/api-error.log'; exit 1
