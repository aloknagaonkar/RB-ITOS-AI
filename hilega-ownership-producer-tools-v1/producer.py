"""One-shot pinned account capture -> deployed ownership record. No order transport."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid
import tempfile
from zoneinfo import ZoneInfo


def need(ok,reason):
    if not ok:raise ValueError(reason)


def safe_reason(exc):
    value=str(exc)
    return value if re.fullmatch(r'[A-Z][A-Z0-9_]{0,179}',value) else 'OWNERSHIP_PRODUCER_ERROR'


def flags():
    return dict(orders_sent=False,production_execution_enabled=False,
        entry_permission=False,exit_submission_permission=False,
        reservation_release_permission=False,production_ready=False,
        entry_allocation_fraction='0.50',daily_loss_limit_required=False,
        background_producer_enabled=False,fees_complete=False,
        realized_net_pnl_paise=None,open_net_pnl_paise=None)


def run_once(action,*,pin_reader,reader,capture,reviewer,writer,state_reader,clock):
    need(action in {'check','record'},'PRODUCER_ACTION_INVALID')
    report=dict(flags(),model='HILEGA_ONE_SHOT_OWNERSHIP_PRODUCER_V1',action=action,
        database_modified=False,ownership_record_persisted=False,
        current_state_signature_verified=False,broker_capture_attempted=False,
        verified_owned_quantity=None,controller_changed=False)
    pin=None;write_started=False
    try:
        pin=deepcopy(pin_reader())
        before=deepcopy(reader(pin))
        report['broker_capture_attempted']=True
        snapshot=deepcopy(capture(pin))
        need(pin_reader()==pin,'ACCOUNT_PIN_CHANGED_DURING_CAPTURE')
        after=reader(pin)
        need(before==after,'LOCAL_SOURCES_CHANGED_DURING_CAPTURE')
        review=reviewer(after,snapshot,pin,as_of=clock().isoformat())
        report.update(review_status=review['status'],reasons=review['reasons'],
            current_entry_ownership_verified=review['current_entry_ownership_verified'],
            live_evidence_assessed=review['live_evidence_assessed'],
            account_capture_generated_at=review['account_capture_generated_at'],
            account_capture_completed_at=review['account_capture_completed_at'],
            account_capture_age_seconds=review['account_capture_age_seconds'],
            verified_owned_quantity=review['reviewed_remaining_entry_quantity'])
        if action=='check':
            report['status']='OWNERSHIP_PRODUCER_CHECK_COMPLETE'
            return report
        need(pin_reader()==pin,'ACCOUNT_PIN_CHANGED_BEFORE_PERSISTENCE')
        write_started=True
        persisted=writer(snapshot,pin)
        row=state_reader(pin)
        need(row is not None and row['account_capture_fingerprint']==
             hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
             'PERSISTED_CAPTURE_READBACK_MISMATCH')
        need(pin_reader()==pin,'ACCOUNT_PIN_CHANGED_AFTER_PERSISTENCE')
        if persisted.get('first_record_backup'):
            report['first_record_backup']=persisted['first_record_backup']
        report.update(status='OWNERSHIP_PRODUCER_RECORDED_'+row['status'],
            ownership_record_persisted=True,current_state_signature_verified=True,
            database_modified=not persisted.get('idempotent_replay',False),
            persistence_outcome='VERIFIED_CURRENT_RECORD',
            verified_owned_quantity=row['reviewed_entry_quantity'],
            current_entry_ownership_verified=(row['status']=='ENTRY_QUANTITY_RECONCILED'
                                               and row['evidence_mode']=='LIVE_CLOSED'),
            record_status=row['status'],record_assessed_at=row['assessed_at'],
            account_capture_age_seconds=(clock()-datetime.fromisoformat(snapshot['generated_at'])).total_seconds(),
            reasons=row['reasons'])
        return report
    except Exception as exc:
        report.update(status='OWNERSHIP_PRODUCER_STOPPED_FOR_REVIEW',reason=safe_reason(exc),
            current_entry_ownership_verified=False,verified_owned_quantity=None)
        if write_started:
            report.update(database_modified=None,persistence_outcome='UNKNOWN_REVIEW_REQUIRED',
                          automatic_write_retry=False)
            return report
        if action=='record' and pin is not None:
            try:
                need(pin_reader()==pin,'ACCOUNT_PIN_CHANGED_SKIP_INVALIDATION')
                # Explicit local failure event, never labelled broker evidence.
                failure=dict(model='HILEGA_OWNERSHIP_PRODUCER_FAILURE_V1',
                    snapshot_id='producer-failure-'+uuid.uuid4().hex,
                    reason=safe_reason(exc),at=clock().isoformat())
                write_started=True
                persisted=writer(failure,pin)
                row=state_reader(pin)
                expected=hashlib.sha256(json.dumps(failure,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
                need(row is not None and row['status']=='BLOCKED'
                     and row['account_capture_fingerprint']==expected,
                     'FAILED_INVALIDATION_READBACK')
                if persisted.get('first_record_backup'):
                    report['first_record_backup']=persisted['first_record_backup']
                report.update(status='OWNERSHIP_PRODUCER_FAILED_CURRENT_INVALIDATED',
                    database_modified=True,current_state_signature_verified=True,
                    ownership_record_persisted=True,record_status='BLOCKED',
                    persistence_outcome='VERIFIED_BLOCKED_CURRENT_RECORD')
            except Exception as invalidation:
                report.update(invalidation_reason=safe_reason(invalidation),
                    database_modified=None if write_started else False,
                    persistence_outcome='UNKNOWN_REVIEW_REQUIRED' if write_started else 'NOT_ATTEMPTED',
                    automatic_write_retry=False)
        return report


def package_check(root):
    folder=Path(__file__).resolve().parent
    manifest=json.loads((folder/'manifest.json').read_text())
    for parent,items in ((folder,manifest['package_sha256']),(root,manifest['installed_source_sha256'])):
        for relative,expected in items.items():
            path=parent/relative
            need(path.is_file() and not path.is_symlink()
                 and not any(p.is_symlink() for p in path.parents),'REGULAR_SOURCE_REQUIRED')
            need(hashlib.sha256(path.read_bytes()).hexdigest()==expected,
                 'PACKAGE_OR_INSTALLED_SOURCE_CHANGED')


def status_report(pin,source,row,*,clock,digest):
    result=dict(flags(),model='HILEGA_OWNERSHIP_PRODUCER_STATUS_V1',action='status',
        database_modified=False,broker_capture_attempted=False,ownership_record_persisted=row is not None,
        current_state_signature_verified=row is not None,verified_owned_quantity=None,
        current_entry_ownership_verified=False)
    if row is None:
        result['status']='NO_OWNERSHIP_RECORD';return result
    result.update(status=row['status'],reasons=row['reasons'],record_assessed_at=row['assessed_at'])
    if row['status']!='ENTRY_QUANTITY_RECONCILED':return result
    from datetime import datetime
    generated=datetime.fromisoformat(row['account_capture_generated_at'])
    completed=datetime.fromisoformat(row['account_capture_completed_at'])
    assessed=datetime.fromisoformat(row['assessed_at']);now=clock()
    age=(now-generated).total_seconds();result['account_capture_age_seconds']=age
    if (not generated<=completed<=assessed<=now or not 0<=age<=30
            or generated.astimezone(ZoneInfo('Asia/Kolkata')).date()!=now.astimezone(ZoneInfo('Asia/Kolkata')).date()
            or digest(source)!=row['source_fingerprint']):
        result['status']='STALE_OR_LOCAL_SOURCE_CHANGED';return result
    result.update(status='CURRENT_ENTRY_CONTEXT_AVAILABLE',verified_owned_quantity=row['reviewed_entry_quantity'],
        current_entry_ownership_verified=row['evidence_mode']=='LIVE_CLOSED')
    return result



def first_write_backup(app,root):
    """Consistent private SQLite backup before the ownership tables first appear."""
    with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True,timeout=10)) as source:
        source.execute('PRAGMA query_only=ON')
        if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preparation_entry_ownership_state'").fetchone():
            return None
        backups=root/'backups'
        need(backups.is_dir() and not backups.is_symlink()
             and not any(p.is_symlink() for p in backups.parents),'PRIVATE_BACKUP_PARENT_REQUIRED')
        folder=Path(tempfile.mkdtemp(prefix='hilega-ownership-producer-',dir=backups))
        target=folder/'application-before-first-record.sqlite'
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        os.close(fd)
        with closing(sqlite3.connect(target)) as destination:source.backup(destination)
        return str(target)



def read_status_snapshot(app,broker,pin,state,*,mode='LIVE_CLOSED'):
    with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('ATTACH DATABASE ? AS broker',(broker.as_uri()+'?mode=ro',))
        db.execute('BEGIN')
        try:
            source=state.read_connection(db,pin['scope'],expected_mode=mode)
            row=state.current_row(db,pin,mode)
            return source,row
        finally:db.rollback()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['status','check','record'])
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json')
    args=p.parse_args();root=args.repo.resolve();package_check(root)
    sys.path.insert(0,str(root/'backend'))
    from market_lab.hilega_production_account_adapter_v1 import read_pin,capture,Client
    from market_lab.hilega_preparation_runtime_v1 import ownership_state as state
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.ownership_review import reconcile_entry
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources,assess
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
    from dotenv import dotenv_values
    app=root/'data/research/hilega-production-workspace/sim.sqlite'
    broker=root/'data/research/hilega-broker-adapter-closed/adapter.sqlite'
    clock=lambda:datetime.now(timezone.utc)
    def pin_reader():
        pin=read_pin(args.pin_file)
        need(re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']) is not None,'LIVE_UPSTOX_PIN_SCOPE_REQUIRED')
        return pin
    def reader(pin):
        source=read_sources(app,broker,pin['scope']);assess(source)
        need(source['control'].get('production_execution_enabled') is False,'CLOSED_CONTROLLER_REQUIRED')
        stop=source['stop_state']
        need(isinstance(stop,list) and len(stop)==2
             and all(type(v) is int and v>=0 for v in stop) and stop[0]==stop[1],
             'UNHANDLED_OR_UNKNOWN_STOP_STATE')
        return source
    def account_capture(pin):
        settings=dotenv_values(root/'.env')
        def setting(name):
            shell,file=os.getenv(name),settings.get(name)
            need(not(shell and file and shell!=file),'TOKEN_CONFIGURATION_CONFLICT')
            return shell or file
        token=(setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or setting('UPSTOX_ACCESS_TOKEN') or '').strip()
        need(bool(token),'READ_TOKEN_MISSING')
        return capture(Client(token),pin)
    def writer(snapshot,pin):
        reader(pin)  # Recheck paused/account/stop safety before backup or write.
        need(pin_reader()==pin,'ACCOUNT_PIN_CHANGED_BEFORE_WRITE')
        backup=first_write_backup(app,root)
        result=state.record_entry_review(app,broker,snapshot,pin,clock=clock)
        if backup is not None:result['first_record_backup']=backup
        return result
    def state_reader(pin):
        with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
            db.execute('PRAGMA query_only=ON')
            return state.current_row(db,pin,'LIVE_CLOSED')
    if args.action=='status':
        pin=pin_reader();before=reader(pin)
        source,row=read_status_snapshot(app,broker,pin,state)
        need(before==source,'LOCAL_SOURCES_CHANGED_DURING_STATUS')
        need(pin_reader()==pin,'ACCOUNT_PIN_CHANGED_DURING_STATUS')
        report=status_report(pin,source,row,clock=clock,digest=sha)
    else:
        report=run_once(args.action,pin_reader=pin_reader,reader=reader,capture=account_capture,
            reviewer=reconcile_entry,writer=writer,state_reader=state_reader,clock=clock)
    print(json.dumps(report,indent=2))
    return 1 if report['status'] in {'OWNERSHIP_PRODUCER_STOPPED_FOR_REVIEW',
        'OWNERSHIP_PRODUCER_FAILED_CURRENT_INVALIDATED'} else 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps(dict(flags(),status='STOPPED_FOR_REVIEW',reason=safe_reason(exc)),indent=2))
        raise SystemExit(1)
