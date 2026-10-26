"""Deployment guards tested against temporary code trees/DBs only; VM execution."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
import pytest
import deploy as d


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(data)


@pytest.fixture
def env(tmp_path,monkeypatch):
    for key in ('HILEGA_PRODUCTION_EXECUTION_ROUTE','HILEGA_PRODUCTION_WORKSPACE_MODE'):
        monkeypatch.delenv(key,raising=False)
    root=tmp_path/'root';root.mkdir();release=tmp_path/'release';stage=tmp_path/'stage'
    write(root/'backend/existing.py','original\n')
    write(release/'files/backend/existing.py','replacement\n')
    write(release/'files/backend/new_module.py','new code\n')
    write(root/'helper.py','helper\n');write(stage/'helper.py','helper\n')
    files={name:d.sha(release/'files'/name) for name in ('backend/existing.py','backend/new_module.py')}
    manifest=dict(model='APPLICATION_PREPARATION_PACKAGE_V1',files=files,
        expected={'backend/existing.py':d.sha(root/'backend/existing.py')},dependencies={'helper.py':d.sha(root/'helper.py')})
    write(release/'manifest.json',json.dumps(manifest))
    lock=tmp_path/'release-lock.json';lock.write_bytes((release/'manifest.json').read_bytes())
    monkeypatch.setattr(d,'PINNED_MANIFEST',d.sha(lock));monkeypatch.setattr(d,'RELEASE_LOCK',lock)
    for name in files:
        write(stage/name,(release/'files'/name).read_text())
    write(stage/'APPLICATION_PREPARATION_STAGED.json',json.dumps(dict(model='APPLICATION_PREPARATION_STAGED_V1',files=files)))
    report=tmp_path/'validation.json'
    write(report,json.dumps(dict(model='APPLICATION_PREPARATION_VALIDATION_V1',status='PASS',returncode=0,
                                files=files,production_execution_enabled=False,applied=False)))
    db=root/'workspace.sqlite'
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT); CREATE TABLE sim_stop_state(id INTEGER PRIMARY KEY,generation INTEGER,handled INTEGER); INSERT INTO sim_stop_state VALUES(1,0,0);')
        c.execute('INSERT INTO control VALUES(1,?)',(json.dumps(dict(mode='PAUSED')),))
        for table in ('intents','sim_orders','sim_fills','sim_allocation_reservations'):
            c.execute('CREATE TABLE '+table+'(id TEXT)')
    calls=[]
    monkeypatch.setattr(d,'verify_units',lambda units:calls.append(tuple(units)))
    return dict(root=root,release=release,stage=stage,report=report,db=db,manifest=manifest,calls=calls)


def check(e):return d.check(e['root'],e['release'],e['stage'],e['report'],e['db'])
def apply(e,**kw):return d.apply(e['root'],e['release'],e['stage'],e['report'],e['db'],['fixture.service'],services_stopped=True,**kw)
def rollback(e,backup,**kw):return d.rollback(e['root'],backup,e['db'],['fixture.service'],services_stopped=True,**kw)


def test_check_is_readonly_and_not_apply_ready(env):
    before={str(p.relative_to(env['root'])):p.read_bytes() for p in env['root'].rglob('*') if p.is_file()}
    result=check(env)
    assert result['replaced_files']==result['new_files']==1
    assert result['apply_ready'] is False and result['services_stopped_verified'] is False
    assert before=={str(p.relative_to(env['root'])):p.read_bytes() for p in env['root'].rglob('*') if p.is_file()}


def test_apply_backs_up_and_does_not_change_db_or_env(env):
    db=env['db'].read_bytes();result=apply(env)
    assert result['status']=='CODE_APPLIED_SERVICES_STILL_STOPPED'
    assert (env['root']/'backend/existing.py').read_text()=='replacement\n'
    assert env['db'].read_bytes()==db and not (env['root']/'.env').exists()
    state=d.read_json(Path(result['backup'])/'deployment.json')
    assert state['phase']=='APPLIED'
    assert (Path(result['backup'])/'original/backend/existing.py').read_text()=='original\n'


def test_round_trip_rollback_removes_new_file_restores_original(env):
    result=apply(env);rollback(env,result['backup'])
    assert (env['root']/'backend/existing.py').read_text()=='original\n'
    assert not (env['root']/'backend/new_module.py').exists()
    rollback(env,result['backup']) # Idempotent code recovery.


def test_refuses_changed_validation(env):
    value=d.read_json(env['report']);value['status']='FAIL';env['report'].write_text(json.dumps(value))
    with pytest.raises(d.Blocked,match='MATCHING_PASS_VALIDATION_REPORT_REQUIRED'):check(env)
    assert not (env['root']/'backups').exists()


def test_refuses_changed_stage(env):
    (env['stage']/'backend/new_module.py').write_text('changed')
    with pytest.raises(d.Blocked,match='VALIDATED_STAGE_CHANGED'):check(env)


def test_refuses_changed_checkout(env):
    (env['root']/'backend/existing.py').write_text('new user work')
    with pytest.raises(d.Blocked,match='APPLICATION_SOURCE_CHANGED'):apply(env)
    assert not (env['root']/'backups').exists()


def test_refuses_changed_package(env):
    (env['release']/'files/backend/new_module.py').write_text('changed')
    with pytest.raises(d.Blocked,match='PACKAGED_FILE_CHANGED'):check(env)


def test_refuses_unapproved_route_activation(env):
    write(env['root']/'.env','HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY\n')
    with pytest.raises(d.Blocked,match='ACTIVATION_NOT_AUTHORIZED'):check(env)


def test_armed_workspace_requires_pause(env):
    with sqlite3.connect(env['db']) as c:c.execute('UPDATE control SET data=?',(json.dumps(dict(mode='ARMED')),))
    with pytest.raises(d.Blocked,match='WORKSPACE_MUST_BE_PAUSED'):check(env)


def test_pending_preparation_blocks_rollback(env):
    result=apply(env)
    with sqlite3.connect(env['db']) as c:
        c.execute('CREATE TABLE preparation_route(id TEXT)');c.execute("INSERT INTO preparation_route VALUES('enrolled')")
    with pytest.raises(d.Blocked,match='DATA_RECOVERY_REVIEW'):rollback(env,result['backup'])
    assert (env['root']/'backend/new_module.py').exists()


def test_rollback_never_overwrites_later_edits(env):
    result=apply(env);(env['root']/'backend/existing.py').write_text('later user work')
    with pytest.raises(d.Blocked,match='POST_DEPLOYMENT_EDIT_REQUIRES_REVIEW'):rollback(env,result['backup'])
    assert (env['root']/'backend/existing.py').read_text()=='later user work'


def test_rollback_refuses_tampered_backup(env):
    result=apply(env);write(Path(result['backup'])/'original/backend/existing.py','changed backup')
    with pytest.raises(d.Blocked,match='BACKUP_CONTENT_CHANGED'):rollback(env,result['backup'])


def test_interrupted_apply_has_recoverable_journal(env):
    class Interrupted(BaseException):pass
    def crash(name):raise Interrupted()
    with pytest.raises(Interrupted):apply(env,checkpoint=crash)
    backup=next((env['root']/'backups').iterdir())
    assert d.read_json(backup/'deployment.json')['phase']=='INTERRUPTED_REQUIRES_ROLLBACK'
    rollback(env,backup)
    assert (env['root']/'backend/existing.py').read_text()=='original\n'
    assert not (env['root']/'backend/new_module.py').exists()


def test_partial_deployment_is_not_reapplied(env):
    (env['root']/'backend/existing.py').write_text('replacement\n')
    with pytest.raises(d.Blocked,match='PARTIAL_OR_MIXED_DEPLOYMENT'):check(env)


def test_requires_explicit_stopped_process_attestation(env):
    with pytest.raises(d.Blocked,match='ALL_API_AND_WORKER_PROCESSES_MUST_BE_STOPPED'):
        d.apply(env['root'],env['release'],env['stage'],env['report'],env['db'],[],services_stopped=False)


def test_unit_checker_rejects_active_service(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(d.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='LoadState=loaded\nActiveState=active\nTriggeredBy=\n'))
    with pytest.raises(d.Blocked,match='REVIEWED_SERVICE_IS_NOT_STOPPED'):d.verify_units(['fixture.service'])


def test_unit_checker_requires_triggered_units(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(d.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='LoadState=loaded\nActiveState=inactive\nTriggeredBy=fixture.socket\n'))
    with pytest.raises(d.Blocked,match='TRIGGERING_UNIT'):d.verify_units(['fixture.service'])


def test_symlink_target_rejected(env,tmp_path):
    path=env['root']/'backend/existing.py';path.unlink();outside=tmp_path/'outside';outside.write_text('original\n');path.symlink_to(outside)
    with pytest.raises(d.Blocked,match='SYMLINK_OR_OUTSIDE_TARGET'):check(env)


def test_modified_backup_file_map_rejected(env):
    result=apply(env);path=Path(result['backup'])/'deployment.json';state=d.read_json(path)
    state['files']['helper.py']=d.sha(env['root']/'helper.py');path.write_text(json.dumps(state))
    with pytest.raises(d.Blocked,match='BACKUP_FILE_MAP_DIFFERS_FROM_RELEASE'):rollback(env,result['backup'])
