from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import pytest
from rollout import TARGETS,UNITS,apply,rollback,start,sha,save,require_empty_closed_baseline


class Manager:
    def __init__(self):self.states={u:dict(active='active',sub='running',pid=100+i) for i,u in enumerate(UNITS)};self.calls=[]
    def state(self,unit):return deepcopy(self.states[unit])
    def control(self,action,unit):
        self.calls.append((action,unit));self.states[unit]=dict(active='active' if action=='start' else 'inactive',sub='running' if action=='start' else 'dead',pid=200 if action=='start' else 0)


@pytest.fixture
def case(tmp_path):
    root=tmp_path/'repo';stage=tmp_path/'stage';folder=tmp_path/'transaction'
    root.mkdir();stage.mkdir();folder.mkdir(mode=0o700);entries=[]
    for i,name in enumerate(TARGETS):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
        if i<2:p.write_bytes(b'original');p.chmod(0o640)
        q=stage/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b'candidate')
        entries.append(dict(name=name,old_sha256=sha(b'original') if i<2 else None,new_sha256=sha(b'candidate'),mode=0o640 if i<2 else 0o644))
    app=root/'app.sqlite';adapter=root/'adapter.sqlite'
    with sqlite3.connect(app) as db:
        db.execute('CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT)');db.execute('INSERT INTO control VALUES(1,?)',(json.dumps(dict(mode='PAUSED')),))
        db.execute('CREATE TABLE sim_stop_state(id INTEGER,generation INTEGER,handled INTEGER)');db.execute('INSERT INTO sim_stop_state VALUES(1,0,0)')
        db.execute('CREATE TABLE preparation_plans(id TEXT)')
    with sqlite3.connect(adapter) as db:
        db.execute('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT)');db.execute('INSERT INTO meta VALUES(1,?)',(json.dumps(dict(mode='LIVE_CLOSED')),))
        for table in ('requests','attempts','receipts'):db.execute('CREATE TABLE '+table+'(id TEXT)')
    plan=dict(model='HILEGA_APPROVABLE_CLOSED_ROLLOUT_V1',repo=str(root),stage=str(stage),application_db=str(app),adapter_db=str(adapter),
        files=entries,previous_bridge_run_hash='previous',production_execution_enabled=False)
    save(folder/'PLAN.json',plan)
    return root,stage,folder,plan,Manager()


def run(case,**kwargs):
    root,stage,folder,plan,manager=case
    return apply(plan,folder,manager,quiescence=lambda root:None,**kwargs)


def original(root):
    assert not (root/TARGETS[2]).exists()
    assert all((root/n).read_bytes()==b'original' for n in TARGETS[:2])


def test_apply_stops_services_backs_up_both_databases_and_installs_only_three_files(case):
    root,stage,folder,plan,manager=case;tx=run(case)
    assert tx['phase']=='INSTALLED_SERVICES_STOPPED' and all(manager.state(u)['pid']==0 for u in UNITS)
    assert all((root/n).read_bytes()==b'candidate' for n in TARGETS)
    for name in ('application.sqlite','adapter.sqlite'):
        with sqlite3.connect(folder/'backups'/name) as db:assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert not any(a=='start' for a,u in manager.calls)


@pytest.mark.parametrize('point',['AFTER_FILE_1','AFTER_FILE_2','AFTER_FILE_3'])
def test_interrupted_install_can_restore_all_code_without_database_rewind(case,point):
    root,stage,folder,plan,manager=case
    def stop(at):
        if at==point:raise RuntimeError('synthetic interruption')
    with pytest.raises(RuntimeError):run(case,checkpoint=stop)
    app=Path(plan['application_db']);before=app.read_bytes()
    rollback(folder,manager,quiescence=lambda root:None);original(root)
    assert app.read_bytes()==before and all(manager.state(u)['pid']==0 for u in UNITS)


def test_foreign_file_change_blocks_rollback_before_any_restore(case):
    root,stage,folder,plan,manager=case;run(case);(root/TARGETS[1]).write_bytes(b'foreign')
    with pytest.raises(ValueError,match='EXTERNAL_FILE_CHANGE_BLOCKS_ROLLBACK'):rollback(folder,manager,quiescence=lambda root:None)
    assert (root/TARGETS[0]).read_bytes()==b'candidate'


def test_unmanaged_process_keeps_services_stopped_without_installing(case):
    root,stage,folder,plan,manager=case
    def blocked(root):raise ValueError('UNMANAGED_SOURCE_WORKER_REMAINS')
    with pytest.raises(ValueError):apply(plan,folder,manager,quiescence=blocked)
    original(root);assert all(manager.state(u)['pid']==0 for u in UNITS)


def test_active_lifecycle_cannot_be_deployed_over(case):
    root,stage,folder,plan,manager=case
    with sqlite3.connect(plan['application_db']) as db:db.execute("INSERT INTO preparation_plans VALUES('existing')")
    with pytest.raises(ValueError,match='NONEMPTY_LIFECYCLE_REQUIRES_REVIEW'):run(case)
    original(root)


def test_existing_owner_requires_migration_before_install(case):
    root,stage,folder,plan,manager=case
    with sqlite3.connect(plan['application_db']) as db:db.execute('CREATE TABLE preparation_candidate_exclusive_source_owner_v1(id INTEGER)')
    with pytest.raises(ValueError,match='EXISTING_OWNER_STATE_REQUIRES_MIGRATION'):run(case)
    original(root)


def test_start_restores_only_previously_active_services_and_checks_health(case):
    root,stage,folder,plan,manager=case;manager.states[UNITS[-1]]=dict(active='inactive',sub='dead',pid=0);run(case)
    checks=[];tx=start(folder,manager,healthcheck=lambda app,old:checks.append((app,old)))
    assert tx['phase']=='CLOSED_HOOK_RUNNING' and len(checks)==1
    assert manager.state(UNITS[-1])['pid']==0
    assert [u for a,u in manager.calls if a=='start'][-1]==UNITS[0]


def test_health_failure_stops_restarted_services_for_review(case):
    root,stage,folder,plan,manager=case;run(case)
    def fail(app,old):raise ValueError('stale heartbeat')
    with pytest.raises(ValueError):start(folder,manager,healthcheck=fail)
    assert all(manager.state(u)['pid']==0 for u in UNITS)
    rollback(folder,manager,quiescence=lambda root:None);original(root)


def test_changed_staged_file_is_rejected_before_stopping_services(case):
    root,stage,folder,plan,manager=case;(stage/TARGETS[0]).write_bytes(b'changed')
    with pytest.raises(ValueError,match='ROLLOUT_SOURCE_CHANGED'):run(case)
    assert manager.calls==[];original(root)


def test_stop_failure_does_not_install_or_automatically_restart(case):
    root,stage,folder,plan,manager=case
    def fail(action,unit):raise RuntimeError('service stop failed')
    manager.control=fail
    with pytest.raises(RuntimeError):run(case)
    original(root);assert not (folder/'backups').exists()
