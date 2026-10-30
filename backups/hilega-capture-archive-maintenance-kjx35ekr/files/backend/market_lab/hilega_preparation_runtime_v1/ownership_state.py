"""Durable read-only entry attestations; never execution or release authority."""
from contextlib import closing,ExitStack
from datetime import datetime,timezone
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from .ownership_checks.ownership_review import reconcile_entry
from .ownership_checks.risk_evidence_audit import read_connection,regular,need
from .ownership_checks.historical_receipt_checks import sha
from .ownership_checks.signature_checks import sign,verify,aware,day

MODEL='HILEGA_APPLICATION_ENTRY_OWNERSHIP_STATE_V1'
CURRENT='preparation_entry_ownership_state'
HISTORY='preparation_entry_ownership_reviews'
AUDIT='preparation_entry_ownership_audit'
FALSE_FLAGS=('entry_permission','exit_submission_permission','orders_sent',
    'production_execution_enabled','reservation_release_permission',
    'strategy_ownership_verified','risk_gate_input_ready')


def load_pin():
    from market_lab.hilega_production_account_adapter_v1 import read_pin
    return read_pin(Path(os.getenv('HILEGA_PREPARATION_PIN_FILE',
        str(Path.home()/'hilega-private/upstox-account-pin.json'))))


def utcnow():return datetime.now(timezone.utc)


def validate_state(row,pin,mode):
    payload=dict(row);signature=payload.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         'OWNERSHIP_STATE_SIGNATURE_INVALID')
    need(row['model']==MODEL and row['account_scope']==pin['scope']
         and row['evidence_mode']==mode,'OWNERSHIP_STATE_SCOPE_OR_MODE_CHANGED')
    need(all(row.get(k) is False for k in FALSE_FLAGS),'OWNERSHIP_STATE_AUTHORITY_CHANGED')
    q=row['reviewed_entry_quantity']
    need((row['status']=='ENTRY_QUANTITY_RECONCILED' and type(q) is int and q>0)
         or (row['status']=='BLOCKED' and q is None),'OWNERSHIP_STATE_QUANTITY_INVALID')
    return row


def current_row(db,pin,mode):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(CURRENT,)).fetchone():return None
    raw=db.execute('SELECT data FROM '+CURRENT+' WHERE id=1').fetchone()
    return validate_state(json.loads(raw[0]),pin,mode) if raw else None


def rollback_database(path):
    path=regular(path)
    with path.open('rb') as stream:header=stream.read(20)
    need(header[:16]==b'SQLite format 3\x00' and header[18:20]==b'\x01\x01',
         'ROLLBACK_JOURNAL_SOURCE_REQUIRED')
    return path


def record_entry_review(application,adapter,snapshot,pin,*,clock=utcnow,
                        mode='LIVE_CLOSED',checkpoint=lambda stage:None):
    """Recompute under the app write transaction and an attached broker RO snapshot.

    This function has no broker transport. Caller supplies the pinned capture.
    Validation failure invalidates the current attestation in the same transaction.
    Replaying an older capture can never restore an older current state.
    """
    need(mode in {'LIVE_CLOSED','OFFLINE_FIXTURE'},'OWNERSHIP_EVIDENCE_MODE_MISMATCH')
    if mode=='LIVE_CLOSED':
        need(re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']) is not None,'LIVE_UPSTOX_PIN_SCOPE_REQUIRED')
    else:need(pin['scope'].startswith('FIXTURE:'),'EXPLICIT_FIXTURE_SCOPE_REQUIRED')
    app,broker=map(rollback_database,(application,adapter))
    need(not app.samefile(broker),'DISTINCT_DATABASES_REQUIRED')
    with closing(sqlite3.connect(app.as_uri()+'?mode=rw',uri=True,timeout=10)) as db:
        db.execute('ATTACH DATABASE ? AS broker',(broker.as_uri()+'?mode=ro',))
        need(db.execute('PRAGMA main.journal_mode').fetchone()[0]=='delete'
             and db.execute('PRAGMA broker.journal_mode').fetchone()[0]=='delete',
             'DELETE_JOURNAL_REQUIRED')
        db.execute('PRAGMA main.synchronous=FULL');db.execute('BEGIN IMMEDIATE')
        try:
            source=read_connection(db,pin['scope'],expected_mode=mode)
            fingerprint=sha(source);previous=current_row(db,pin,mode)
            now=clock();as_of=aware(now.isoformat()).isoformat()
            db.execute('CREATE TABLE IF NOT EXISTS '+CURRENT+'(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS '+HISTORY+'(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,source_fingerprint TEXT NOT NULL,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS '+AUDIT+'(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL)')
            sid=snapshot.get('snapshot_id') if isinstance(snapshot,dict) else None
            if not isinstance(sid,str) or not sid or len(sid)>200:sid='invalid-'+uuid.uuid4().hex
            try:snapshot_fp=sha(snapshot)
            except Exception:snapshot_fp=sha(dict(invalid_payload=True))
            old=db.execute('SELECT fingerprint,source_fingerprint FROM '+HISTORY+' WHERE id=?',(sid,)).fetchone()
            if old is not None and old==(snapshot_fp,fingerprint):
                db.rollback()
                return dict(status='IDEMPOTENT_CURRENT_STATE_RETURNED',idempotent_replay=True,
                    current_status=previous['status'] if previous else None,
                    orders_sent=False,production_execution_enabled=False,
                    exit_submission_permission=False,reservation_release_permission=False)
            highwater=previous.get('high_water_capture_at') if previous else None
            report=None;reason=None;capture_valid=False
            try:
                need(old is None,'CAPTURE_ID_REUSED_OR_LOCAL_SOURCE_CHANGED')
                verify(snapshot,pin,as_of=as_of);capture_valid=True
                if highwater:
                    need(aware(snapshot['generated_at'])>=aware(highwater),'OUT_OF_ORDER_OWNERSHIP_CAPTURE')
                report=reconcile_entry(source,snapshot,pin,as_of=as_of,mode=mode)
            except Exception as exc:
                text=str(exc)
                reason=text if re.fullmatch(r'[A-Z][A-Z0-9_]{0,179}',text) else 'OWNERSHIP_REVIEW_INVALID'
            passed=report is not None and report['reviewed_remaining_entry_quantity'] is not None
            if capture_valid and (not highwater or aware(snapshot['generated_at'])>aware(highwater)):
                highwater=snapshot['generated_at']
            key=next(iter(source['bindings'])) if passed else None
            plan=source['plans'][key] if passed else None
            row=dict({k:False for k in FALSE_FLAGS},model=MODEL,account_scope=pin['scope'],
                evidence_mode=mode,status='ENTRY_QUANTITY_RECONCILED' if passed else 'BLOCKED',
                assessed_at=as_of,snapshot_id=sid,account_capture_fingerprint=snapshot_fp,
                account_capture_generated_at=snapshot.get('generated_at') if capture_valid else None,
                account_capture_completed_at=snapshot.get('completed_at') if capture_valid else None,
                high_water_capture_at=highwater,source_fingerprint=fingerprint,
                reviewed_entry_quantity=report['reviewed_remaining_entry_quantity'] if passed else None,
                parent_request_id=key,entry_direction=plan['direction'] if passed else None,
                entry_signal_at=plan['signal_at'] if passed else None,
                reasons=report['reasons'] if report else [reason],
                scope='SINGLE_CURRENT_FULLY_FILLED_BUY_ENTRY_READ_ONLY',
                evidence_sources_atomic=False,raw_account_capture_persisted=False,
                fees_complete=False,realized_net_pnl_paise=None,open_net_pnl_paise=None,
                production_ready=False)
            row['signature']=sign(row,pin)
            if old is None:
                db.execute('INSERT INTO '+HISTORY+' VALUES(?,?,?,?)',
                    (sid,snapshot_fp,fingerprint,json.dumps(row,sort_keys=True)))
            checkpoint('AFTER_OWNERSHIP_HISTORY_INSERT')
            db.execute('INSERT OR REPLACE INTO '+CURRENT+' VALUES(1,?)',(json.dumps(row,sort_keys=True),))
            db.execute('INSERT INTO '+AUDIT+'(data) VALUES(?)',(json.dumps(dict(
                status=row['status'],at=as_of,snapshot_fingerprint=snapshot_fp,
                source_fingerprint=fingerprint,orders_sent=False)),))
            checkpoint('BEFORE_OWNERSHIP_COMMIT')
            # Recheck age after SQLite waits and all test interruption hooks.
            if capture_valid:verify(snapshot,pin,as_of=clock().isoformat())
            db.commit()
            return dict(status='OWNERSHIP_RECORD_COMMITTED',record_status=row['status'],
                idempotent_replay=False,reviewed_entry_quantity=row['reviewed_entry_quantity'],
                live_evidence_assessed=mode=='LIVE_CLOSED',database_modified=True,
                orders_sent=False,production_execution_enabled=False,
                exit_submission_permission=False,reservation_release_permission=False,
                production_ready=False)
        except BaseException:
            db.rollback();raise



class SourceReader:
    """Route fixed SELECTs to the caller's app transaction and a broker RO snapshot."""
    def __init__(self,application,broker):self.application=application;self.broker=broker
    def execute(self,sql,parameters=()):
        need(sql.lstrip().upper().startswith('SELECT '),'SOURCE_READER_SELECT_ONLY')
        if 'broker.' in sql:
            need('main.' not in sql,'CROSS_DATABASE_QUERY_UNSUPPORTED')
            return self.broker.execute(sql.replace('broker.','main.'),parameters)
        return self.application.execute(sql,parameters)


def broker_snapshot(path,resources):
    path=rollback_database(path)
    connection=resources.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)))
    connection.execute('PRAGMA query_only=ON')
    need(connection.execute('PRAGMA journal_mode').fetchone()[0]=='delete','ADAPTER_DELETE_JOURNAL_REQUIRED')
    connection.execute('BEGIN')
    resources.callback(connection.rollback)
    return connection


def closed_exit_context(source,db,event,*,now,pin=None,mode='LIVE_CLOSED',resources=None):
    """Informational attestation link only. Every actual exit stays REFUSED_CLOSED.

    No HMAC key is loaded when there is no ownership table. Fixture mode/pin
    injection is used explicitly by tests; the dispatcher calls live defaults.
    """
    if resources is None:
        with ExitStack() as local:
            return closed_exit_context(source,db,event,now=now,pin=pin,mode=mode,resources=local)
    blocked=dict(status='NO_CURRENT_ENTRY_OWNERSHIP_CONTEXT',reviewed_entry_quantity=None,
        informational_only=True,exit_submission_permission=False,
        reservation_release_permission=False,production_execution_enabled=False)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(CURRENT,)).fetchone():return blocked
    try:
        pin=load_pin() if pin is None else pin
        row=current_row(db,pin,mode)
        need(row is not None and row['status']=='ENTRY_QUANTITY_RECONCILED','OWNERSHIP_STATE_BLOCKED')
        if mode=='LIVE_CLOSED':
            need(re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']) is not None,'LIVE_UPSTOX_PIN_SCOPE_REQUIRED')
        else:need(pin['scope'].startswith('FIXTURE:'),'EXPLICIT_FIXTURE_SCOPE_REQUIRED')
        current=aware(now.isoformat());generated=aware(row['account_capture_generated_at'])
        completed=aware(row['account_capture_completed_at']);assessed=aware(row['assessed_at'])
        need(generated<=completed<=assessed<=current
             and 0<=(current-generated).total_seconds()<=30 and day(current)==day(generated),
             'OWNERSHIP_STATE_STALE_OR_FUTURE')
        need(event['role']=='EXIT' and event['direction']==row['entry_direction']
             and event.get('entry_reference_at') is not None
             and aware(event['entry_reference_at'])==aware(row['entry_signal_at'])
             and aware(row['entry_signal_at'])<=aware(event['event_at'])<=current,
             'EXIT_PARENT_OR_DIRECTION_UNVERIFIED')
        adapter=rollback_database(Path(os.getenv('HILEGA_PREPARATION_ADAPTER_DB',
            'data/research/hilega-broker-adapter-closed/adapter.sqlite')))
        broker=broker_snapshot(adapter,resources)
        fresh=read_connection(SourceReader(db,broker),pin['scope'],expected_mode=mode)
        need(sha(fresh)==row['source_fingerprint'],'OWNERSHIP_BOUND_SOURCE_CHANGED')
        return dict(status='ENTRY_QUANTITY_CONTEXT_ONLY',
            reviewed_entry_quantity=row['reviewed_entry_quantity'],
            ownership_record_fingerprint=sha(row),fixture_only=mode=='OFFLINE_FIXTURE',
            informational_only=True,exit_submission_permission=False,
            reservation_release_permission=False,production_execution_enabled=False)
    except Exception as exc:
        reason=str(exc)
        blocked['reason']=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,179}',reason) else 'OWNERSHIP_CONTEXT_UNAVAILABLE'
        return blocked
