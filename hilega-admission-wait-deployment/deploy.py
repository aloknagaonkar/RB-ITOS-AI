"""Preparation-route code deployment. Default action is read-only check."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parents[1]
PIN_MANIFEST = '781000c45ab1a6a19f92c2d36a4ea4c5ebda0233cf61f8901fb76add8767783e'
PIN_PLAN = 'be2b037252ec707691e1e335c6792f5079daf2340b425483f413c596ffeee562'
PLAN_REL = 'backups/hilega-admission-wait-maintenance-5zpodt29/plan.json'
PAYLOAD = {'backend/market_lab/hilega_preparation_runtime_v1/source.py', 'tests/test_hilega_preparation_wait_admission_v1.py'}

def load_helper(name, path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError('REGULAR_HELPER_REQUIRED')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('DEPLOYMENT_HELPER_CHANGED')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
guard = load_helper('_auto_limit_file_guards', ROOT / 'hilega-production-application-deployment/deploy.py', '44dd109e11c3ae6a2d2d01719aef345b1f0d9e83c79aac5c167dca3b1e6ab866')
managed = load_helper('_auto_limit_process_guards', ROOT / 'hilega-production-application-deployment/managed_processes.py', '83c6d960bf47571f6e5e1ed5647a7fa97da4d011fce71791a7e4a5045c905119')
Blocked = guard.Blocked
need = guard.need

def sha(path):
    need(path.is_file() and (not path.is_symlink()), 'REGULAR_FILE_REQUIRED')
    return hashlib.sha256(path.read_bytes()).hexdigest()

def stopped():
    managed.require_stopped(ROOT)

def workspace(plan):
    path = Path(plan['database'])
    need(path == ROOT / 'data/research/hilega-production-workspace/sim.sqlite', 'WORKSPACE_PATH_CHANGED')
    sha(path)
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        control = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        route = json.loads(db.execute('SELECT data FROM preparation_route WHERE id=1').fetchone()[0])
        need(control['mode'] == 'PAUSED', 'CONTROLLER_MUST_REMAIN_PAUSED')
        need(route == {'route': 'PREPARATION_ONLY', 'model': 'APPLICATION_PREPARATION_ROUTE_V1'}, 'PERSISTED_PREPARATION_ROUTE_REQUIRED')
        stop = db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        need(stop is not None and stop[0] == stop[1], 'STOP_PENDING')
        for table in ('intents', 'sim_orders', 'sim_fills', 'sim_allocation_reservations', 'preparation_plans', 'preparation_shadow_holds', 'preparation_outbox'):
            need(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0, 'WORKSPACE_ACTIVITY_REQUIRES_REVIEW')
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preparation_request_bindings'").fetchone()
        if exists:
            need(db.execute('SELECT COUNT(*) FROM preparation_request_bindings').fetchone()[0] == 0, 'EXISTING_BINDING_REQUIRES_REVIEW')
        return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()

def context(payload=True):
    plan_path = guard.target(ROOT, PLAN_REL)
    need(sha(plan_path) == PIN_PLAN, 'MAINTENANCE_PLAN_CHANGED')
    plan = guard.read_json(plan_path)
    backup = plan_path.parent
    package = ROOT / 'hilega-admission-wait-release-v1'
    need(plan['root'] == str(ROOT) and plan['backup'] == str(backup) and (plan['package'] == str(package)), 'MAINTENANCE_ROOT_MISMATCH')
    need(plan['manifest_sha256'] == PIN_MANIFEST, 'PLAN_RELEASE_MISMATCH')
    need(sha(backup / 'startup-private.json') == plan['startup_sha256'], 'PRIVATE_STARTUP_RECORD_CHANGED')
    need(sha(ROOT / '.env') == plan['env_sha256'], 'ENVIRONMENT_CHANGED')
    config = dotenv_values(ROOT / '.env')
    need(config.get('HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED', '0') == '1', 'BINDING_MODE_MUST_REMAIN_ON')
    need(config.get('HILEGA_PRODUCTION_EXECUTION_ROUTE') == 'PREPARATION_ONLY' and config.get('HILEGA_PRODUCTION_WORKSPACE_MODE') == 'SIMULATION_ONLY', 'CONFIGURATION_REQUIRES_REVIEW')
    for name, expected in plan['guard_files'].items():
        need(sha(guard.target(ROOT, name)) == expected, 'GUARD_FILE_CHANGED')
    manifest_path = guard.target(package, 'manifest.json')
    need(sha(manifest_path) == PIN_MANIFEST, 'RELEASE_MANIFEST_CHANGED')
    release = guard.read_json(manifest_path)
    need(release.get('model') == 'HILEGA_PREPARATION_WAIT_ADMISSION_RELEASE_V1' and release.get('scope') == 'PREPARATION_LOCAL_BASELINE_REFRESH_ONLY' and (release.get('configuration_change_included') is False) and (release.get('production_execution_enabled') is False), 'ADMISSION_RELEASE_IDENTITY_INVALID')
    need(set(release['files']) == PAYLOAD and set(release['target_baseline']) == PAYLOAD, 'EXACT_RELEASE_FILES_REQUIRED')
    for name, expected in release['dependencies'].items():
        need(sha(guard.target(ROOT, name)) == expected, 'DEPENDENCY_CHANGED')
    for name, field in (('validation.json', 'validation_sha256'), ('stage-manifest.json', 'stage_manifest_sha256')):
        need(sha(guard.target(package, name)) == release[field], 'VALIDATION_EVIDENCE_CHANGED')
    proof = guard.read_json(package / 'validation.json')
    need(proof.get('status') == 'PASS' and proof.get('pytest_exit_code') == 0, 'PASSING_VALIDATION_REQUIRED')
    if payload:
        for name, expected in release['files'].items():
            need(sha(guard.target(package / 'files', name)) == expected, 'PACKAGED_FILE_CHANGED')
    workspace(plan)
    return (plan, release, package, backup / 'code-transaction')

def current(name):
    path = guard.target(ROOT, name)
    return sha(path) if path.exists() else None

def journal(transaction, value):
    guard.atomic_bytes(transaction / 'state.json', json.dumps(value, indent=2).encode(), 384)

def check():
    plan, release, package, transaction = context()
    expected = release['target_baseline']
    status = 'ADMISSION_WAIT_CODE_CHECKS_PASS'
    if (transaction / 'state.json').exists():
        state = guard.read_json(transaction / 'state.json')
        need(state['root'] == str(ROOT) and state['plan_sha256'] == PIN_PLAN, 'TRANSACTION_IDENTITY_MISMATCH')
        need(state['phase'] == 'APPLIED', 'RECOVERY_REVIEW_REQUIRED')
        expected = release['files']
        status = 'ADMISSION_WAIT_ALREADY_APPLIED'
    need(all((current(name) == expected[name] for name in PAYLOAD)), 'TARGET_CHANGED')
    return dict(status=status, controller_mode='PAUSED', execution_route='PREPARATION_ONLY', apply_ready=False, processes_signalled=False, production_execution_enabled=False)

def apply(checkpoint=lambda name: None):
    with guard.deployment_lock(ROOT):
        stopped()
        plan, release, package, transaction = context()
        need(not transaction.exists(), 'TRANSACTION_ALREADY_EXISTS')
        need(all((current(n) == release['target_baseline'][n] for n in PAYLOAD)), 'TARGET_CHANGED')
        transaction.mkdir(mode=448)
        modes = {}
        for name in sorted(PAYLOAD):
            path = guard.target(ROOT, name)
            modes[name] = path.stat().st_mode & 511 if path.exists() else 420
            if path.exists():
                guard.atomic_bytes(guard.target(transaction / 'original', name), path.read_bytes(), modes[name])
        database_before = workspace(plan)
        with closing(sqlite3.connect(Path(plan['database']).as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(transaction / 'stopped-workspace.sqlite')) as destination:
            source.backup(destination)
        os.chmod(transaction / 'stopped-workspace.sqlite', 384)
        state = dict(model='HILEGA_ADMISSION_WAIT_CODE_TRANSACTION_V1', root=str(ROOT), plan_sha256=PIN_PLAN, before=release['target_baseline'], files=release['files'], modes=modes, phase='BACKUP_COMPLETE', database_fingerprint=database_before, production_execution_enabled=False)
        journal(transaction, state)
        try:
            state['phase'] = 'APPLYING'
            journal(transaction, state)
            for name in sorted(PAYLOAD):
                stopped()
                need(workspace(plan) == database_before, 'DATABASE_CHANGED')
                need(sha(ROOT / '.env') == plan['env_sha256'], 'ENVIRONMENT_CHANGED')
                need(current(name) == state['before'][name], 'TARGET_CHANGED')
                source = guard.target(package / 'files', name)
                need(sha(source) == state['files'][name], 'PACKAGED_FILE_CHANGED')
                guard.atomic_bytes(guard.target(ROOT, name), source.read_bytes(), modes[name])
                checkpoint(name)
            stopped()
            need(workspace(plan) == database_before, 'DATABASE_CHANGED')
            state['phase'] = 'APPLIED'
            journal(transaction, state)
        except BaseException:
            state['phase'] = 'INTERRUPTED_REQUIRES_RECOVERY'
            journal(transaction, state)
            raise
    return dict(status='ADMISSION_WAIT_CODE_APPLIED_SERVICES_STILL_STOPPED', transaction=str(transaction), services_started=False, database_modified=False, configuration_changed=False, production_execution_enabled=False)

def rollback():
    with guard.deployment_lock(ROOT):
        stopped()
        plan, release, package, transaction = context(payload=False)
        state = guard.read_json(transaction / 'state.json')
        need(state['root'] == str(ROOT) and state['plan_sha256'] == PIN_PLAN and (state['before'] == release['target_baseline']) and (state['files'] == release['files']), 'TRANSACTION_IDENTITY_MISMATCH')
        for name in sorted(PAYLOAD):
            need(current(name) in {state['before'][name], state['files'][name]}, 'TARGET_CHANGED_OUTSIDE_TRANSACTION')
            if state['before'][name] is not None:
                need(sha(guard.target(transaction / 'original', name)) == state['before'][name], 'ORIGINAL_BACKUP_CHANGED')
        for name in sorted(PAYLOAD):
            stopped()
            workspace(plan)
            path = guard.target(ROOT, name)
            need(current(name) in {state['before'][name], state['files'][name]}, 'TARGET_CHANGED_DURING_RECOVERY')
            if state['before'][name] is None:
                path.unlink(missing_ok=True)
                guard.fsync_directory(path.parent)
            else:
                original = guard.target(transaction / 'original', name)
                need(sha(original) == state['before'][name], 'ORIGINAL_BACKUP_CHANGED')
                guard.atomic_bytes(path, original.read_bytes(), state['modes'][name])
        state['phase'] = 'ROLLED_BACK'
        journal(transaction, state)
    return dict(status='ADMISSION_WAIT_CODE_ROLLED_BACK_SERVICES_STILL_STOPPED', database_restored=False, configuration_changed=False, services_started=False, production_execution_enabled=False)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'apply', 'rollback'), nargs='?', default='check')
    parser.add_argument('--confirmation')
    args = parser.parse_args()
    if args.action != 'check':
        required = 'APPLY_ADMISSION_WAIT_CODE_ONLY' if args.action == 'apply' else 'ROLLBACK_ADMISSION_WAIT_CODE_ONLY'
        need(args.confirmation == required, 'EXPLICIT_ACTION_REQUIRED')
    return {'check': check, 'apply': apply, 'rollback': rollback}[args.action]()
if __name__ == '__main__':
    os.umask(63)
    try:
        print(json.dumps(main(), indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps(dict(status='BLOCKED', reason=str(exc), production_execution_enabled=False)))
        raise SystemExit(1)
