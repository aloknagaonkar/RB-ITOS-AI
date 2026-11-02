import json
from pathlib import Path
import sqlite3
import pytest
from maintenance_primitives import UNITS,sha
from rollout import apply,rollback,start,wrapper,check_plan


class Manager:
    def __init__(self):self.rows={u:dict(active='active',sub='running',pid=100+i) for i,u in enumerate(UNITS)};self.events=[]
    def state(self,u):return dict(self.rows[u])
    def control(self,a,u):
        self.events.append((a,u));self.rows[u]=dict(active='inactive' if a=='stop' else 'active',sub='dead' if a=='stop' else 'running',pid=0 if a=='stop' else 200)


@pytest.fixture
def setup(tmp_path):
    root=tmp_path/'repo';(root/'scripts').mkdir(parents=True);(root/'scripts/hilega_production_simulator_bridge.py').write_bytes(b'old-worker')
    folder=root/'plan';folder.mkdir();source=root/'source';source.mkdir()
    registration=dict(mode='CLOSED_PREPARATION_ONLY',production_execution_enabled=False,execution_factory_configured=False)
    (source/'CLOSED-REGISTRATION.json').write_text(json.dumps(registration));(source/'closed_worker_launcher.py').write_text('pass\n')
    files={p.name:sha(p.read_bytes()) for p in source.iterdir()}
    (source/'RELEASE-MANIFEST.json').write_text(json.dumps(dict(files=files)));digest=sha((source/'RELEASE-MANIFEST.json').read_bytes())
    app=root/'app.sqlite';adapter=root/'adapter.sqlite'
    with sqlite3.connect(app) as d:
        d.execute('CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT)');d.execute('INSERT INTO control VALUES(1,?)',(json.dumps(dict(mode='PAUSED')),))
        d.execute('CREATE TABLE sim_stop_state(id INTEGER PRIMARY KEY,generation INT,handled INT)');d.execute('INSERT INTO sim_stop_state VALUES(1,0,0)')
        d.execute('CREATE TABLE sim_bridge_health(id INTEGER PRIMARY KEY,data TEXT)');d.execute('INSERT INTO sim_bridge_health VALUES(1,?)',(json.dumps(dict(run_id='old')),))
    with sqlite3.connect(adapter) as d:
        d.execute('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT)');d.execute('INSERT INTO meta VALUES(1,?)',(json.dumps(dict(mode='LIVE_CLOSED')),))
    destination=root/'data/runtime/hilega-closed-releases'/digest
    plan=dict(model='HILEGA_GROUP1_EXACT_CLOSED_ROLLOUT_V1',repo=str(root),destination=str(destination),source_bundle=str(source),
        release_manifest_sha256=digest,bindings={},old_worker_sha256=sha(b'old-worker'),new_worker_sha256=sha(wrapper(destination,digest)),
        worker_mode=0o644,application_db=str(app),adapter_db=str(adapter),production_execution_enabled=False)
    return root,folder,plan,Manager()


def test_apply_stops_services_and_creates_real_sqlite_backups_before_install(setup):
    root,folder,p,m=setup;result=apply(p,folder,m,quiescence=lambda r:None)
    assert result['phase']=='INSTALLED_SERVICES_STOPPED'
    assert all(m.state(u)['pid']==0 for u in UNITS)
    for name in ('application.sqlite','adapter.sqlite'):
        with sqlite3.connect(folder/'backups'/name) as db:assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert (folder/'backups/worker.old').read_bytes()==b'old-worker'


def test_interruption_after_wrapper_can_restore_original_without_rewinding_database(setup):
    root,folder,p,m=setup
    def interrupt(stage):
        if stage=='AFTER_WORKER_WRAPPER':raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError):apply(p,folder,m,quiescence=lambda r:None,checkpoint=interrupt)
    before=Path(p['application_db']).read_bytes();rollback(p,folder,m,quiescence=lambda r:None)
    assert (root/'scripts/hilega_production_simulator_bridge.py').read_bytes()==b'old-worker'
    assert Path(p['application_db']).read_bytes()==before


def test_changed_backup_blocks_rollback(setup):
    _,folder,p,m=setup;apply(p,folder,m,quiescence=lambda r:None);(folder/'backups/worker.old').write_bytes(b'changed')
    with pytest.raises(ValueError,match='BACKUP_CHANGED'):rollback(p,folder,m,quiescence=lambda r:None)


def test_external_worker_change_blocks_rollback(setup):
    root,folder,p,m=setup;apply(p,folder,m,quiescence=lambda r:None);(root/'scripts/hilega_production_simulator_bridge.py').write_bytes(b'external')
    with pytest.raises(ValueError,match='EXTERNAL_WORKER_CHANGE'):rollback(p,folder,m,quiescence=lambda r:None)


def test_nonempty_lifecycle_blocks_before_stopping_services(setup):
    _,folder,p,m=setup
    with sqlite3.connect(p['adapter_db']) as d:d.execute('CREATE TABLE requests(id TEXT)');d.execute("INSERT INTO requests VALUES('existing')")
    with pytest.raises(ValueError,match='NONEMPTY_LIFECYCLE'):apply(p,folder,m,quiescence=lambda r:None)
    assert not m.events and not (folder/'TRANSACTION.json').exists()


def test_start_waits_for_pid_inventory_before_source_service(setup):
    _,folder,p,m=setup;apply(p,folder,m,quiescence=lambda r:None);m.events=[]
    def inventory(root):m.events.append(('inventory','ready'))
    start(p,folder,m,inventory=inventory,healthcheck=lambda *a:None)
    assert m.events.index(('inventory','ready'))<m.events.index(('start',UNITS[0]))


def test_start_failure_stops_started_service_set(setup):
    _,folder,p,m=setup;apply(p,folder,m,quiescence=lambda r:None)
    def failed(*a):raise ValueError('injected health failure')
    with pytest.raises(ValueError):start(p,folder,m,inventory=lambda r:None,healthcheck=failed)
    assert all(m.state(u)['pid']==0 for u in UNITS)
    assert json.loads((folder/'TRANSACTION.json').read_text())['phase']=='STARTUP_FAILED_SERVICES_STOPPED'


def test_plan_cannot_redirect_install_destination(setup):
    _,_,p,_=setup;p['destination']='/outside'
    with pytest.raises(ValueError,match='EXACT_IMMUTABLE_DESTINATION'):check_plan(p)


def test_plan_cannot_enable_execution(setup):
    _,_,p,_=setup;p['production_execution_enabled']=True
    with pytest.raises(ValueError,match='EXACT_CLOSED_PLAN'):check_plan(p)


def test_changed_approved_input_blocks_before_service_actions(setup):
    root,folder,p,m=setup;bound=root/'bound';bound.write_bytes(b'changed');p['bindings']={str(bound):sha(b'original')}
    with pytest.raises(ValueError,match='APPROVED_INPUT_CHANGED'):apply(p,folder,m,quiescence=lambda r:None)
    assert not m.events
