"""Staged Source ownership. No CLI factory, enable flag, takeover or live clearance."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import fcntl
from functools import wraps
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import sys

TABLE='preparation_candidate_exclusive_source_owner_v1'
MODEL='HILEGA_EXCLUSIVE_CLOSED_SOURCE_OWNER_V1'
STAGED_SOURCE_SHA256='d451edda4f7f28bfa38d2e095a543d4e36b83b9484027fb1ddff1375464b22e2'
_HELD=ContextVar('hilega_exclusive_source_lock',default=None)
_PERMISSION=ContextVar('hilega_exclusive_source_permission',default=None)


def need(ok,reason):
    if not ok:raise ValueError(reason)


def closed(status):
    return dict(status=status,source_at=None,entry_permission=False,orders_sent_to_upstox=False,
        production_execution_enabled=False,reservation_release_permission=False)


@contextmanager
def route_lock(path):
    key=str(Path(path).resolve())
    if _HELD.get()==key:
        yield
        return
    need(_HELD.get() is None,'NESTED_DIFFERENT_SOURCE_ROUTES_FORBIDDEN')
    fd=os.open(key+'.exclusive-source-route.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    token=None
    try:
        info=os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
             and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_SOURCE_ROUTE_LOCK_REQUIRED')
        fcntl.flock(fd,fcntl.LOCK_EX);token=_HELD.set(key);yield
    finally:
        if token is not None:_HELD.reset(token)
        os.close(fd)


def _owner(db):
    exists=db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(TABLE,)).fetchone()
    if not exists:return False,None
    rows=db.execute('SELECT id,data FROM '+TABLE).fetchall()
    need(len(rows)==1 and rows[0][0]==1,'SOURCE_OWNER_MISSING_OR_AMBIGUOUS_NO_REBASELINE')
    return True,json.loads(rows[0][1])


def _guarded_source(source):
    from market_lab.hilega_preparation_runtime_v1.source import Source
    need(type(source) is Source and getattr(Source.run_source_once,'exclusive_source_guard',False),
         'STAGED_GUARDED_SOURCE_REQUIRED')
    path=Path(sys.modules[Source.__module__].__file__)
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest()==STAGED_SOURCE_SHA256,
         'STAGED_SOURCE_VERSION_CHANGED')


def _binding(session):
    return dict(application=str(session.app.path.resolve()),adapter=str(session.adapter.store.path.resolve()),
        journal=str(session.journal.resolve()),seed_request_id=session.seed,account_scope=session.pin['scope'],
        bridge_run_id=session.bridge,authority_id=session.authority['authority_id'],
        guarded_source_sha256=STAGED_SOURCE_SHA256,
        guard_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def _verify(session,row):
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
    value=deepcopy(row);signature=value.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(value,session.pin),signature),
         'SOURCE_OWNER_SIGNATURE_INVALID')
    need(row.get('model')==MODEL and row.get('binding')==_binding(session)
         and all(row.get(k) is False for k in ('entry_permission','production_execution_enabled',
             'orders_sent_to_upstox','reservation_release_permission')),'SOURCE_OWNER_BINDING_CHANGED')
    return row


def _session(session):
    from closed_application_coordinator_v1 import CandidateSession
    need(type(session) is CandidateSession,'EXACT_CANDIDATE_SESSION_REQUIRED')
    session._runtime();_guarded_source(session.source)


def enroll_candidate_route(session,*,checkpoint=lambda at:None):
    """Explicit Python candidate enrollment only. Caller must quiesce old workers for deployment."""
    _session(session)
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
    from market_lab.hilega_production_simulator_bridge_v1 import verified_records
    with route_lock(session.app.path),session.app.lock(),session.app.db() as db:
        db.execute('BEGIN IMMEDIATE');exists,old=_owner(db)
        if exists:
            _verify(session,old)
            return dict(status='EXCLUSIVE_SOURCE_OWNER_REPLAY',idempotent_replay=True,production_execution_enabled=False)
        control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        need(control['mode']=='PAUSED' and control['reason']=='APPLICATION_UNSENT_PREPARATION_REQUIRES_REVIEW'
             and stop and stop[0]==stop[1],'PAUSED_PREPARATION_ENROLLMENT_REQUIRED')
        raw=db.execute('SELECT data FROM preparation_plans WHERE id=?',(session.seed,)).fetchone()
        need(raw is not None,'EXPLICIT_PREPARED_SEED_REQUIRED')
        plan=json.loads(raw[0]);cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
        records=verified_records(session.journal)
        need(plan['account_scope']==session.pin['scope'] and cursor['path']==str(session.journal.resolve())
             and cursor['sequence']==plan['source_sequence'] and cursor['hash']==plan['source_record_hash']
             and 1<=cursor['sequence']<=len(records)
             and records[cursor['sequence']-1]['record_hash']==cursor['hash'],'EXACT_SEED_SOURCE_CURSOR_REQUIRED')
        need(db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0]==1,
             'SINGLE_PREPARED_SOURCE_SEED_REQUIRED')
        row=dict(model=MODEL,binding=_binding(session),enrolled_cursor=cursor,
            entry_permission=False,orders_sent_to_upstox=False,reservation_release_permission=False,
            production_execution_enabled=False)
        row['signature']=sign(row,session.pin)
        db.execute('CREATE TABLE '+TABLE+'(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
        db.execute('INSERT INTO '+TABLE+' VALUES(1,?)',(json.dumps(row,sort_keys=True),))
        checkpoint('BEFORE_SOURCE_OWNER_COMMIT')
        return dict(status='EXCLUSIVE_CLOSED_SOURCE_ENROLLED',idempotent_replay=False,production_execution_enabled=False)


def exclusive_source_guard(function):
    @wraps(function)
    def guarded(source,path):
        _guarded_source(source)
        need(source.s.store.path.is_file() and not source.s.store.path.is_symlink(),'REGULAR_SOURCE_DATABASE_REQUIRED')
        with route_lock(source.s.store.path):
            with source.s.store.db() as db:exists,row=_owner(db)
            if exists:
                permission=_PERMISSION.get()
                if permission is None:return closed('COORDINATOR_OWNS_SOURCE_ROUTE_CLOSED')
                session,expected=permission
                need(source is session.source,'SOURCE_ROUTE_CONTEXT_CHANGED')
                _verify(session,row)
                need(row==expected,'SOURCE_OWNER_CHANGED_DURING_POLL')
                need(Path(path).resolve()==session.journal.resolve(),'SOURCE_ROUTE_JOURNAL_CHANGED')
                from closed_application_coordinator_v1 import STATE
                with source.s.store.db() as db:
                    raw=db.execute('SELECT data FROM '+STATE+' WHERE id=1').fetchone()
                need(raw is not None and session._verify(json.loads(raw[0]))['phase']=='WAIT_EXIT',
                     'SOURCE_ONLY_DURING_COORDINATOR_EXIT_PHASE')
            else:
                need(_PERMISSION.get() is None,'SOURCE_OWNER_DISAPPEARED')
            return function(source,path)
    guarded.exclusive_source_guard=True
    return guarded


def candidate_poll(session):
    """Single route owner around coordinator tick, including nested Source EXIT dispatch."""
    _session(session)
    from closed_application_coordinator_v1 import worker_tick
    with route_lock(session.app.path):
        with session.app.db() as db:exists,row=_owner(db)
        need(exists,'EXCLUSIVE_SOURCE_ENROLLMENT_REQUIRED');_verify(session,row)
        token=_PERMISSION.set((session,deepcopy(row)))
        try:return worker_tick(session)
        finally:_PERMISSION.reset(token)


def closed_poll(bridge,journal):
    """Actual staged worker call. No execution session is constructed here."""
    from market_lab.hilega_preparation_runtime_v1.source import Source
    from market_lab.hilega_production_simulator_bridge_v1 import Bridge
    need(type(bridge) in {Source,Bridge},'EXACT_APPLICATION_BRIDGE_REQUIRED')
    if type(bridge) is Source:_guarded_source(bridge)
    return bridge.run_source_once(journal)


def exclusive_coordinator_guard(function):
    @wraps(function)
    def guarded(session):
        _session(session)
        with route_lock(session.app.path):
            with session.app.db() as db:exists,row=_owner(db)
            if exists:
                permission=_PERMISSION.get()
                if permission is None:
                    return dict(closed('COORDINATOR_REQUIRES_EXCLUSIVE_ROUTE_CONTEXT'),application_database_opened=True)
                permitted,expected=permission
                need(permitted is session,'COORDINATOR_ROUTE_CONTEXT_CHANGED')
                _verify(session,row);need(row==expected,'SOURCE_OWNER_CHANGED_DURING_POLL')
            else:need(_PERMISSION.get() is None,'SOURCE_OWNER_DISAPPEARED')
            output=function(session)
            output=dict(output);output['application_database_opened']=True
            return output
    guarded.exclusive_coordinator_guard=True
    return guarded
