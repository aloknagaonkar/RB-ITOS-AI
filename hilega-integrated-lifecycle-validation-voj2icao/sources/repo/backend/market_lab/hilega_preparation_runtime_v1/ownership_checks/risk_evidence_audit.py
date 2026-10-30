"""Read-only historical-reference audit; never produces live P&L or entry authority."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from .historical_receipt_checks import _check as receipt_check,sha

FLAGS=('orders_sent','production_execution_enabled','entry_permission',
       'application_ledger_updated','strategy_ownership_verified',
       'real_funds_reservation_verified','reservation_release_permission',
       'allocation_reserved','source_atomic')
APP_TABLES=('intents','sim_orders','sim_fills','sim_allocation_reservations',
            'preparation_plans','preparation_shadow_holds','preparation_outbox',
            'preparation_evidence','preparation_source','preparation_events')

class AuditBlocked(ValueError):pass

def need(ok,reason):
    if not ok:raise AuditBlocked(reason)

def regular(path):
    p=Path(path).absolute()
    need(p.is_file() and not p.is_symlink(),'REGULAR_EXISTING_SOURCE_REQUIRED')
    for parent in p.parents:need(not parent.is_symlink(),'SYMLINK_PARENT_FORBIDDEN')
    return p

def blob(path):
    raw=regular(path).read_bytes()
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def mapping(raw):
    value=json.loads(raw)
    need(isinstance(value,dict),'OBJECT_RECORD_REQUIRED')
    return value

def records(db,table):
    rows=db.execute('SELECT id,data FROM '+table).fetchmany(10001)
    need(len(rows)<=10000,'SOURCE_RECORD_LIMIT_EXCEEDED')
    result={}
    for key,raw in rows:
        value=mapping(raw)
        need(value.get('id')==key and key not in result,'APPLICATION_RECORD_ID_MISMATCH')
        result[key]=value
    return result

def read_sources(application,adapter,expected_scope,*,expected_mode='LIVE_CLOSED'):
    need(expected_mode in ('LIVE_CLOSED','OFFLINE_FIXTURE'),'EXPECTED_ADAPTER_MODE_INVALID')
    app,broker=regular(application),regular(adapter)
    for path in (app,broker):
        with path.open('rb') as stream:header=stream.read(20)
        need(header[:16]==b'SQLite format 3\x00' and header[18:20]==b'\x01\x01','ROLLBACK_JOURNAL_SOURCE_REQUIRED')
    need(not app.samefile(broker),'DISTINCT_DATABASES_REQUIRED')
    # One attached read transaction. URI mode=ro applies to BOTH sources.
    with closing(sqlite3.connect(app.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('ATTACH DATABASE ? AS broker',(broker.as_uri()+'?mode=ro',))
        need(db.execute('PRAGMA main.journal_mode').fetchone()[0]=='delete','APPLICATION_DELETE_JOURNAL_REQUIRED')
        need(db.execute('PRAGMA broker.journal_mode').fetchone()[0]=='delete','ADAPTER_DELETE_JOURNAL_REQUIRED')
        db.execute('BEGIN')
        try:
            return read_connection(db,expected_scope,expected_mode=expected_mode)
        finally:db.rollback()

def read_connection(db,expected_scope,*,expected_mode='LIVE_CLOSED'):
    """Caller owns the attached main/broker transaction; SELECT statements only."""
    control=mapping(db.execute('SELECT data FROM main.control WHERE id=1').fetchone()[0])
    need(control.get('mode')=='PAUSED','CONTROLLER_MUST_BE_PAUSED')
    route=mapping(db.execute('SELECT data FROM main.preparation_route WHERE id=1').fetchone()[0])
    need(route==dict(route='PREPARATION_ONLY',model='APPLICATION_PREPARATION_ROUTE_V1'),'PREPARATION_ROUTE_REQUIRED')
    meta=mapping(db.execute('SELECT data FROM broker.meta WHERE id=1').fetchone()[0])
    need(meta==dict(scope=expected_scope,mode=expected_mode),'ADAPTER_PIN_SCOPE_OR_MODE_MISMATCH')
    counts={t:db.execute('SELECT COUNT(*) FROM main.'+t).fetchone()[0] for t in APP_TABLES}
    app_names={r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
    plans=records(db,'main.preparation_plans')
    holds=records(db,'main.preparation_shadow_holds')
    outbox=records(db,'main.preparation_outbox')
    bindings=records(db,'main.preparation_request_bindings') if 'preparation_request_bindings' in app_names else {}
    counts['preparation_request_bindings']=len(bindings)
    requests=db.execute('SELECT id,fingerprint,data FROM broker.requests ORDER BY rowid').fetchmany(10001)
    attempts=db.execute('SELECT id,request_id,operation,data FROM broker.attempts').fetchmany(10001)
    receipt_rows=db.execute('SELECT id,data FROM broker.receipts').fetchmany(10001)
    need(max(len(requests),len(attempts),len(receipt_rows))<=10000,'SOURCE_RECORD_LIMIT_EXCEEDED')
    receipts=dict(receipt_rows)
    need(len(receipts)==len(receipt_rows),'DUPLICATE_RECEIPT_ID')
    # Hashes are checked here for local consistency only, not HMAC/signature authenticity.
    evidence_rows=db.execute('SELECT digest,data FROM main.preparation_evidence').fetchmany(10001)
    need(len(evidence_rows)<=10000,'SOURCE_RECORD_LIMIT_EXCEEDED')
    evidence=dict(evidence_rows)
    need(len(evidence)==len(evidence_rows),'DUPLICATE_EVIDENCE_DIGEST')
    cash=records(db,'main.preparation_cash_reservations') if 'preparation_cash_reservations' in app_names else {}
    policy=db.execute('SELECT data FROM main.preparation_cash_policy WHERE id=1').fetchone() if 'preparation_cash_policy' in app_names else None
    stop=db.execute('SELECT generation,handled FROM main.sim_stop_state WHERE id=1').fetchone() if 'sim_stop_state' in app_names else None
    cursors=db.execute('SELECT id,data FROM main.preparation_source ORDER BY id').fetchall()
    exits=records(db,'main.preparation_exit_dispatch') if 'preparation_exit_dispatch' in app_names else {}
    return dict(cash_reservations=cash,cash_policy=mapping(policy[0]) if policy else None,
                stop_state=list(stop) if stop else None,source_cursors=cursors,closed_exits=exits,
                scope=expected_scope,mode=expected_mode,control=control,counts=counts,
                plans=plans,holds=holds,outbox=outbox,bindings=bindings,
                requests=requests,attempts=attempts,receipts=receipts,evidence=evidence)

def assess(source):
    plans,holds,outbox,bindings=(source[k] for k in ('plans','holds','outbox','bindings'))
    need(set(plans)==set(holds)==set(outbox),'PLAN_HOLD_OUTBOX_IDS_MISMATCH')
    need(set(bindings)<=set(plans),'ORPHAN_APPLICATION_BINDING')
    requests={}
    for key,fp,raw in source['requests']:
        request=mapping(raw)
        need(key not in requests and request.get('request_id')==key,'REQUEST_ID_MISMATCH')
        stable={k:request[k] for k in ('request_id','draft','signal_id','signal_at','direction','reservation_reference')}
        need(sha(stable)==fp,'REQUEST_FINGERPRINT_MISMATCH')
        draft=request['draft']
        need(draft.get('model')=='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1','DRAFT_MODEL_INVALID')
        need((draft.get('documented_method'),draft.get('documented_host'),draft.get('documented_path'))==('POST','api-hft.upstox.com','/v3/order/place'),'PLACE_ENDPOINT_MISMATCH')
        need(draft['request_id']==key and sha(draft['body'])==draft['fingerprint'],'DRAFT_FINGERPRINT_MISMATCH')
        need(all(draft.get(k) is False for k in ('submission_enabled','entry_permission','orders_sent')),'DISABLED_DRAFT_REQUIRED')
        requests[key]=(request,fp)
    local_links=[]
    for key,binding in bindings.items():
        plan,hold,out=plans[key],holds[key],outbox[key]
        need(key in requests,'BOUND_REQUEST_MISSING')
        request,fp=requests[key]
        for value in (plan,hold,out,binding):
            need(all(value.get(flag) is False for flag in FLAGS),'APPLICATION_PERMISSION_FLAGS_CHANGED')
        need(binding.get('model')=='HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1'
             and binding.get('status')=='PREPARED_DISABLED_HOLD_RETAINED','BINDING_MODEL_OR_STATUS_INVALID')
        need(binding.get('account_scope')==plan.get('account_scope')==source['scope'],'APPLICATION_ACCOUNT_SCOPE_MISMATCH')
        need(binding.get('request_fingerprint')==fp and binding.get('plan_fingerprint')==sha(plan)
             and binding.get('hold_fingerprint')==sha(hold) and binding.get('outbox_fingerprint')==sha(out),'APPLICATION_BINDING_HASH_MISMATCH')
        need(binding.get('local_budget_reference_bound') is True and binding.get('broker_cash_locked') is False,'LOCAL_BINDING_CANNOT_CLAIM_BROKER_LOCK')
        need(request['signal_id']==key==request['reservation_reference']==out['reservation_reference'],'SIGNAL_HOLD_REQUEST_ID_MISMATCH')
        need(out.get('status')=='NON_EXECUTABLE_PRICING_POLICY_PENDING' and out.get('request_body') is None,'OUTBOX_MUST_REMAIN_NON_EXECUTABLE')
        need(out['disabled_request_candidate']['draft']==request['draft'],'OUTBOX_DRAFT_REQUEST_MISMATCH')
        need(plan.get('status')=='EVIDENCE_LINKED_UNSENT' and hold.get('evidence_mode')=='REAL_CASH_OBSERVED_SHADOW_ONLY'
             and hold.get('real_cash_reserved') is False,'UNSENT_SHADOW_PREPARATION_REQUIRED')
        amount=hold['held_cents'];cap=binding['cash_cap_cents']
        need(type(amount) is int and amount>0 and type(cap) is int and cap>=amount
             and type(binding.get('held_cents')) is int and binding['held_cents']==amount,'LOCAL_HOLD_AMOUNT_INVALID')
        body=request['draft']['body']
        need(body['transaction_type']=='BUY' and body['quantity']==plan['quantity']==out['quantity']
             and type(plan['quantity']) is int and type(body['quantity']) is int and type(out['quantity']) is int and plan['quantity']>0
             and body['instrument_token']==plan['instrument']==out['instrument'],'PREPARATION_CONTRACT_MISMATCH')
        bundle_hash=binding['bundle_fingerprint']
        need(bundle_hash==out['bundle_fingerprint']==plan['evidence']['bundle_fingerprint'],'BUNDLE_REFERENCE_MISMATCH')
        need(bundle_hash in source['evidence'],'PERSISTED_EVIDENCE_MISSING')
        need(sha(mapping(source['evidence'][bundle_hash]))==bundle_hash,'PERSISTED_EVIDENCE_HASH_MISMATCH')
        local_links.append(sha(dict(binding=binding,request_fingerprint=fp)))
    historical=receipt_check(source['mode'],source['requests'],source['attempts'],source['receipts'])
    gaps=['CURRENT_SIGNED_ACCOUNT_EVIDENCE_NOT_ASSESSED','CURRENT_FILL_LINKAGE_UNVERIFIED',
          'STRATEGY_OWNERSHIP_UNVERIFIED','COMPLETE_FEE_EVIDENCE_PROVIDER_NOT_WIRED',
          'REALIZED_NET_PNL_UNAVAILABLE','OPEN_NET_PNL_UNAVAILABLE',
          'PRODUCTION_DAILY_STOP_STATE_NOT_INTEGRATED']
    if not source['requests']:gaps.append('NO_EXECUTION_HISTORY_IS_NOT_VERIFIED_ZERO_PNL')
    if set(plans)-set(bindings):gaps.append('PREPARATIONS_WITHOUT_ATOMIC_REQUEST_BINDING')
    if set(requests)-set(bindings):gaps.append('REQUESTS_WITHOUT_APPLICATION_BINDING')
    if historical['unbound_request_count']:gaps.append('UNACKNOWLEDGED_REQUESTS_REQUIRE_RECONCILIATION')
    if not historical['bindings']:gaps.append('NO_DURABLE_ACKNOWLEDGEMENT_REFERENCES')
    if any(source['counts'][k] for k in ('intents','sim_orders','sim_fills','sim_allocation_reservations')):
        gaps.append('SIMULATOR_HISTORY_CANNOT_ESTABLISH_LIVE_PNL')
    return dict(model='HILEGA_RISK_EVIDENCE_AUDIT_V1',status='BLOCKED_EVIDENCE_GAPS',
        assessed_at=datetime.now(timezone.utc).isoformat(),scope='READ_ONLY_HISTORICAL_REFERENCES_ONLY',
        adapter_mode=source['mode'],account_scope_matches_local_pin=True,
        application_counts=source['counts'],adapter_counts=dict(requests=len(source['requests']),attempts=len(source['attempts']),receipts=len(source['receipts'])),
        local_binding_reference_count=len(local_links),historical_ack_reference_count=len(historical['bindings']),
        unacknowledged_request_count=historical['unbound_request_count'],
        receipt_review_status=historical['status'],gaps=sorted(gaps),
        gross_pnl_paise=None,realized_net_pnl_paise=None,open_net_pnl_paise=None,
        live_pnl_authenticated=False,fees_complete=False,current_positions_assessed=False,
        strategy_ownership_verified=False,real_funds_reservation_verified=False,
        bundle_signatures_assessed=False,risk_gate_input_ready=False,
        broker_reads_performed=False,database_modified=False,
        controller_changed=False,entry_permission=False,orders_sent=False,
        production_execution_enabled=False,reservation_release_permission=False,production_ready=False)

def audit_paths(application,adapter,scope,*,expected_mode='LIVE_CLOSED'):
    try:return assess(read_sources(application,adapter,scope,expected_mode=expected_mode))
    except AuditBlocked:raise
    except Exception as exc:
        text=str(exc)
        if re.fullmatch('[A-Z0-9_]{1,140}',text):raise AuditBlocked(text) from None
        raise AuditBlocked('SOURCE_SCHEMA_OR_REFERENCE_INVALID') from None
