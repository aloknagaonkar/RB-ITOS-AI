"""Reviewed three-file CLOSED hook rollout. Production execution is never enabled."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import time

TARGETS=('scripts/hilega_production_simulator_bridge.py','backend/market_lab/hilega_preparation_runtime_v1/source.py',
 'backend/market_lab/hilega_exclusive_closed_route_v1.py')
UNITS=('hilega-production-source-worker.service','hilega-worker.service','hilega-api.service',
 'hilega-lifecycle-reference.service','hilega-observation-analytics.service','hilega-observation-readiness.service')


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def regular(path):
    path=Path(path)
    need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_ABSOLUTE_FILE_REQUIRED')
    return path.read_bytes()


def save(path,value):
    data=(json.dumps(value,indent=2,sort_keys=True)+'\n').encode();atomic(path,data,0o600)


def atomic(path,data,mode):
    need(not path.is_symlink(),'SYMLINK_TARGET_FORBIDDEN')
    temp=path.with_name(path.name+'.rollout-new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temp.exists():temp.unlink()


def target(root,name):
    need(name in TARGETS,'EXACT_CLOSED_TARGET_REQUIRED');path=root/name
    need(not any(p.is_symlink() for p in [path,*path.parents]),'SYMLINK_TARGET_FORBIDDEN')
    need(path.resolve().is_relative_to(root),'TARGET_ESCAPES_REPOSITORY');return path


def require_empty_closed_baseline(app,adapter):
    need(app.resolve()!=adapter.resolve(),'DISTINCT_DATABASES_REQUIRED')
    for kind,path in [('application',app),('adapter',adapter)]:
        need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_DATABASE_REQUIRED')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            need(db.execute('PRAGMA journal_mode').fetchone()[0]=='delete','DELETE_JOURNAL_REQUIRED')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            need(not {'preparation_candidate_exclusive_source_owner_v1','preparation_candidate_coordinator_state_v1'}&tables,
                 'EXISTING_OWNER_STATE_REQUIRES_MIGRATION')
            if kind=='application':
                c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
                stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
                need(c['mode']=='PAUSED' and stop and stop[0]==stop[1],'PAUSED_NO_PENDING_STOP_REQUIRED')
                checked=('intents','sim_orders','sim_fills','sim_allocation_reservations','preparation_plans',
                    'preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations')
            else:
                meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
                need(meta['mode']=='LIVE_CLOSED','CLOSED_ADAPTER_REQUIRED');checked=('requests','attempts','receipts')
            for table in checked:
                if table in tables:need(db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() is None,'NONEMPTY_LIFECYCLE_REQUIRES_REVIEW')
            db.rollback()


class Systemd:
    def state(self,unit):
        need(unit in UNITS,'EXACT_MANAGED_UNIT_REQUIRED')
        r=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,SubState,MainPID'],capture_output=True,text=True,timeout=15)
        need(r.returncode==0,'SERVICE_QUERY_FAILED')
        fields=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
        return dict(active=fields.get('ActiveState'),sub=fields.get('SubState'),pid=int(fields.get('MainPID','-1')))

    def control(self,action,unit):
        need(action in {'stop','start'} and unit in UNITS,'EXACT_SERVICE_ACTION_REQUIRED')
        r=subprocess.run(['systemctl','--user',action,unit],capture_output=True,timeout=45)
        need(r.returncode==0,'MANAGED_SERVICE_ACTION_FAILED')


def no_unmanaged_python(repo):
    repo=repo.resolve();python=str(repo/'.venv/bin/python')
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name)==os.getpid():continue
        try:
            if entry.stat().st_uid!=os.getuid():continue
            argv=(entry/'cmdline').read_bytes().split(b'\0');first=argv[0].decode(errors='replace')
            if first==python and (entry/'cwd').resolve()==repo:raise ValueError('UNMANAGED_REPOSITORY_PYTHON_REMAINS')
            script=str(repo/'scripts/hilega_production_simulator_bridge.py').encode()
            need(script not in argv,'UNMANAGED_SOURCE_WORKER_REMAINS')
        except (FileNotFoundError,ProcessLookupError):continue
        except PermissionError:raise ValueError('PROCESS_QUIESCENCE_NOT_VERIFIABLE')


def backup_database(source,destination):
    need(not destination.exists(),'BACKUP_TARGET_ALREADY_EXISTS')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=3)) as src,closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        need(dst.execute('PRAGMA quick_check').fetchone()[0]=='ok','DATABASE_BACKUP_CHECK_FAILED')
    destination.chmod(0o600)


def apply(plan,folder,manager,*,quiescence=no_unmanaged_python,checkpoint=lambda at:None):
    root=Path(plan['repo']);stage=Path(plan['stage']);folder=Path(folder)
    need(plan['model']=='HILEGA_APPROVABLE_CLOSED_ROLLOUT_V1' and plan['production_execution_enabled'] is False,'EXACT_CLOSED_PLAN_REQUIRED')
    need([e['name'] for e in plan['files']]==list(TARGETS),'EXACT_CLOSED_FILES_REQUIRED')
    need(not (folder/'TRANSACTION.json').exists(),'ROLLOUT_TRANSACTION_ALREADY_EXISTS')
    for e in plan['files']:
        path=target(root,e['name']);current=sha(regular(path)) if path.exists() else None
        need(current==e['old_sha256'] and sha(regular(stage/e['name']))==e['new_sha256'],'ROLLOUT_SOURCE_CHANGED')
    before={u:manager.state(u) for u in UNITS}
    need(all(s['active'] in {'active','inactive'} for s in before.values()),'SERVICES_NOT_IN_STABLE_STATE')
    tx=dict(phase='STOPPING',files=plan['files'],before=before,repo=str(root),production_execution_enabled=False)
    save(folder/'TRANSACTION.json',tx)
    # Deliberately no automatic restart on an error: recovery must inspect partial work.
    for unit in UNITS:
        if before[unit]['active']=='active':manager.control('stop',unit)
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in UNITS),'SERVICES_NOT_STOPPED')
    quiescence(root);require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    tx['phase']='BACKING_UP';save(folder/'TRANSACTION.json',tx)
    backup=folder/'backups';backup.mkdir(mode=0o700)
    backup_database(Path(plan['application_db']),backup/'application.sqlite')
    backup_database(Path(plan['adapter_db']),backup/'adapter.sqlite')
    for i,e in enumerate(plan['files']):
        p=target(root,e['name'])
        if e['old_sha256'] is not None:
            need(sha(regular(p))==e['old_sha256'],'ORIGINAL_CHANGED_BEFORE_BACKUP')
            atomic(backup/(str(i)+'.old'),regular(p),0o600)
    tx['phase']='INSTALLING';save(folder/'TRANSACTION.json',tx)
    for i,e in enumerate(plan['files']):
        path=target(root,e['name']);need(path.parent.is_dir(),'TARGET_PARENT_REQUIRED')
        need(sha(regular(stage/e['name']))==e['new_sha256'],'CANDIDATE_CHANGED_BEFORE_INSTALL')
        atomic(path,regular(stage/e['name']),e['mode']);checkpoint('AFTER_FILE_'+str(i+1))
    tx['phase']='INSTALLED_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    return tx


def rollback(folder,manager,*,quiescence=no_unmanaged_python):
    folder=Path(folder);tx=json.loads(regular(folder/'TRANSACTION.json'));root=Path(tx['repo'])
    need(tx['phase'] in {'INSTALLING','INSTALLED_SERVICES_STOPPED','ROLLED_BACK_SERVICES_STOPPED','STARTUP_FAILED_SERVICES_STOPPED'},'ROLLBACK_PHASE_REQUIRES_REVIEW')
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in UNITS),'SERVICES_NOT_STOPPED')
    quiescence(root)
    for i,e in enumerate(tx['files']):
        p=target(root,e['name']);current=sha(regular(p)) if p.exists() else None
        need(current in {e['old_sha256'],e['new_sha256']},'EXTERNAL_FILE_CHANGE_BLOCKS_ROLLBACK')
        if e['old_sha256'] is not None:need(sha(regular(folder/'backups'/(str(i)+'.old')))==e['old_sha256'],'CODE_BACKUP_CHANGED')
    for i,e in reversed(list(enumerate(tx['files']))):
        p=target(root,e['name'])
        if e['old_sha256'] is None:
            if p.exists():p.unlink()
        else:atomic(p,regular(folder/'backups'/(str(i)+'.old')),e['mode'])
    tx['phase']='ROLLED_BACK_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx)
    # Database backups are retained; never rewind live cursors automatically.
    return tx


def closed_health(root,previous_run_hash):
    from datetime import datetime,timezone
    app=Path(root)
    with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        row=db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
        need(row is not None,'BRIDGE_HEALTH_REQUIRED');health=json.loads(row[0])
        need(control['mode']=='PAUSED','CONTROLLER_MUST_REMAIN_PAUSED')
        need(health.get('phase')=='RUNNING' and not health.get('problem'),'SOURCE_WORKER_HEALTH_ERROR')
        at=datetime.fromisoformat(health['heartbeat_at'])
        need(at.tzinfo is not None and 0<=(datetime.now(timezone.utc)-at).total_seconds()<=30,'NEW_BRIDGE_HEARTBEAT_NOT_CURRENT')
        need(health.get('run_id') and sha(str(health['run_id']).encode())!=previous_run_hash,'NEW_BRIDGE_LEASE_REQUIRED')
        db.rollback()


def start(folder,manager,*,healthcheck=closed_health):
    folder=Path(folder);tx=json.loads(regular(folder/'TRANSACTION.json'));plan=json.loads(regular(folder/'PLAN.json'))
    need(tx['phase'] in {'INSTALLED_SERVICES_STOPPED','ROLLED_BACK_SERVICES_STOPPED'},'START_PHASE_REQUIRES_REVIEW')
    root=Path(tx['repo']);restoring=tx['phase']=='ROLLED_BACK_SERVICES_STOPPED'
    for e in tx['files']:
        p=target(root,e['name']);actual=sha(regular(p)) if p.exists() else None
        need(actual==(e['old_sha256'] if restoring else e['new_sha256']),'START_CODE_HASH_CHANGED')
    require_empty_closed_baseline(Path(plan['application_db']),Path(plan['adapter_db']))
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in UNITS),'SERVICES_NOT_STOPPED')
    started=[]
    try:
        for unit in reversed(UNITS):
            if tx['before'][unit]['active']=='active':
                started.append(unit);manager.control('start',unit)
        for _ in range(20):
            if all(manager.state(u)['active']=='active' and manager.state(u)['pid']>0 for u in started):break
            time.sleep(.5)
        need(all(manager.state(u)['active']=='active' and manager.state(u)['pid']>0 for u in started),'RESTORED_SERVICES_NOT_ACTIVE')
        need(UNITS[0] in started,'SOURCE_SERVICE_WAS_NOT_PREVIOUSLY_ACTIVE')
        healthcheck(Path(plan['application_db']),plan['previous_bridge_run_hash'])
    except BaseException:
        for unit in UNITS:
            if unit in started:manager.control('stop',unit)
        tx['phase']='STARTUP_FAILED_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx);raise
    tx['phase']='ROLLED_BACK_RUNNING' if restoring else 'CLOSED_HOOK_RUNNING';save(folder/'TRANSACTION.json',tx)
    return tx


def hold(folder,manager):
    folder=Path(folder);tx=json.loads(regular(folder/'TRANSACTION.json'))
    for unit in UNITS:
        if manager.state(unit)['active']!='inactive':manager.control('stop',unit)
    need(all(manager.state(u)['active']=='inactive' and manager.state(u)['pid']==0 for u in UNITS),'SERVICES_NOT_STOPPED')
    if tx['phase']=='CLOSED_HOOK_RUNNING':tx['phase']='INSTALLED_SERVICES_STOPPED'
    elif tx['phase']=='ROLLED_BACK_RUNNING':tx['phase']='ROLLED_BACK_SERVICES_STOPPED'
    save(folder/'TRANSACTION.json',tx);return tx


def cancel_before_install(folder,manager):
    folder=Path(folder);tx=hold(folder,manager);root=Path(tx['repo'])
    need(tx['phase'] in {'STOPPING','BACKING_UP'},'CANCEL_ONLY_BEFORE_INSTALL')
    for e in tx['files']:
        p=target(root,e['name']);actual=sha(regular(p)) if p.exists() else None
        need(actual==e['old_sha256'],'ORIGINAL_CODE_CHANGED')
    tx['phase']='ROLLED_BACK_SERVICES_STOPPED';save(folder/'TRANSACTION.json',tx);return tx
