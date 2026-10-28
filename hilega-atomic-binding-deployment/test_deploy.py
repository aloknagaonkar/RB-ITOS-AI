import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest
spec = importlib.util.spec_from_file_location('auto_limit_deployment', Path(__file__).with_name('deploy.py'))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))

@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    monkeypatch.setattr(tool, 'ROOT', root)
    monkeypatch.setattr(tool, 'stopped', lambda: None)
    package = root / 'hilega-atomic-binding-release-v1'
    backup = (root / tool.PLAN_REL).parent
    before, files = ({}, {})
    for i, name in enumerate(sorted(tool.PAYLOAD)):
        source = package / 'files' / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('new-' + str(i))
        files[name] = sha(source)
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if i != 3:
            target.write_text('old-' + str(i))
        before[name] = sha(target) if target.exists() else None
    put(package / 'validation.json', {'status': 'PASS', 'pytest_exit_code': 0})
    put(package / 'stage-manifest.json', {'synthetic': True})
    release = dict(files=files, target_baseline=before, dependencies={}, validation_sha256=sha(package / 'validation.json'), stage_manifest_sha256=sha(package / 'stage-manifest.json'), model='HILEGA_ATOMIC_DISABLED_BINDING_RELEASE_V1', scope='ATOMIC_PREPARATION_HOLD_TO_DISABLED_ADAPTER_REQUEST', binding_activation_included=False, production_execution_enabled=False)
    put(package / 'manifest.json', release)
    monkeypatch.setattr(tool, 'PIN_MANIFEST', sha(package / 'manifest.json'))
    (root / '.env').write_text('HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY\nHILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n')
    put(backup / 'startup-private.json', {'synthetic': True})
    database = root / 'data/research/hilega-production-workspace/sim.sqlite'
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.executescript('CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT);CREATE TABLE preparation_route(id INTEGER PRIMARY KEY,data TEXT);CREATE TABLE sim_stop_state(id INTEGER PRIMARY KEY,generation INTEGER,handled INTEGER);')
        db.execute('INSERT INTO control VALUES(1,?)', (json.dumps({'mode': 'PAUSED'}),))
        db.execute('INSERT INTO preparation_route VALUES(1,?)', (json.dumps({'route': 'PREPARATION_ONLY', 'model': 'APPLICATION_PREPARATION_ROUTE_V1'}),))
        db.execute('INSERT INTO sim_stop_state VALUES(1,0,0)')
        for table in ('intents', 'sim_orders', 'sim_fills', 'sim_allocation_reservations', 'preparation_plans', 'preparation_shadow_holds', 'preparation_outbox'):
            db.execute('CREATE TABLE ' + table + '(id TEXT)')
    plan = dict(root=str(root), backup=str(backup), package=str(package), database=str(database), manifest_sha256=tool.PIN_MANIFEST, env_sha256=sha(root / '.env'), startup_sha256=sha(backup / 'startup-private.json'), guard_files={})
    put(root / tool.PLAN_REL, plan)
    monkeypatch.setattr(tool, 'PIN_PLAN', sha(root / tool.PLAN_REL))
    return (root, package, backup, database, before)

def test_apply_and_rollback_preserve_database_and_configuration(setup):
    root, package, backup, database, before = setup
    db_before = database.read_bytes()
    env_before = (root / '.env').read_bytes()
    assert tool.check()['status'] == 'ATOMIC_BINDING_CODE_CHECKS_PASS'
    assert tool.apply()['services_started'] is False
    assert tool.check()['status'] == 'ATOMIC_BINDING_ALREADY_APPLIED'
    assert tool.rollback()['database_restored'] is False
    assert {name: tool.current(name) for name in tool.PAYLOAD} == before
    assert database.read_bytes() == db_before
    assert (root / '.env').read_bytes() == env_before

def test_running_processes_block_apply(setup, monkeypatch):

    def running():
        raise tool.Blocked('STILL_RUNNING')
    monkeypatch.setattr(tool, 'stopped', running)
    with pytest.raises(tool.Blocked, match='STILL_RUNNING'):
        tool.apply()
    assert not (setup[2] / 'code-transaction').exists()

@pytest.mark.parametrize('change', ['target', 'payload', 'env', 'manifest'])
def test_changed_inputs_block_before_apply(setup, change):
    root, package, backup, database, before = setup
    name = next((n for n, value in before.items() if value is not None))
    path = {'target': root / name, 'payload': package / 'files' / name, 'env': root / '.env', 'manifest': package / 'manifest.json'}[change]
    path.write_text('changed')
    with pytest.raises((tool.Blocked, ValueError)):
        tool.apply()
    assert not (backup / 'code-transaction').exists()

def test_interrupted_apply_can_restore_original_files(setup):

    class Interrupted(BaseException):
        pass

    def interrupt(name):
        raise Interrupted()
    with pytest.raises(Interrupted):
        tool.apply(checkpoint=interrupt)
    tool.rollback()
    assert {n: tool.current(n) for n in tool.PAYLOAD} == setup[4]

def test_changed_original_backup_blocks_rollback(setup):
    tool.apply()
    name = next((n for n, value in setup[4].items() if value is not None))
    (setup[2] / 'code-transaction/original' / name).write_text('changed')
    with pytest.raises(tool.Blocked, match='ORIGINAL_BACKUP_CHANGED'):
        tool.rollback()

def test_new_workspace_activity_blocks_rollback(setup):
    tool.apply()
    with sqlite3.connect(setup[3]) as db:
        db.execute("INSERT INTO intents VALUES('unexpected')")
    with pytest.raises(tool.Blocked, match='WORKSPACE_ACTIVITY'):
        tool.rollback()


def test_enabled_binding_mode_blocks_code_maintenance(setup, monkeypatch):
    root = setup[0]
    path = root / ".env"
    path.write_text(path.read_text()
                    + "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED=1\n")
    plan_path = root / tool.PLAN_REL
    plan = json.loads(plan_path.read_text())
    plan["env_sha256"] = sha(path)
    put(plan_path, plan)
    monkeypatch.setattr(tool, "PIN_PLAN", sha(plan_path))
    with pytest.raises(tool.Blocked, match="BINDING_MODE_MUST_REMAIN_OFF"):
        tool.apply()


@pytest.mark.parametrize("action", ["apply", "rollback"])
def test_existing_binding_blocks_maintenance(setup, action):
    if action == "rollback":
        tool.apply()
    with sqlite3.connect(setup[3]) as db:
        db.execute("CREATE TABLE preparation_request_bindings(id TEXT)")
        db.execute("INSERT INTO preparation_request_bindings VALUES('existing')")
    before = {name: tool.current(name) for name in tool.PAYLOAD}
    with pytest.raises(tool.Blocked, match="EXISTING_BINDING_REQUIRES_REVIEW"):
        getattr(tool, action)()
    assert {name: tool.current(name) for name in tool.PAYLOAD} == before


def test_empty_binding_table_is_preserved(setup):
    with sqlite3.connect(setup[3]) as db:
        db.execute("CREATE TABLE preparation_request_bindings(id TEXT)")
    original = setup[3].read_bytes()
    tool.apply()
    tool.rollback()
    assert setup[3].read_bytes() == original
