import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
import pytest
from readiness import (approval_bindings,supervisor_review,database_snapshot,baseline,transitive_inventory,
    dependency_manifest_review,sha,OWNER,COORDINATOR)

SUPERVISOR="""
need(permit.get('config_sha256')==digest(folder/'config-private.json'),'bad config')
need(permit.get('runner_sha256')==digest(Path(__file__)),'bad runner')
"""


@pytest.fixture
def supervisor(tmp_path):
    home=tmp_path/'home';repo=tmp_path/'repo';repo.mkdir();folder=home/'hilega-persistent-supervision-stage-v1';folder.mkdir(parents=True)
    (folder/'runner.py').write_text(SUPERVISOR)
    config=dict(root=str(repo),startup={'production-source-worker':dict(argv=[str(repo/'.venv/bin/python'),'-u',str(repo/'scripts/hilega_production_simulator_bridge.py'),'--watch'],
        env=dict(HILEGA_PRODUCTION_EXECUTION_ROUTE='PREPARATION_ONLY',HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',UPSTOX_ACCESS_TOKEN='must-not-export',HILEGA_PRODUCTION_SIM_DB='data/app.sqlite'))})
    raw=json.dumps(config).encode();(folder/'config-private.json').write_bytes(raw)
    (folder/'MIGRATION_APPROVED.json').write_text(json.dumps(dict(config_sha256=sha(raw),runner_sha256=sha(SUPERVISOR.encode()))))
    return repo,home,folder


def test_supervisor_contract_checked_without_exporting_credentials(supervisor):
    repo,home,folder=supervisor
    with patch('readiness.SUPERVISOR_SHA',sha(SUPERVISOR.encode())):report,context=supervisor_review(repo,home)
    assert report['approval_hashes_match'] is True and context=={'HILEGA_PRODUCTION_SIM_DB':'data/app.sqlite'}
    assert 'must-not-export' not in json.dumps(report) and 'UPSTOX_ACCESS_TOKEN' not in json.dumps(context)
    assert report['environment_file_opened'] is False


def test_changed_private_config_fails_approval_without_rewriting_it(supervisor):
    repo,home,folder=supervisor;p=folder/'config-private.json';p.write_bytes(p.read_bytes()+b' ');before=p.read_bytes()
    with patch('readiness.SUPERVISOR_SHA',sha(SUPERVISOR.encode())):report,context=supervisor_review(repo,home)
    assert report['status']=='BLOCKED' and context=={} and p.read_bytes()==before


def test_unrecognized_approval_expressions_are_not_assumed_valid():
    with pytest.raises(ValueError,match='SUPERVISOR_APPROVAL_CONTRACT_NOT_RECOGNIZED'):approval_bindings('permit={}')


@pytest.fixture
def databases(tmp_path):
    app=tmp_path/'app.sqlite';adapter=tmp_path/'adapter.sqlite'
    with sqlite3.connect(app) as db:
        db.execute('CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT)')
        db.execute('INSERT INTO control VALUES(1,?)',(json.dumps(dict(mode='PAUSED',version=3,session_date='2000-01-01',private='never-export')),))
        db.execute('CREATE TABLE sim_stop_state(id INTEGER,generation INTEGER,handled INTEGER)');db.execute('INSERT INTO sim_stop_state VALUES(1,0,0)')
        db.execute('CREATE TABLE preparation_source(id INTEGER PRIMARY KEY,data TEXT)')
        db.execute('INSERT INTO preparation_source VALUES(1,?)',(json.dumps(dict(path='private-journal-path',sequence=5,hash='x')),))
        db.execute('CREATE TABLE preparation_plans(id TEXT,data TEXT)')
    with sqlite3.connect(adapter) as db:
        db.execute('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT)')
        db.execute('INSERT INTO meta VALUES(1,?)',(json.dumps(dict(scope='private-account-scope',mode='LIVE_CLOSED')),))
        for t in ('requests','attempts','receipts'):db.execute('CREATE TABLE '+t+'(id TEXT,data TEXT)')
    return app,adapter


def test_query_only_snapshot_preserves_database_and_redacts_rows(databases):
    app,adapter=databases;before={p:p.read_bytes() for p in databases}
    left=database_snapshot(app,'application');right=database_snapshot(adapter,'adapter')
    assert left['status']==right['status']=='READ_ONLY_LOCAL_SNAPSHOT_OBSERVED'
    assert left['source_sequence']==5 and right['adapter_is_live_closed'] is True
    exported=json.dumps([left,right])
    assert all(x not in exported for x in ('never-export','private-account-scope','private-journal-path'))
    assert all(p.read_bytes()==raw for p,raw in before.items())


def test_missing_database_is_not_created(tmp_path):
    p=tmp_path/'missing.sqlite';report=database_snapshot(p,'adapter')
    assert report['database_opened'] is False and not p.exists()


def test_existing_owner_requires_migration_review_without_signature_claim(databases):
    app,adapter=databases
    with sqlite3.connect(app) as db:db.execute('CREATE TABLE '+OWNER+'(id INTEGER,data TEXT)')
    report=baseline(app.parent,{},application_db=app,adapter_db=adapter)
    assert 'EXISTING_OWNER_OR_COORDINATOR_REQUIRES_AUTHENTICATED_MIGRATION_REVIEW' in report['blockers']
    assert report['snapshots'][0]['signed_ownership_verified'] is False


def test_same_database_cannot_be_used_as_both_sources(databases):
    app,_=databases;report=baseline(app.parent,{},application_db=app,adapter_db=app)
    assert report['reason']=='DISTINCT_DATABASES_REQUIRED' and report['live_database_inspected'] is False


def test_symlink_database_is_not_opened(databases,tmp_path):
    app,_=databases;p=tmp_path/'alias.sqlite';p.symlink_to(app)
    assert database_snapshot(p,'application')['database_opened'] is False


def test_defaults_do_not_claim_effective_runtime_paths(tmp_path):
    report=baseline(tmp_path,{})
    assert 'ADAPTER_EFFECTIVE_PATH_NOT_CONFIRMED' in report['blockers'] and report['migration_approved'] is False


def test_transitive_local_modules_are_pinned_without_execution(tmp_path):
    (tmp_path/'a.py').write_text('import b\n')
    (tmp_path/'b.py').write_text("raise AssertionError('Never execute')\nimport json\n")
    report=transitive_inventory(['a'],[tmp_path],[tmp_path],{})
    assert report['unresolved']==[] and report['package_code_executed'] is False
    assert {r['module'] for r in report['modules']}=={'a','b','json'}
    assert all(r.get('sha256') for r in report['modules'] if r['kind']=='PINNED_LOCAL_PYTHON')


def test_dynamic_loader_and_unknown_import_remain_explicit(tmp_path):
    (tmp_path/'a.py').write_text("import missing_hilega_xyz\n__import__('dynamic_name')\n")
    report=transitive_inventory(['a'],[tmp_path],[tmp_path],{})
    assert report['unresolved']==['missing_hilega_xyz']
    assert 'DYNAMIC_LOADING_REQUIRES_SEPARATE_MANIFEST_REVIEW' in report['blockers']
    assert report['dependency_manifest_fully_reconciled'] is False


def test_transitive_scan_is_bounded(tmp_path):
    (tmp_path/'a.py').write_text('import b\n');(tmp_path/'b.py').write_text('value=1\n')
    report=transitive_inventory(['a'],[tmp_path],[tmp_path],{},max_modules=1)
    assert 'LOCAL_MODULE_SCAN_LIMIT_REACHED' in report['blockers']


def test_installed_dependency_manifest_mismatch_is_reported(tmp_path):
    source=tmp_path/'rules.py';source.write_text('value=1\n');manifest=tmp_path/'dependencies.json'
    manifest.write_text(json.dumps({'rules.py':sha(source.read_bytes())}))
    assert dependency_manifest_review(tmp_path,manifest)['status']=='INSTALLED_DEPENDENCY_PINS_MATCH'
    source.write_text('value=2\n')
    assert dependency_manifest_review(tmp_path,manifest)['status']=='INSTALLED_DEPENDENCY_PIN_MISMATCH'


def test_armed_controller_with_pending_stop_is_not_quiescent(databases):
    app,adapter=databases
    with sqlite3.connect(app) as db:
        db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(dict(mode='ARMED',version=4,session_date='2000-01-01')),))
        db.execute('UPDATE sim_stop_state SET generation=1 WHERE id=1')
    report=baseline(app.parent,{},application_db=app,adapter_db=adapter)
    assert 'CONTROLLER_NOT_QUIESCENT' in report['blockers'] and report['migration_approved'] is False
    with sqlite3.connect(app) as db:assert json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])['mode']=='ARMED'
