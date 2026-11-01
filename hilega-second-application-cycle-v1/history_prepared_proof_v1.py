"""History-aware prepared-reference and fresh-state checks; no live authority."""
from decimal import Decimal
import json
from pathlib import Path
from cycle_scope_v1 import (
    BrokerScope,archives,verify_lifecycle_capture,one,need,digest,port,aware,day,
    order_identity,trade_identity,validate_account_rows,
)
from history_aware_preparation_v1 import ADMISSIONS,MODEL
from application_cycle_close_v1 import ACTIVE,signed
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
from market_lab.hilega_preparation_runtime_v1.evidence import validate,FLAGS
from market_lab.hilega_preparation_runtime_v1.source import event_digest,entry_clock_open
from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted
from market_lab.hilega_production_bridge_health_v1 import effective
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE,inspect_quote


def admission_as_handoff(db,pin,key,provenance):
    row=signed(one(db,ADMISSIONS,key),pin)
    need(row['model']==MODEL and row['request_id']==key,'HISTORY_ADMISSION_BINDING_CHANGED')
    for table in ACTIVE:
        need(digest(one(db,table,key))==row['active_fingerprints'][table],
             'HISTORY_PREPARATION_REFERENCE_CHANGED')
    need(sorted(row['closed_history_fingerprints'])==sorted(digest(a) for a in archives(db,pin)),
         'HISTORY_ARCHIVES_CHANGED_AFTER_PREPARATION')
    return row


def review_prepared(db,pin,*,journal,request_id):
    key=request_id;admission=admission_as_handoff(db,pin,key,None)
    plan=one(db,'preparation_plans',key);out=one(db,'preparation_outbox',key)
    hold=one(db,'preparation_shadow_holds',key);binding=one(db,'preparation_request_bindings',key)
    cash=verify_row(one(db,'preparation_cash_reservations',key),pin)
    need(binding['model']=='HILEGA_HISTORY_AWARE_DISABLED_REQUEST_BINDING_V1'
         and binding['request_fingerprint']==cash['request_fingerprint']==admission['request_fingerprint']
         and cash['plan_fingerprint']==binding['plan_fingerprint']==digest(plan)
         and cash['shadow_hold_fingerprint']==binding['hold_fingerprint']==digest(hold)
         and cash['outbox_fingerprint']==binding['outbox_fingerprint']==digest(out),
         'HISTORY_REQUEST_RESERVATION_BINDING_CHANGED')
    need(all(row.get(flag) is False for row in (plan,hold,out,binding) for flag in FLAGS),
         'HISTORY_PREPARATION_AUTHORITY_CHANGED')
    journal=Path(journal)
    need(journal.is_file() and not journal.is_symlink(),'REGULAR_HISTORY_ENTRY_JOURNAL_REQUIRED')
    records=verified_records(journal);sequence=plan['source_sequence']
    need(1<=sequence<=len(records),'HISTORY_ENTRY_SEQUENCE_CHANGED')
    events=accepted(records[sequence-1])
    need(len(events)==1 and events[0]['id']==key and events[0]['role']=='ENTRY'
         and records[sequence-1]['record_hash']==plan['source_record_hash'],'HISTORY_ENTRY_JOURNAL_CHANGED')
    event=events[0]
    consumed=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(key,)).fetchone()
    need(consumed is not None and consumed[0]==event_digest(event),'HISTORY_ENTRY_CONSUMPTION_CHANGED')
    cursor=one(db,'preparation_source',1)
    need(cursor['path']==str(journal.resolve()) and cursor['sequence']>=sequence and cursor['sequence']<=len(records)
         and records[cursor['sequence']-1]['record_hash']==cursor['hash'],'HISTORY_ENTRY_CURSOR_CHANGED')
    raw=db.execute('SELECT data FROM preparation_evidence WHERE digest=?',(binding['bundle_fingerprint'],)).fetchone()
    need(raw is not None,'HISTORY_ENTRY_EVIDENCE_REQUIRED');bundle=json.loads(raw[0])
    need(digest(bundle)==binding['bundle_fingerprint']==out['bundle_fingerprint'],'HISTORY_ENTRY_EVIDENCE_CHANGED')
    checked=next(p for p in validate(bundle,pin,as_of=plan['created_at']) if p['direction']==plan['direction'])
    need(set(checked['reasons'])<={'ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED'},
         'HISTORY_ENTRY_NESTED_EVIDENCE_REJECTED')
    found=db.execute('SELECT fingerprint,data FROM broker.requests WHERE id=?',(key,)).fetchone()
    need(found is not None and found[0]==admission['request_fingerprint'],'HISTORY_ENTRY_REQUEST_CHANGED')
    row=json.loads(found[1]);candidate=out['disabled_request_candidate']
    expected,fp=port.validated_request(candidate['draft'],signal_id=key,signal_at=plan['signal_at'],
        direction=plan['direction'],reservation_reference=key,as_of=candidate['draft']['created_at'])
    need(found[0]==fp and row==expected,'HISTORY_ENTRY_ALREADY_ATTEMPTED_OR_CHANGED')
    return dict(model='HILEGA_HISTORY_PREPARED_PROVENANCE_V1',request_id=key,
        request_fingerprint=fp,admission_fingerprint=digest(admission),reservation_fingerprint=digest(cash),
        event_fingerprint=event_digest(event),production_execution_enabled=False)


def current_history(db,pin,key,account,bundle,now,expected_version,bridge_run_id):
    control=one(db,'control',1);stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
    need(type(expected_version) is int and control['version']==expected_version
         and control['mode']=='PAUSED' and control.get('reason')=='APPLICATION_UNSENT_PREPARATION_REQUIRES_REVIEW'
         and stop is not None and stop[0]==stop[1],'HISTORY_CURRENT_CONTROLLER_REQUIRED')
    plan=one(db,'preparation_plans',key);hold=one(db,'preparation_shadow_holds',key)
    need(day(now)==control['session_date']==day(aware(plan['signal_at']))
         and 0<=(now-aware(plan['signal_at'])).total_seconds()<=60
         and control.get('resumed_at') and aware(plan['signal_at'])>aware(control['resumed_at'])
         and entry_clock_open(now),'HISTORY_CURRENT_SIGNAL_INVALID')
    health=one(db,'sim_bridge_health',1)
    need(health.get('run_id')==bridge_run_id and effective(health,now)['healthy'],'HISTORY_BRIDGE_NOT_CURRENT')
    need(all(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==1 for t in ACTIVE)
         and db.execute('SELECT COUNT(*) FROM broker.requests').fetchone()[0]==1
         and not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in (
             'broker.attempts','broker.receipts','intents','sim_orders','sim_fills')),
         'HISTORY_SINGLE_PREPARED_CYCLE_REQUIRED')
    current_orders,positions=verify_lifecycle_capture(db,account,pin,now)
    need(not current_orders and not any(positions.values()),'EMPTY_NEW_CYCLE_BASELINE_REQUIRED')
    need(account.get('profile_verified_before_and_after') is True
         and account.get('account_position_rows_complete') is True
         and account.get('source_atomic') is False and account.get('position_fill_linkage_verified') is False
         and account.get('live_pnl') is None and not account.get('diagnostics',{}).get('issues',[]),
         'HISTORY_CLEAN_ACCOUNT_CAPTURE_REQUIRED')
    selected=next(p for p in validate(bundle,pin,as_of=now.isoformat()) if p['direction']==plan['direction'])
    need(set(selected['reasons'])<={'ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED'},
         'HISTORY_CURRENT_EVIDENCE_REJECTED')
    cash=bundle['cash_capture'];co,cp=validate_account_rows(cash);ao,ap=validate_account_rows(account)
    need({k:order_identity(v) for k,v in co.items()}=={k:order_identity(v) for k,v in ao.items()}
         and cp==ap and {(t['order_id'],t['trade_id']):trade_identity(t) for t in cash['trades']}==
             {(t['order_id'],t['trade_id']):trade_identity(t) for t in account['trades']},
         'HISTORY_CURRENT_CASH_ACCOUNT_DIFFER')
    need(selected['instrument']==plan['instrument'] and selected['quantity']==plan['quantity']
         and digest(selected['contract'])==plan['evidence']['contract_fingerprint'],
         'HISTORY_CURRENT_CONTRACT_CHANGED')
    grid=inspect_quote(selected['contract'],selected['quote'],profile=PROFILE)
    candidate=one(db,'preparation_outbox',key)['disabled_request_candidate'];body=candidate['draft']['body']
    price=Decimal(str(body['price']));premium=price*body['quantity']*100
    need(body['transaction_type']=='BUY' and body['order_type']=='LIMIT' and price>=Decimal(grid['ask']),
         'HISTORY_CURRENT_ASK_EXCEEDS_LIMIT')
    need(premium==premium.to_integral_value() and int(premium)==candidate['premium_cents']
         and type(candidate['fee_buffer_cents']) is int and candidate['fee_buffer_cents']>0
         and candidate['budget_cents']==int(premium)+candidate['fee_buffer_cents']
         and candidate['budget_cents']<=hold['held_cents']<=selected['half_cash_cap_cents'],
         'HISTORY_CURRENT_CASH_SHORTFALL')
    return dict(control_version=control['version'],control_fingerprint=digest(control),
        bridge_run_id=bridge_run_id,bridge_fingerprint=digest(health),
        fresh_bundle_fingerprint=digest(bundle),fresh_account_fingerprint=digest(account),
        fresh_cash_cap_cents=selected['half_cash_cap_cents'],reviewed_at=now.isoformat())
