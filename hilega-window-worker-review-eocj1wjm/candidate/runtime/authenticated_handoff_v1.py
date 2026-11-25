"""Read-only historical binding verification. No adoption or execution authority."""
import json
from pathlib import Path
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
from market_lab.hilega_preparation_runtime_v1.evidence import digest, validate, FLAGS
from market_lab.hilega_preparation_runtime_v1.source import event_digest
from market_lab.hilega_execution_port_v1.adapter import validated_request
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted


def need(ok, reason):
    if not ok:raise ValueError(reason)


def review(db, pin, *, journal, request_id):
    """Caller holds application lock and attached broker read snapshot; SELECT only."""
    need(db.in_transaction, 'CALLER_ATTACHED_SNAPSHOT_REQUIRED')
    path=Path(journal)
    need(path.is_file() and not path.is_symlink(), 'REGULAR_JOURNAL_REQUIRED')
    records=verified_records(path)
    def one(table,key):
        found=db.execute('SELECT data FROM '+table+' WHERE id=?',(key,)).fetchone()
        need(found is not None,'BOUND_REFERENCE_REQUIRED')
        return json.loads(found[0])
    meta=one('broker.meta',1)
    need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'CLOSED_ADAPTER_SCOPE_REQUIRED')
    plan=one('preparation_plans',request_id)
    hold=one('preparation_shadow_holds',request_id)
    out=one('preparation_outbox',request_id)
    binding=one('preparation_request_bindings',request_id)
    cash=verify_row(one('preparation_cash_reservations',request_id),pin)
    need(cash['id']==plan['id']==hold['id']==out['id']==binding['id']==request_id,
         'BOUND_REFERENCE_ID_CHANGED')
    need(plan['account_scope']==binding['account_scope']==pin['scope'],'BOUND_SCOPE_CHANGED')
    need(all(row.get(flag) is False for row in (plan,hold,out,binding) for flag in FLAGS),
         'BOUND_AUTHORITY_CHANGED')
    need(cash['plan_fingerprint']==digest(plan)
         and cash['shadow_hold_fingerprint']==digest(hold)
         and cash['outbox_fingerprint']==digest(out),'SIGNED_REFERENCE_CHANGED')
    need(binding['model']=='HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1'
         and binding['status']=='PREPARED_DISABLED_HOLD_RETAINED'
         and binding['plan_fingerprint']==digest(plan)
         and binding['hold_fingerprint']==digest(hold)
         and binding['outbox_fingerprint']==digest(out)
         and binding['broker_cash_locked'] is False,'APPLICATION_BINDING_CHANGED')
    seq=plan['source_sequence']
    need(type(seq) is int and 1<=seq<=len(records),'BOUND_JOURNAL_SEQUENCE_INVALID')
    record=records[seq-1];events=accepted(record)
    need(len(events)==1 and events[0]['role']=='ENTRY' and events[0]['id']==request_id,
         'SINGLE_BOUND_ENTRY_REQUIRED')
    event=events[0]
    need(record['record_hash']==plan['source_record_hash']
         and event['event_at']==plan['signal_at'] and event['direction']==plan['direction'],
         'BOUND_EVENT_CHANGED')
    consumed=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(request_id,)).fetchone()
    need(consumed is not None and consumed[0]==event_digest(event),'BOUND_CONSUMPTION_CHANGED')
    cursor=one('preparation_source',1);offset=cursor['sequence']
    need(cursor['path']==str(path.resolve()) and type(offset) is int and seq<=offset<=len(records)
         and cursor['hash']==records[offset-1]['record_hash'],'BOUND_CURSOR_CHANGED')
    evidence=db.execute('SELECT data FROM preparation_evidence WHERE digest=?',
                        (binding['bundle_fingerprint'],)).fetchone()
    need(evidence is not None,'SIGNED_EVIDENCE_REQUIRED')
    bundle=json.loads(evidence[0])
    need(digest(bundle)==binding['bundle_fingerprint']==out['bundle_fingerprint'],
         'BOUND_BUNDLE_CHANGED')
    historical=validate(bundle,pin,as_of=plan['created_at'])
    need(any(p['direction']==plan['direction'] and p['evidence_checks_passed']
             and p['instrument']==plan['instrument'] and p['quantity']==plan['quantity']
             for p in historical),'HISTORICAL_EVIDENCE_REJECTED')
    found=db.execute('SELECT fingerprint,data FROM broker.requests WHERE id=?',(request_id,)).fetchone()
    need(found is not None,'BOUND_REQUEST_REQUIRED')
    row=json.loads(found[1]);draft=out['disabled_request_candidate']['draft']
    expected,fp=validated_request(draft,signal_id=request_id,signal_at=plan['signal_at'],
        direction=plan['direction'],reservation_reference=request_id,as_of=draft['created_at'])
    need(found[0]==fp==cash['request_fingerprint']==binding['request_fingerprint']
         and row==expected,'BOUND_REQUEST_CHANGED_OR_ALREADY_ATTEMPTED')
    need(row['draft']['body']['transaction_type']=='BUY'
         and row['draft']['body']['instrument_token']==plan['instrument']
         and row['draft']['body']['quantity']==plan['quantity'],'BOUND_REQUEST_CONTRACT_CHANGED')
    need(not db.execute('SELECT 1 FROM broker.attempts WHERE request_id=?',(request_id,)).fetchone(),
         'EXISTING_ATTEMPT_REQUIRES_RECOVERY')
    need(cash['held_cents']==hold['held_cents']==binding['held_cents']
         and cash['cash_cap_cents']==binding['cash_cap_cents'],'BOUND_BUDGET_CHANGED')
    return dict(status='HISTORICAL_BOUND_PREPARATION_VERIFIED_EXECUTION_CLOSED',
        request_id=request_id,event_fingerprint=event_digest(event),request_fingerprint=fp,
        reservation_fingerprint=digest(cash),journal_record_hash=record['record_hash'],
        signature_scope='ACCOUNT_EVIDENCE_AND_LOCAL_RESERVATION',
        journal_hash_chain_verified=True,journal_external_authenticity_verified=False,
        current_freshness_verified=False,current_controller_clearance_verified=False,
        execution_adoption_implemented=False,entry_permission=False,orders_sent=False,
        reservation_release_permission=False,production_execution_enabled=False)
