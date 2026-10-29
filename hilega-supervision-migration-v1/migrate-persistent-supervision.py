"""Guarded migration of preparation processes to user systemd services."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import select
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.request import build_opener, HTTPRedirectHandler

ROLES = ('api', 'worker', 'production-source-worker')
RUNNER_SHA = '9a45abca7de7cd5cfdadcaaa0d9f30130fcb96b2e6597f929f5af903e1626f4d'
TEST_SHA = '5c4fc79c544d88bb88e65b354637aef9fb815f464251ccbcace00a2c71a6ed37'

def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)

def sha(path):
    need(path.is_file() and not path.is_symlink(), 'REGULAR_FILE_REQUIRED')
    return hashlib.sha256(path.read_bytes()).hexdigest()

def call(args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    need(r.returncode == 0, 'SERVICE_MANAGER_COMMAND_FAILED')
    return r.stdout.strip()

def identity(pid, root):
    p = Path('/proc') / str(pid)
    need(p.joinpath('cwd').resolve() == root, 'PROCESS_ROOT_CHANGED')
    return int(p.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19])

def inventory(root):
    sys.path.insert(0, str(root / 'hilega-production-application-deployment'))
    from managed_processes import inspect
    return inspect(root)['active_processes']

def normalized(rows):
    return sorted((r['role'], r['pid'], r['start_ticks']) for r in rows)

def clean_database(root):
    for kind, relative, required in (
        ('application', 'data/research/hilega-production-workspace/sim.sqlite',
         ('intents', 'sim_orders', 'sim_fills', 'sim_allocation_reservations',
          'preparation_plans', 'preparation_shadow_holds', 'preparation_outbox')),
        ('adapter', 'data/research/hilega-broker-adapter-closed/adapter.sqlite',
         ('requests', 'attempts', 'receipts')),
    ):
        p = root / relative
        need(p.is_file() and not p.is_symlink(), 'DATABASE_INVALID')
        with sqlite3.connect(p.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in required + (('preparation_request_bindings',) if kind == 'application' else ()):
                if table == 'preparation_request_bindings' and table not in names:
                    continue
                need(table in names, 'DATABASE_SCHEMA_INVALID')
                need(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0,
                     'ACTIVITY_REQUIRES_REVIEW')

def paused_check(root):
    env = dict(os.environ, PYTHONPATH='backend:.')
    r = subprocess.run([str(root / '.venv/bin/python'), 'check-preparation-paused.py'],
                       cwd=root, env=env, capture_output=True, text=True, timeout=30)
    need(r.returncode == 0, 'PAUSED_SAFETY_CHECK_FAILED')
    result = json.loads(r.stdout)
    need(result['controller_mode'] == 'PAUSED' and result['execution_route'] == 'PREPARATION_ONLY',
         'UNEXPECTED_CONTROL_STATE')
    need(not any(result['activity_counts'].values()), 'APPLICATION_ACTIVITY_PRESENT')
    need(result['bridge_health'].get('healthy') is True, 'FRESH_SOURCE_REQUIRED')
    return result

def api_health():
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with build_opener(NoRedirect()).open('http://127.0.0.1:8123/api/health', timeout=3) as response:
        value = json.load(response)
    need(value.get('status') == 'ok' and value.get('execution') == 'not_enabled', 'API_HEALTH_INVALID')
    return value

def load_runner(stage):
    need(sha(stage / 'runner.py') == RUNNER_SHA, 'RUNNER_CHANGED')
    need(sha(stage / 'test_supervision.py') == TEST_SHA, 'TEST_FILE_CHANGED')
    spec = importlib.util.spec_from_file_location('staged_runner', stage / 'runner.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def validate_units(root, stage, unit_dir):
    # Match exact generated service semantics before anything is stopped.
    for role in ROLES:
        src = stage / ('hilega-' + role + '.service')
        text = src.read_text()
        need(not src.is_symlink(), 'UNIT_SYMLINK_FORBIDDEN')
        need(hashlib.sha256(text.encode()).hexdigest() == expected_unit_hash(root, stage, role),
             'STAGED_UNIT_CHANGED')
        dest = unit_dir / src.name
        need(not dest.exists() and not dest.is_symlink(), 'UNIT_ALREADY_EXISTS')
        # Also reject a unit of this name loaded from another search directory.
        r = subprocess.run(['systemctl', '--user', 'show', src.name, '-p', 'LoadState', '--value'],
                           capture_output=True, text=True, timeout=10)
        need(r.stdout.strip() == 'not-found', 'UNIT_NAME_ALREADY_MANAGED')

def expected_unit_hash(root, stage, role):
    def q(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    text = '\n'.join([
        '[Unit]', 'Description=Hilega preparation ' + role,
        'StartLimitIntervalSec=300', 'StartLimitBurst=3', '', '[Service]',
        'Type=exec', 'WorkingDirectory=' + q(root),
        'ExecStart=' + ' '.join(map(q, (root / '.venv/bin/python', stage / 'runner.py', role))),
        'Restart=on-failure', 'RestartSec=10', 'RestartPreventExitStatus=78',
        'TimeoutStopSec=30', 'KillMode=control-group', 'UMask=0077',
        'NoNewPrivileges=true', '', '[Install]', 'WantedBy=default.target', '',
    ])
    return hashlib.sha256(text.encode()).hexdigest()

def main(apply=False):
    os.umask(0o077)
    root = Path.home() / 'RB-ITOS-AI'
    stage = Path.home() / 'hilega-persistent-supervision-stage-v1'
    runner = load_runner(stage)
    config_path = stage / 'config-private.json'
    config_sha = sha(config_path)
    config = json.loads(config_path.read_text())
    need(config['root'] == str(root), 'ROOT_MISMATCH')
    need(sha(root / '.env') == config['env_sha256'], 'ENV_CHANGED')
    for role in ROLES:
        runner.validate_item(role, config['startup'][role], root)
    runner.paused(root)
    state_path = stage / 'migration.json'
    approval = stage / 'MIGRATION_APPROVED.json'
    need(not state_path.exists() and not state_path.is_symlink(), 'MIGRATION_ALREADY_ATTEMPTED')
    need(not approval.exists() and not approval.is_symlink(), 'ACTIVATION_ALREADY_PRESENT')
    unit_dir = Path.home() / '.config/systemd/user'
    validate_units(root, stage, unit_dir)
    call(['systemctl', '--user', 'show-environment'])  # Check only; never print its contents.
    linger = call(['loginctl', 'show-user', pwd.getpwuid(os.getuid()).pw_name, '-p', 'Linger', '--value'])
    before = inventory(root)
    need(len(before) == 3 and {r['role'] for r in before} == set(ROLES), 'PROCESS_INVENTORY_INVALID')
    checked = paused_check(root)
    clean_database(root)
    if not apply:
        print(json.dumps(dict(status='SUPERVISION_MIGRATION_CHECKS_PASS',
            linger_enabled=linger == 'yes', apply_ready=linger == 'yes',
            processes=before, services_installed=False, processes_signalled=False,
            controller_mode='PAUSED', production_execution_enabled=False), indent=2))
        return
    need(linger == 'yes', 'ENABLE_USER_LINGER_FIRST')
    handles = []
    state = dict(phase='PREPARED', previous_processes=before, units_installed=[],
                 production_execution_enabled=False)
    lock = (stage / 'migration.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        need(not state_path.exists(), 'MIGRATION_ALREADY_ATTEMPTED')
        need(normalized(inventory(root)) == normalized(before), 'PROCESSES_CHANGED')
        for r in before:
            fd = os.pidfd_open(r['pid'])
            handles.append((r['role'], fd))
            need(identity(r['pid'], root) == r['start_ticks'], 'PROCESS_IDENTITY_CHANGED')
        paused_check(root); clean_database(root)
        need(sha(root / '.env') == config['env_sha256'] and sha(config_path) == config_sha,
             'CONFIGURATION_CHANGED')
        state['previous_maintenance'] = json.loads((root / 'backups/hilega-preparation-activation-cvtlkibq/maintenance.json').read_text())
        runner.atomic(state_path, state)
        state['phase'] = 'STOPPING'; runner.atomic(state_path, state)
        for role in ('production-source-worker', 'worker', 'api'):
            signal.pidfd_send_signal(dict(handles)[role], signal.SIGTERM)
        poller = select.poll()
        for _, fd in handles:
            poller.register(fd, select.POLLIN)
        waiting = {fd for _, fd in handles}; deadline = time.monotonic() + 30
        while waiting and time.monotonic() < deadline:
            waiting -= {fd for fd, event in poller.poll(500) if event & select.POLLIN}
        need(not waiting, 'PROCESS_STOP_TIMEOUT_NO_FORCE_KILL')
        need(not inventory(root), 'UNEXPECTED_PROCESS_AFTER_STOP')
        runner.paused(root); clean_database(root)
        need(sha(root / '.env') == config['env_sha256'], 'ENV_CHANGED_AFTER_STOP')
        unit_dir.mkdir(parents=True, exist_ok=True)
        state['phase'] = 'INSTALLING'; runner.atomic(state_path, state)
        for role in ROLES:
            name = 'hilega-' + role + '.service'
            dest = unit_dir / name
            with dest.open('x') as stream:
                os.chmod(dest, 0o600)
                stream.write((stage / name).read_text())
                stream.flush(); os.fsync(stream.fileno())
            state['units_installed'].append(name); runner.atomic(state_path, state)
        runner.atomic(approval, dict(config_sha256=config_sha, runner_sha256=RUNNER_SHA))
        call(['systemctl', '--user', 'daemon-reload'])
        units = ['hilega-' + role + '.service' for role in ROLES]
        state['phase'] = 'STARTING_SUPERVISED'; runner.atomic(state_path, state)
        # Enable only after health verification so a failed migration cannot
        # silently become an approved boot configuration.
        for name in ('hilega-worker.service', 'hilega-api.service', 'hilega-production-source-worker.service'):
            call(['systemctl', '--user', 'start', name])
        deadline = time.monotonic() + 50
        last_error = None
        while time.monotonic() < deadline:
            try:
                checked = paused_check(root)
                health = api_health()
                rows = inventory(root)
                need(len(rows) == 3, 'RESTARTED_INVENTORY_INVALID')
                for row in rows:
                    name = 'hilega-' + row['role'] + '.service'
                    need(call(['systemctl', '--user', 'is-active', name]) == 'active', 'UNIT_NOT_ACTIVE')
                    pid = int(call(['systemctl', '--user', 'show', name, '-p', 'MainPID', '--value']))
                    need(pid == row['pid'], 'SYSTEMD_PID_MISMATCH')
                    process_env = dict(x.split(b'=', 1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in x)
                    need(all(process_env.get(k.encode()) == v.encode() for k, v in runner.REQUIRED.items()),
                         'RESTARTED_CONFIGURATION_MISMATCH')
                clean_database(root)
                break
            except Exception as exc:
                last_error = type(exc).__name__
                time.sleep(1)
        else:
            raise RuntimeError('POST_MIGRATION_VERIFICATION_FAILED_' + str(last_error))
        need(sha(root / '.env') == config['env_sha256'], 'ENV_CHANGED_DURING_MIGRATION')
        call(['systemctl', '--user', 'enable', *units])
        state.update(phase='SUPERVISION_ACTIVE_PAUSED_VERIFIED', processes=rows,
                     bridge_health=checked['bridge_health'], activity_counts=checked['activity_counts'],
                     api_health=health, execution_route='PREPARATION_ONLY', controller_mode='PAUSED')
        runner.atomic(state_path, state)
        print(json.dumps(state, indent=2))
    except BaseException as exc:
        if state_path.exists():
            state['failure_after_phase'] = state['phase']
            state['phase'] = 'REQUIRES_REVIEW_NO_AUTOMATIC_RETRY'
            state['error_type'] = type(exc).__name__
            runner.atomic(state_path, state)
        raise
    finally:
        for _, fd in handles:
            os.close(fd)
        lock.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'apply'))
    args = parser.parse_args()
    try:
        main(args.action == 'apply')
    except BaseException as exc:
        reason = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        print(json.dumps(dict(status='STOPPED_FOR_REVIEW', reason=reason,
              automatic_retry=False, production_execution_enabled=False)))
        raise SystemExit(1)
