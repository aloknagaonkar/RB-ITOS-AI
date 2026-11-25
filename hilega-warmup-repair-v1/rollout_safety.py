"""Deploy validated 3m observation rules to the explicitly identified user services."""
import argparse
import ast
from datetime import datetime, timezone
import difflib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import companion_bindings
VERSION = 'bullish-gap2-full-wma2-3.0.0-3m-two-of-three-session-close'
RESTART_ORDER = ['hilega-api.service', 'hilega-lifecycle-reference.service', 'hilega-observation-analytics.service', 'hilega-observation-readiness.service']
PROTECTED = ['hilega-worker.service', 'hilega-production-source-worker.service']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + '\n')

def systemctl(*args, check=True):
    p = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=60)
    if check and p.returncode:
        raise ValueError('SYSTEMCTL_FAILED:' + args[0] + ':' + args[-1])
    return p

def service_state(unit):
    p = systemctl('show', unit, '--property=ActiveState,SubState,WorkingDirectory,MainPID,NRestarts', check=False)
    return dict((line.split('=', 1) for line in p.stdout.splitlines() if '=' in line))

def api_status(base):
    with urlopen(base.rstrip('/') + '/api/live-shadow/hilega-directional/status?fast=true', timeout=15) as response:
        body = json.load(response)
    if body.get('selected_live_shadow_strategy') != 'HILEGA_V2_ALIGNMENT_DUAL_EXIT':
        raise ValueError('WRONG_ACTIVE_API_STRATEGY')
    if body.get('observation_only') is not True or body.get('execution_enabled') is not False:
        raise ValueError('OBSERVATION_MODE_REQUIRED')
    return body

def sandbox_clear(repo):
    code = 'import json\nfrom pathlib import Path\nfrom market_lab.hilega_sandbox_fill_ledger_v1 import open_legs,pending_orders\np=Path("data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl")\nrows=[json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.is_file() else []\ndone={r.get("request_id") for r in rows if r.get("status") in {"ACCEPTED","REQUEST_RESOLVED_NO_FILL"}}\nuncertain=[r for r in rows if r.get("status")=="REQUESTED" and r.get("request_id") not in done]\nprint(json.dumps(dict(open_legs=len(open_legs(rows)),pending_orders=len(pending_orders(rows)),uncertain_requests=len(uncertain))))\n'
    env = dict(os.environ, PYTHONPATH=str(repo / 'backend'), PYTHONDONTWRITEBYTECODE='1')
    p = subprocess.run([sys.executable, '-B', '-c', code], cwd=repo, env=env, capture_output=True, text=True)
    if p.returncode:
        raise ValueError('LOCAL_LEDGER_CHECK_FAILED')
    result = json.loads(p.stdout)
    if any(result.values()):
        raise ValueError('OPEN_OR_UNCERTAIN_SANDBOX_STATE:' + json.dumps(result))
    return result

def no_execution_workers(repo):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            args = (proc / 'cmdline').read_bytes().decode().split('\x00')
            if (proc / 'cwd').resolve() != repo:
                continue
            if any((any((tag in arg for tag in ('hilega_upstox_sandbox_basket', 'hilega_upstox_sandbox_live_worker', 'hilega_production_source_worker', 'market_lab.worker'))) for arg in args)):
                raise ValueError('EXECUTION_WORKER_ACTIVE_PID:' + proc.name)
        except (OSError, UnicodeError):
            continue

def stop_units(units):
    for unit in reversed(units):
        systemctl('stop', unit)
    for unit in units:
        state = service_state(unit)
        if state.get('ActiveState') not in ('inactive', 'failed') or state.get('MainPID') not in ('0', None):
            raise ValueError('SERVICE_NOT_STOPPED:' + unit)

def start_units(units):
    for unit in units:
        systemctl('start', unit)

def tail_bootstrap(repo, started):
    path = repo / 'data/live-observation/hilega-directional-v1/step-audit.jsonl'
    if not path.is_file():
        return False
    with path.open('rb') as stream:
        size = path.stat().st_size
        offset = max(0, size - 4 * 1024 * 1024)
        stream.seek(offset)
        if offset:
            stream.readline()
        lines = stream.read().decode(errors='replace').splitlines()
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        p = row.get('payload') or {}
        if row.get('stage') == 'DIRECTIONAL_LIVE_BOOTSTRAP' and row.get('status') == 'PASS' and (p.get('strategy_version') == VERSION):
            stamp = datetime.fromisoformat(row['event_time'])
            if stamp >= started:
                return True
    return False

def verify_running(args, context, started):
    deadline = time.monotonic() + args.startup_timeout
    while time.monotonic() < deadline:
        states = {u: service_state(u) for u in context['active']}
        failed = [unit for unit, state in states.items() if state.get('ActiveState') == 'failed']
        if failed:
            raise ValueError('SERVICE_START_FAILED:' + ','.join(failed))
        try:
            api = api_status(args.api_url)
            correct = api.get('strategy_version') == VERSION
            if all((s.get('ActiveState') == 'active' for s in states.values())) and correct and tail_bootstrap(context['repo'], started):
                health = context['repo'] / 'data/live-observation/shadow-worker-health.json'
                h = json.loads(health.read_text()) if health.is_file() else {}
                stamp = datetime.fromisoformat(h['timestamp']) if h.get('timestamp') else None
                if stamp and stamp >= started and ((h.get('components') or {}).get('hilega') == 'OK'):
                    return states
        except (OSError, ValueError, KeyError):
            pass
        print('Waiting for API version and fresh 3m worker bootstrap...', flush=True)
        time.sleep(5)
    raise ValueError('FRESH_3M_BOOTSTRAP_NOT_CONFIRMED_WITHIN_TIMEOUT')
