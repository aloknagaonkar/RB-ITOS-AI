"""Exact-plan closed bundle install. No owner enrollment, authority or live gate changes."""
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sqlite3
import time
from assembly import regular,verify,need
from maintenance_primitives import UNITS,Systemd,sha,atomic,save,require_empty_closed_baseline,backup_database,no_unmanaged_python

TARGET='scripts/hilega_production_simulator_bridge.py'


def wrapper(bundle,digest):
    return ('"""Approved CLOSED preparation bundle launcher; no execution factory."""\n'
        'from pathlib import Path\nimport hashlib,json,runpy\n'
        'root=Path('+repr(str(bundle))+')\n'
        'raw=(root/"RELEASE-MANIFEST.json").read_bytes()\n'
        'if hashlib.sha256(raw).hexdigest()!='+repr(digest)+':raise ValueError("CLOSED_RELEASE_MANIFEST_CHANGED")\n'
        'for name,expected in json.loads(raw)["files"].items():\n'
        '    rel=Path(name)\n'
        '    if rel.is_absolute() or ".." in rel.parts:raise ValueError("CLOSED_RELEASE_PATH_INVALID")\n'
        '    p=root/rel\n'
        '    if any(q.is_symlink() for q in [p,*p.parents]) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError("CLOSED_RELEASE_INPUT_CHANGED")\n'
        'identity=runpy.run_path(str(root/"rehearse.py"),run_name="closed_runtime_identity")\n'
        'identity["verify_runtime_payload"](root)\n'
        'runpy.run_path(str(root/"closed_worker_launcher.py"),run_name="__main__")\n').encode()


def bound_inputs(plan):
    for name,digest in plan['bindings'].items():need(sha(regular(Path(name)))==digest,'APPROVED_INPUT_CHANGED: '+Path(name).name)
    source=Path(plan['source_bundle']);raw=regular(source/'RELEASE-MANIFEST.json')
    need(sha(raw)==plan['release_manifest_sha256'],'SOURCE_BUNDLE_MANIFEST_CHANGED');verify(source,json.loads(raw))
    config=json.loads(regular(source/'CLOSED-REGISTRATION.json'))
    need(config['mode']=='CLOSED_PREPARATION_ONLY' and config['production_execution_enabled'] is False
        and config['execution_factory_configured'] is False,'EXACT_CLOSED_REGISTRATION_REQUIRED')


def check_plan(plan):
    root=Path(plan['repo']);destination=Path(plan['destination'])
    need(plan['model']=='HILEGA_GROUP1_EXACT_CLOSED_ROLLOUT_V1' and plan['production_execution_enabled'] is False,'EXACT_CLOSED_PLAN_REQUIRED')
    need(destination==root/'data/runtime/hilega-closed-releases'/plan['release_manifest_sha256'],'EXACT_IMMUTABLE_DESTINATION_REQUIRED')
    need(plan['new_worker_sha256']==sha(wrapper(destination,plan['release_manifest_sha256'])),'EXACT_WRAPPER_REQUIRED')
    for p in [root/TARGET,destination,*destination.parents]:need(not p.is_symlink(),'SYMLINK_ROLLOUT_PATH_FORBIDDEN')
    return root,destination


def stopped(manager):
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in UNITS),'ALL_SIX_SERVICES_MUST_BE_STOPPED')


def apply(plan,folder,manager,*,quiescence=no_unmanaged_python,checkpoint=lambda at:None):
    root,destination=check_plan(plan);bound_inputs(plan)
    need(not (folder/'TRANSACTION.json').exists(),'ROLLOUT_ALREADY_STARTED')
    reuse=destination.exists()
    if reuse:
        existing=regular(destination/'RELEASE-MANIFEST.json')
        need(sha(existing)==plan['release_manifest_sha256'],'EXISTING_IMMUTABLE_BUNDLE_DIFFERS')
        verify(destination,json.loads(existing))
    need(sha(regular(root/TARGET))==plan['old_worker_sha256'],'INSTALLED_WORKER_CHANGED')
    require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    before={u:manager.state(u) for u in UNITS};need(all(s['active']=='active' and s['pid']>0 for s in before.values()),'ALL_SIX_SERVICES_MUST_BE_ACTIVE_BEFORE_MAINTENANCE')
    need(before[UNITS[0]]['active']=='active','SOURCE_WORKER_MUST_BE_RUNNING_BEFORE_MAINTENANCE')
    tx=dict(phase='STOPPING',before=before,production_execution_enabled=False);save(folder/'TRANSACTION.json',tx)
    for u in UNITS:
        if before[u]['active']=='active':manager.control('stop',u)
    stopped(manager);quiescence(root);bound_inputs(plan)
    require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    backup=folder/'backups';backup.mkdir(mode=0o700)
    backup_database(Path(plan['application_db']),backup/'application.sqlite')
    backup_database(Path(plan['adapter_db']),backup/'adapter.sqlite')
    old=regular(root/TARGET);need(sha(old)==plan['old_worker_sha256'],'WORKER_CHANGED_BEFORE_BACKUP')
    atomic(backup/'worker.old',old,0o600)
    tx['phase']='BACKED_UP_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx);checkpoint('AFTER_REAL_BACKUPS')
    source=Path(plan['source_bundle']);manifest=json.loads(regular(source/'RELEASE-MANIFEST.json'))
    if not reuse:
        destination.mkdir(parents=True,mode=0o700)
        for name,digest in manifest['files'].items():
            rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_BUNDLE_PATH_REQUIRED')
            data=regular(source/rel);need(sha(data)==digest,'SOURCE_BUNDLE_CHANGED_DURING_INSTALL')
            target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);atomic(target,data,0o600)
        atomic(destination/'RELEASE-MANIFEST.json',regular(source/'RELEASE-MANIFEST.json'),0o600)
    verify(destination,manifest)
    tx['phase']='INSTALLING_WRAPPER_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    atomic(root/TARGET,wrapper(destination,plan['release_manifest_sha256']),plan['worker_mode']);checkpoint('AFTER_WORKER_WRAPPER')
    tx['phase']='INSTALLED_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx);return tx


def read_health(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        h=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
    need(c['mode']=='PAUSED','CONTROLLER_LEFT_PAUSED_MODE');return h


def wait_health(path,previous,manager,active,*,timeout=60):
    deadline=time.monotonic()+timeout;first=None
    while time.monotonic()<deadline:
        need(all(manager.state(u)['active']=='active' and manager.state(u)['pid']>0 for u in active),'SERVICE_EXITED_DURING_STARTUP')
        row=read_health(path)
        if row.get('run_id')!=previous and row.get('phase') in {'ERROR','STOPPED'}:raise ValueError('NEW_WORKER_ERROR_OR_STOPPED')
        at=datetime.fromisoformat(row['heartbeat_at'])
        valid=row.get('pid')==manager.state(UNITS[0])['pid'] and row.get('run_id')!=previous and row.get('phase')=='RUNNING' and not row.get('problem') and at.tzinfo is not None and 0<=(datetime.now(timezone.utc)-at).total_seconds()<=30
        if valid:
            if first and first[0]==row['run_id'] and row['heartbeat_at']>first[1]:return
            first=first or (row['run_id'],row['heartbeat_at'])
        time.sleep(1)
    raise ValueError('BOUNDED_NEW_LEASE_HEARTBEAT_TIMEOUT')


def wait_inventory(root,*,timeout=30):
    from managed_processes import inspect
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            inventory=inspect(root)
            if all(r['state']=='MATCHED_RUNNING' for r in inventory['records']):return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise ValueError('API_WORKER_PID_RECORDS_NOT_READY')


def start(plan,folder,manager,*,inventory=wait_inventory,healthcheck=wait_health):
    root,destination=check_plan(plan);bound_inputs(plan);tx=json.loads(regular(folder/'TRANSACTION.json'))
    restoring=tx['phase']=='ROLLED_BACK_SERVICES_STOPPED'
    need(restoring or tx['phase'] in {'INSTALLED_SERVICES_STOPPED','STARTUP_FAILED_SERVICES_STOPPED'},'START_PHASE_REQUIRES_REVIEW')
    need(sha(regular(root/TARGET))==(plan['old_worker_sha256'] if restoring else plan['new_worker_sha256']),'START_WORKER_HASH_CHANGED')
    if not restoring:verify(destination,json.loads(regular(destination/'RELEASE-MANIFEST.json')))
    stopped(manager);require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    old_lease=read_health(Path(plan['application_db']))['run_id'];active=[u for u in UNITS if tx['before'][u]['active']=='active']
    started=[]
    try:
        for u in reversed(UNITS[1:]):
            if u in active:started.append(u);manager.control('start',u)
        inventory(root) # Avoid the earlier API/worker PID-record startup race.
        started.append(UNITS[0]);manager.control('start',UNITS[0])
        healthcheck(Path(plan['application_db']),old_lease,manager,active)
        require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    except BaseException:
        for u in UNITS:
            if u in started:manager.control('stop',u)
        tx['phase']='STARTUP_FAILED_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx);raise
    tx['phase']='ROLLED_BACK_RUNNING' if restoring else 'CLOSED_BUNDLE_RUNNING';save(folder/'TRANSACTION.json',tx);return tx


def hold(plan,folder,manager):
    tx=json.loads(regular(folder/'TRANSACTION.json'))
    for u in UNITS:
        if manager.state(u)['active']!='inactive':manager.control('stop',u)
    stopped(manager)
    if tx['phase']=='CLOSED_BUNDLE_RUNNING':tx['phase']='INSTALLED_SERVICES_STOPPED'
    elif tx['phase']=='ROLLED_BACK_RUNNING':tx['phase']='ROLLED_BACK_SERVICES_STOPPED'
    save(folder/'TRANSACTION.json',tx);return tx


def rollback(plan,folder,manager,*,quiescence=no_unmanaged_python):
    root,_=check_plan(plan);stopped(manager);quiescence(root);tx=json.loads(regular(folder/'TRANSACTION.json'))
    need(tx['phase'] in {'BACKED_UP_SERVICES_STOPPED','INSTALLING_WRAPPER_SERVICES_STOPPED','INSTALLED_SERVICES_STOPPED',
        'STARTUP_FAILED_SERVICES_STOPPED','ROLLED_BACK_SERVICES_STOPPED'},'ROLLBACK_PHASE_REQUIRES_REVIEW')
    old=regular(folder/'backups/worker.old');need(sha(old)==plan['old_worker_sha256'],'OLD_WORKER_BACKUP_CHANGED')
    need(sha(regular(root/TARGET)) in {plan['old_worker_sha256'],plan['new_worker_sha256']},'EXTERNAL_WORKER_CHANGE_BLOCKS_ROLLBACK')
    atomic(root/TARGET,old,plan['worker_mode']);tx['phase']='ROLLED_BACK_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    return tx # Retain bundle and DB backups; never rewind live cursors automatically.
