"""Prepare private user-service files only. Does not install or start services."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shlex
import sys

ROLES = ('api', 'worker', 'production-source-worker')
REQUIRED = {
    'HILEGA_PRODUCTION_EXECUTION_ROUTE': 'PREPARATION_ONLY',
    'HILEGA_PRODUCTION_WORKSPACE_MODE': 'SIMULATION_ONLY',
    'HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED': '1',
    'HILEGA_PREPARATION_CAPTURE_ON_SIGNAL': '1',
}
RUNNER = r'''"""Private staged supervisor entry point; activation requires a separate migration."""
import fcntl
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROLES = ('api', 'worker', 'production-source-worker')
REQUIRED = {
    'HILEGA_PRODUCTION_EXECUTION_ROUTE': 'PREPARATION_ONLY',
    'HILEGA_PRODUCTION_WORKSPACE_MODE': 'SIMULATION_ONLY',
    'HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED': '1',
    'HILEGA_PREPARATION_CAPTURE_ON_SIGNAL': '1',
}

def need(ok, reason):
    if not ok:
        raise ValueError(reason)

def regular(path):
    need(path.is_file() and not path.is_symlink(), 'REGULAR_FILE_REQUIRED')
    return path.read_bytes()

def digest(path):
    return hashlib.sha256(regular(path)).hexdigest()

def validate_item(role, item, root):
    need(role in ROLES, 'ROLE_INVALID')
    argv = item['argv']
    need(isinstance(argv, list) and all(isinstance(a, str) for a in argv), 'ARGV_INVALID')
    need(argv and argv[0] == str(root / '.venv/bin/python'), 'INTERPRETER_INVALID')
    if role in ('api', 'worker'):
        need(argv[1:4] == ['-m', 'market_lab.runtime', role], 'RUNTIME_COMMAND_INVALID')
    else:
        script = str(root / 'scripts/hilega_production_simulator_bridge.py')
        need(argv[1:3] == ['-u', script] and '--watch' in argv, 'SOURCE_COMMAND_INVALID')
        need('--env-file' in argv and '--source' in argv, 'SOURCE_ARGUMENTS_REQUIRED')
        need('--synthetic-fills' not in argv, 'SYNTHETIC_FILLS_FORBIDDEN')
    need(all(item['env'].get(k) == v for k, v in REQUIRED.items()), 'CONFIGURATION_INVALID')
    need(len(item['logs']) == 2, 'LOGS_INVALID')
    for name in item['logs']:
        p = Path(name)
        need(p.is_absolute() and p.resolve().is_relative_to(root / 'data'), 'LOG_OUTSIDE_DATA')
        need(not p.is_symlink() and p.parent.is_dir(), 'LOG_PATH_INVALID')

def paused(root):
    path = root / 'data/research/hilega-production-workspace/sim.sqlite'
    need(path.is_file() and not path.is_symlink(), 'DATABASE_INVALID')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        control = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        route = json.loads(db.execute('SELECT data FROM preparation_route WHERE id=1').fetchone()[0])
        need(control['mode'] == 'PAUSED', 'CONTROLLER_NOT_PAUSED')
        need(route['route'] == 'PREPARATION_ONLY', 'ROUTE_INVALID')

def atomic(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def main():
    folder = Path(__file__).resolve().parent
    config = json.loads(regular(folder / 'config-private.json'))
    approval = folder / 'MIGRATION_APPROVED.json'
    need(approval.is_file() and not approval.is_symlink(), 'STAGED_ONLY_MIGRATION_REQUIRED')
    permit = json.loads(regular(approval))
    need(permit.get('config_sha256') == digest(folder / 'config-private.json'), 'ACTIVATION_MISMATCH')
    need(permit.get('runner_sha256') == digest(Path(__file__)), 'RUNNER_CHANGED')
    root = Path(config['root'])
    need(Path.cwd().resolve() == root, 'WORKING_DIRECTORY_INVALID')
    need(digest(root / '.env') == config['env_sha256'], 'ENV_CHANGED_REVIEW_REQUIRED')
    role = sys.argv[1]
    item = config['startup'][role]
    validate_item(role, item, root)
    # Serialize all launches and metadata updates. Existing managed processes
    # are also checked; they need not hold this new lock to be detected.
    with (folder / 'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        paused(root)
        sys.path.insert(0, str(root / 'hilega-production-application-deployment'))
        from managed_processes import inspect
        active = inspect(root)['active_processes']
        need(not any(r['role'] == role for r in active), 'ROLE_ALREADY_RUNNING')
        pid = os.getpid()
        ticks = int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19])
        if role == 'production-source-worker':
            atomic(root / 'data/runtime/hilega-preparation-source.json', dict(
                pid=pid, start_ticks=ticks, root=str(root), role=role))
        else:
            atomic(root / ('data/runtime/' + role + '.json'), dict(
                service=role, pid=pid, started_at=datetime.now(timezone.utc).isoformat(),
                project_root=str(root)))
        metadata = root / 'backups/hilega-preparation-activation-cvtlkibq/maintenance.json'
        record = json.loads(regular(metadata))
        record['children']['source' if role == 'production-source-worker' else role] = pid
        atomic(metadata, record)
        # Lock remains held through exec and closes when the target begins.
        # Runtime API/worker entry points write their own PID records.
        for fd, name in ((1, item['logs'][0]), (2, item['logs'][1])):
            out = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            os.dup2(out, fd)
            if out not in (1, 2):
                os.close(out)
        os.execve(item['argv'][0], item['argv'], item['env'])

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never print argv, environments or raw exception messages.
        reason = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(json.dumps(dict(status='SUPERVISION_START_BLOCKED', reason=reason)), file=sys.stderr)
        raise SystemExit(78)
'''

TESTS = r'''import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

folder = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('runner', folder / 'runner.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data/logs').mkdir(parents=True)
        self.item = dict(argv=[str(self.root / '.venv/bin/python'), '-m', 'market_lab.runtime', 'api'],
                         env=dict(r.REQUIRED), logs=[str(self.root / 'data/logs/a.log')]*2)
    def test_valid_api(self):
        r.validate_item('api', self.item, self.root)
    def test_valid_worker(self):
        self.item['argv'][-1] = 'worker'
        r.validate_item('worker', self.item, self.root)
    def test_valid_source(self):
        self.item['argv'] = [str(self.root / '.venv/bin/python'), '-u', str(self.root / 'scripts/hilega_production_simulator_bridge.py'), '--watch', '--env-file', '.env', '--source', 'journal']
        r.validate_item('production-source-worker', self.item, self.root)
    def test_live_route_rejected(self):
        self.item['env']['HILEGA_PRODUCTION_EXECUTION_ROUTE'] = 'LIVE'
        with self.assertRaisesRegex(ValueError, 'CONFIGURATION_INVALID'):
            r.validate_item('api', self.item, self.root)
    def test_disabled_binding_rejected(self):
        self.item['env']['HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED'] = '0'
        with self.assertRaises(ValueError):
            r.validate_item('api', self.item, self.root)
    def test_wrong_interpreter_rejected(self):
        self.item['argv'][0] = '/usr/bin/python'
        with self.assertRaisesRegex(ValueError, 'INTERPRETER_INVALID'):
            r.validate_item('api', self.item, self.root)
    def test_wrong_role_rejected(self):
        with self.assertRaises(ValueError):
            r.validate_item('worker', self.item, self.root)
    def test_external_log_rejected(self):
        self.item['logs'][0] = '/tmp/elsewhere'
        with self.assertRaisesRegex(ValueError, 'LOG_OUTSIDE_DATA'):
            r.validate_item('api', self.item, self.root)
    def test_symlink_log_rejected(self):
        log = Path(self.item['logs'][0]); log.symlink_to(self.root / 'data/logs/other')
        with self.assertRaises(ValueError):
            r.validate_item('api', self.item, self.root)
    def test_atomic_metadata(self):
        p = self.root / 'record.json'
        r.atomic(p, {'pid': 123})
        self.assertEqual(r.json.loads(p.read_text()), {'pid': 123})
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
    def test_activation_missing_blocks_before_execution(self):
        with patch.object(r, 'regular', return_value=b'{}'), patch.object(r.os, 'execve') as execute:
            with self.assertRaisesRegex(ValueError, 'STAGED_ONLY_MIGRATION_REQUIRED'):
                r.main()
            execute.assert_not_called()
    def test_units_fail_closed(self):
        for role in r.ROLES:
            unit = (folder / ('hilega-' + role + '.service')).read_text()
            self.assertIn('RestartPreventExitStatus=78', unit)
            self.assertIn('Restart=on-failure', unit)
            self.assertIn('StartLimitBurst=3', unit)
            self.assertNotIn('resume', unit.lower())

if __name__ == '__main__':
    unittest.main()
'''

def unit(root, folder, role):
    # systemd command-line quoting is not shell quoting.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    return '\n'.join([
        '[Unit]', 'Description=Hilega preparation ' + role,
        'StartLimitIntervalSec=300', 'StartLimitBurst=3', '', '[Service]',
        'Type=exec', 'WorkingDirectory=' + quote(root),
        'ExecStart=' + ' '.join(map(quote, (root / '.venv/bin/python', folder / 'runner.py', role))),
        'Restart=on-failure', 'RestartSec=10', 'RestartPreventExitStatus=78',
        'TimeoutStopSec=30', 'KillMode=control-group', 'UMask=0077',
        'NoNewPrivileges=true', '', '[Install]', 'WantedBy=default.target', '',
    ])

def prepare(repo, folder):
    repo = repo.resolve()
    saved_path = repo / 'backups/hilega-admission-wait-maintenance-5zpodt29/startup-private.json'
    plan_path = saved_path.parent / 'plan.json'
    def sha(p):
        if not p.is_file() or p.is_symlink():
            raise ValueError('REGULAR_FILE_REQUIRED')
        return hashlib.sha256(p.read_bytes()).hexdigest()
    if sha(plan_path) != 'be2b037252ec707691e1e335c6792f5079daf2340b425483f413c596ffeee562':
        raise ValueError('PLAN_CHANGED')
    plan = json.loads(plan_path.read_text())
    if sha(saved_path) != plan['startup_sha256'] or sha(repo / '.env') != plan['env_sha256']:
        raise ValueError('SAVED_STARTUP_OR_ENV_CHANGED')
    saved = json.loads(saved_path.read_text())
    from dotenv import dotenv_values
    file_env = {k: v for k, v in dotenv_values(repo / '.env').items() if v is not None}
    for role in ROLES:
        saved[role]['env'] = {**file_env, **saved[role]['env']}
    namespace = {'__name__': 'not_main'}
    exec(compile(RUNNER, 'runner.py', 'exec'), namespace)
    for role in ROLES:
        namespace['validate_item'](role, saved[role], repo)
    folder.mkdir(mode=0o700)  # Refuse to overwrite a previous stage.
    contents = {'runner.py': RUNNER, 'test_supervision.py': TESTS,
                'config-private.json': json.dumps(dict(root=str(repo), env_sha256=sha(repo / '.env'), startup=saved), indent=2)}
    for role in ROLES:
        contents['hilega-' + role + '.service'] = unit(repo, folder, role)
    for name, content in contents.items():
        p = folder / name
        with p.open('x') as stream:
            os.chmod(p, 0o600)
            stream.write(content)
        if p.suffix == '.py':
            py_compile.compile(str(p), doraise=True)
    print(json.dumps(dict(status='SUPERVISION_STAGED_NOT_INSTALLED', stage=str(folder),
                         tests_executed=False, processes_signalled=False,
                         services_installed=False, activation_included=False,
                         contains_private_credentials=True), indent=2))

if __name__ == '__main__':
    os.umask(0o077)
    try:
        prepare(Path.home() / 'RB-ITOS-AI', Path.home() / 'hilega-persistent-supervision-stage-v1')
    except Exception as exc:
        print(json.dumps(dict(status='STAGING_BLOCKED', error_type=type(exc).__name__)))
        raise SystemExit(1)
