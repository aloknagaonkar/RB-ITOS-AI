"""Simulator bridge lease and freshness evidence. No broker transport or arming."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import fcntl,json,os,re,uuid

MODEL='HILEGA_SIMULATOR_BRIDGE_HEALTH_V1'
HEARTBEAT_SECONDS=15
SOURCE_SECONDS=390

class HealthBlocked(ValueError):pass

def aware(v):
    t=datetime.fromisoformat(v)
    if t.tzinfo is None:raise ValueError('AWARE_TIME_REQUIRED')
    return t

def _row(store):
    with store.db() as d:
        r=d.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
    return json.loads(r[0]) if r else None

def _write(store,row):
    with store.db() as d:d.execute('INSERT OR REPLACE INTO sim_bridge_health VALUES(1,?)',(json.dumps(row,sort_keys=True,allow_nan=False),))

def effective(row,at):
    enabled=os.getenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')=='1'
    base=dict(model=MODEL,required=bool(enabled or row),status='NOT_STARTED' if enabled else 'NOT_ENABLED',
              healthy=False,heartbeat_age_seconds=None,source_age_seconds=None,pid=None,instance=None,
              last_heartbeat_at=None,source_at=None,production_execution_enabled=False,
              heartbeat_limit_seconds=HEARTBEAT_SECONDS,source_limit_seconds=SOURCE_SECONDS)
    if row is None:return base
    if row.get('model')!=MODEL or row.get('required') is not True:raise ValueError('HEALTH_ROW_INVALID')
    base.update(required=True,pid=row['pid'],instance=row['run_id'][:8],last_heartbeat_at=row['heartbeat_at'],
                source_at=row.get('source_at'),phase=row['phase'])
    age=(at-aware(row['heartbeat_at'])).total_seconds();base['heartbeat_age_seconds']=round(age,3)
    if row['phase']=='STOPPED':base['status']='STOPPED';return base
    if row['phase']=='ERROR':base.update(status='WORKER_ERROR',problem=row.get('problem'));return base
    if row['session_date']!=at.date().isoformat():base['status']='SESSION_MISMATCH';return base
    if age<0:base['status']='CLOCK_OR_FUTURE_HEARTBEAT';return base
    if age>HEARTBEAT_SECONDS:base['status']='HEARTBEAT_STALE';return base
    if row['phase']!='RUNNING':base['status']='STARTING';return base
    source=row.get('source_at')
    if source is None:base['status']='SOURCE_NOT_READY';return base
    source_time=aware(source).astimezone(at.tzinfo);source_age=(at-source_time).total_seconds()
    base['source_age_seconds']=round(source_age,3)
    if source_time.date()!=at.date():base['status']='SOURCE_SESSION_MISMATCH';return base
    if not 0<=source_age<=SOURCE_SECONDS:base['status']='SOURCE_STALE_OR_FUTURE';return base
    base.update(status='HEALTHY',healthy=True);return base

def summary(store,at):
    try:return effective(_row(store),at)
    except Exception:
        return dict(model=MODEL,required=True,status='HEALTH_UNAVAILABLE',healthy=False,pid=None,instance=None,
                    heartbeat_age_seconds=None,source_age_seconds=None,production_execution_enabled=False)

@contextmanager
def worker_lock(db_path):
    """Kernel releases this lock after a crash; a second worker cannot take over live."""
    path=Path(str(db_path)+'.bridge-worker.lock');path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(fd,'a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise HealthBlocked('SIM_BRIDGE_WORKER_ALREADY_RUNNING') from None
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)

def claim(service):
    with service.store.lock():
        at=service.now();run=uuid.uuid4().hex
        service._block('SIM_BRIDGE_START_REQUIRES_EXPLICIT_RESUME')
        _write(service.store,dict(model=MODEL,required=True,run_id=run,pid=os.getpid(),phase='STARTING',
            heartbeat_at=at.isoformat(),session_date=at.date().isoformat(),source_at=None))
        service.store.event('SIM_BRIDGE_HEALTH_CLAIMED',at.isoformat(),instance=run[:8],pid=os.getpid())
        return run

def heartbeat(service,run_id,*,source_at,problem=None):
    with service.store.lock():
        row=_row(service.store)
        if row is None or row.get('run_id')!=run_id:raise HealthBlocked('SIM_BRIDGE_LEASE_REPLACED')
        at=service.now();before=effective(row,at)['status']
        if source_at is not None:aware(source_at)
        if problem is not None and (not isinstance(problem,str) or not re.fullmatch(r'[A-Z0-9_]{1,100}',problem)):problem='WORKER_ERROR'
        row.update(phase='ERROR' if problem else 'RUNNING',heartbeat_at=at.isoformat(),source_at=source_at,problem=problem)
        _write(service.store,row);after=effective(row,at)
        if before!=after['status']:
            service.store.event('SIM_BRIDGE_HEALTH_CHANGED',at.isoformat(),before=before,after=after['status'],instance=run_id[:8])
        return after

def finish(service,run_id):
    with service.store.lock():
        row=_row(service.store)
        if row is None or row.get('run_id')!=run_id:return False
        row.update(phase='STOPPED',heartbeat_at=service.now().isoformat());_write(service.store,row)
        service._block('SIM_BRIDGE_PROCESS_STOPPED')
        service._reconcile() # cancel pending simulator BUYs; keep established positions
        service.store.event('SIM_BRIDGE_HEALTH_STOPPED',service.now().isoformat(),instance=run_id[:8])
        return True

def assert_ready(store,at,*,run_id=None,submitting=False):
    state=summary(store,at)
    if not state['required']:return
    if not state['healthy']:raise HealthBlocked('SIM_BRIDGE_'+state['status'])
    if submitting:
        row=_row(store)
        if run_id is None or row is None or row.get('run_id')!=run_id:raise HealthBlocked('SIM_BRIDGE_LEASE_MISMATCH')

def source_timestamp(records,policy,version):
    latest=None
    for record in records:
        if record.get('stage') not in {'DIRECTIONAL_DECISION','COMBINED_PRICE_OBSERVATION','DIRECTIONAL_SESSION_CUTOFF'} or record.get('status')!='PROCESSED':continue
        p=record.get('payload') or {}
        if p.get('policy_id')!=policy or p.get('strategy_version')!=version or p.get('reconstructed') is True:continue
        value=p.get('decision_timestamp') or p.get('cutoff_timestamp')
        if value:
            t=aware(value)
            if latest is None or t>aware(latest):latest=value
    return latest
