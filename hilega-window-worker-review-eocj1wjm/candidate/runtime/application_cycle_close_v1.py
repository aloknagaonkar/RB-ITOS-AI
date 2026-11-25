"""Closed application cycle archive/retirement and history-aware reentry REVIEW.
Never broker cash release, actual next-entry preparation or live authority.
"""
from copy import deepcopy
from decimal import Decimal
import hmac
import json
from pathlib import Path
from application_lifecycle_candidate_v1 import (
    exact, position, exit_event, adoption, ENTRY_MODEL, EXIT_MODEL,
    transaction, one, port, digest, verify, sign, aware, day, validate_account_rows,
)
from authenticated_handoff_v1 import need
from market_lab.hilega_preparation_runtime_v1.evidence import validate,dependencies
from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open
from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted
from market_lab.hilega_production_bridge_health_v1 import effective
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE,inspect_quote

CLOSEOUTS='preparation_candidate_cycle_closeouts_v1'
ARCHIVES='preparation_candidate_closed_cycle_archives_v1'
RETIREMENTS='preparation_candidate_reference_retirements_v1'
ACTIVE=('preparation_plans','preparation_shadow_holds','preparation_outbox',
        'preparation_request_bindings','preparation_cash_reservations')
MODEL='HILEGA_APPLICATION_CLOSED_CYCLE_V1'


def seal(row,pin):
    result=deepcopy(row);result['signature']=sign(result,pin);return result


def signed(row,pin):
    payload=dict(row);signature=payload.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         'CLOSED_CYCLE_SIGNATURE_INVALID')
    need(row['account_scope']==pin['scope'] and row['production_execution_enabled'] is False
         and row['entry_permission'] is False and row['reservation_release_permission'] is False,
         'CLOSED_CYCLE_SCOPE_OR_AUTHORITY_CHANGED')
    return row


def maybe(db,table,key):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
    if not exists:return None
    raw=db.execute('SELECT data FROM '+table+' WHERE id=?',(key,)).fetchone()
    return json.loads(raw[0]) if raw else None


def broker_view(db):
    return {table:[list(row) for row in db.execute('SELECT '+fields+' FROM broker.'+table+' ORDER BY '+order)]
        for table,fields,order in (
            ('meta','id,data','id'),('requests','id,fingerprint,data','id'),
            ('attempts','id,request_id,operation,data','id'),('receipts','id,data','id'),
            ('candidate_existing_request_claims_v1','id,data','id'))}


def source_view(db,key):
    source={table:one(db,table,key) for table in ACTIVE}
    source['broker']=broker_view(db)
    source['cursor']=one(db,'preparation_source',1)
    source['entry_adoption']=one(db,'preparation_execution_adoption_candidates_v1',key)
    return source


def paused(db):
    control=one(db,'control',1);stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
    need(control['mode']=='PAUSED' and stop is not None and stop[0]==stop[1],
         'CYCLE_PAUSED_WITH_NO_PENDING_STOP_REQUIRED')


def authenticate_closeout(row,pin):
    signed(row,pin)
    need(row['model']==MODEL and digest(row['source'])==row['source_fingerprint']
         and digest(row['snapshot'])==row['snapshot_fingerprint'],'CLOSED_CYCLE_EVIDENCE_CHANGED')
    verify(row['snapshot'],pin,as_of=row['assessed_at'])
    orders,positions=validate_account_rows(row['snapshot'])
    need(positions and not any(positions.values())
         and all(o['status'] in {'FILLED','CANCELLED','REJECTED'} and o['pending']==0 for o in orders.values())
         and row['review']['remaining_quantity']==row['review']['pending_exit_quantity']==0
         and row['review']['all_orders_terminal'] is True,'TERMINAL_FLAT_CLOSEOUT_REQUIRED')
    return row


def record_closeout(app,adapter,pin,authority,*,entry_id,journal,exit_sequence,
                    capture_provider,clock,checkpoint=lambda at:None):
    exact(app,adapter,pin,authority)
    with transaction(app,adapter.store.path) as db:
        old=maybe(db,CLOSEOUTS,entry_id)
        if old:
            authenticate_closeout(old,pin)
            need(old['entry_id']==entry_id,'CLOSEOUT_ENTRY_ID_CHANGED')
            return dict(record=old,idempotent_replay=True,current_checks_reexecuted=False,
                        production_execution_enabled=False)
    snapshot=deepcopy(capture_provider())
    with transaction(app,adapter.store.path) as db:
        old=maybe(db,CLOSEOUTS,entry_id)
        if old:
            authenticate_closeout(old,pin)
            need(old['entry_id']==entry_id,'CLOSEOUT_ENTRY_ID_CHANGED')
            return dict(record=old,idempotent_replay=True,current_checks_reexecuted=False,
                        production_execution_enabled=False)
        paused(db);at=clock()
        report=position(db,adapter,pin,authority,entry_id,snapshot,at)
        need(report['status']=='FLAT_CONFIRMED_REFERENCE' and report['exit_id'],
             'TERMINAL_FLAT_CLOSEOUT_REQUIRED')
        parent,_,_=adoption(db,entry_id,pin,authority,ENTRY_MODEL)
        event,record_hash=exit_event(db,journal,exit_sequence,parent)
        _,_,exit_adoption=adoption(db,report['exit_id'],pin,authority,EXIT_MODEL)
        need(exit_adoption['event']==event and exit_adoption['record_hash']==record_hash,
             'CLOSEOUT_EXIT_PROVENANCE_CHANGED')
        need(all(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==1 for table in ACTIVE),
             'ONE_ACTIVE_CYCLE_REQUIRED')
        source=source_view(db,entry_id)
        gross=sum((Decimal(str(t['price']))*t['quantity']*(1 if t['side']=='SELL' else -1)
                   for t in snapshot['trades']),Decimal(0))*100
        need(gross==gross.to_integral_value(),'EXACT_GROSS_PAISE_REQUIRED')
        row=seal(dict(model=MODEL,account_scope=pin['scope'],entry_id=entry_id,
            assessed_at=at.isoformat(),journal=str(Path(journal).resolve()),exit_sequence=exit_sequence,
            exit_event=event,exit_record_hash=record_hash,source=source,source_fingerprint=digest(source),
            snapshot=snapshot,snapshot_fingerprint=digest(snapshot),review=report,
            realized_gross_pnl_paise=int(gross),fees_complete=False,realized_net_pnl_paise=None,
            financial_closeout_complete=False,active_references_retired=False,
            entry_permission=False,reservation_release_permission=False,production_execution_enabled=False),pin)
        db.execute('CREATE TABLE IF NOT EXISTS '+CLOSEOUTS+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        db.execute('INSERT INTO '+CLOSEOUTS+' VALUES(?,?)',(entry_id,port.encode(row)))
        checkpoint('AFTER_CYCLE_CLOSEOUT_INSERT');checkpoint('BEFORE_CYCLE_CLOSEOUT_COMMIT')
        final=position(db,adapter,pin,authority,entry_id,snapshot,clock())
        need(final['status']=='FLAT_CONFIRMED_REFERENCE' and source_view(db,entry_id)==source,
             'CLOSEOUT_SOURCE_CHANGED_BEFORE_COMMIT')
        final_event,final_hash=exit_event(db,journal,exit_sequence,parent)
        need(final_event==event and final_hash==record_hash,'CLOSEOUT_JOURNAL_CHANGED')
        authenticate_closeout(row,pin)
    return dict(record=row,idempotent_replay=False,current_checks_reexecuted=True,
                production_execution_enabled=False)


def archive_checked(row,pin):
    signed(row,pin)
    need(row['model']=='HILEGA_APPLICATION_CLOSED_CYCLE_ARCHIVE_V1'
         and row['entry_id']==row['closeout']['entry_id']
         and row['closeout_fingerprint']==digest(row['closeout']),'CLOSED_ARCHIVE_BINDING_CHANGED')
    authenticate_closeout(row['closeout'],pin);return row


def retire_references(app,adapter,pin,authority,*,entry_id,capture_provider,clock,
                      checkpoint=lambda at:None):
    exact(app,adapter,pin,authority)
    with transaction(app,adapter.store.path) as db:
        prior=maybe(db,RETIREMENTS,entry_id)
        if prior:
            signed(prior,pin);archive=archive_checked(one(db,ARCHIVES,entry_id),pin)
            need(prior['entry_id']==archive['entry_id']==entry_id,'RETIREMENT_ENTRY_ID_CHANGED')
            need(prior['archive_fingerprint']==digest(archive)
                 and not any(db.execute('SELECT 1 FROM '+t+' WHERE id=?',(entry_id,)).fetchone() for t in ACTIVE),
                 'RETIRED_REFERENCE_OR_ARCHIVE_CHANGED')
            return dict(status='CYCLE_RETIREMENT_HISTORICAL_REPLAY',idempotent_replay=True,
                        current_checks_reexecuted=False,production_execution_enabled=False)
    snapshot=deepcopy(capture_provider())
    with transaction(app,adapter.store.path) as db:
        paused(db)
        # Concurrent callers serialize. The second verifies the committed seal.
        prior=maybe(db,RETIREMENTS,entry_id)
        if prior:
            signed(prior,pin);archive=archive_checked(one(db,ARCHIVES,entry_id),pin)
            need(prior['entry_id']==archive['entry_id']==entry_id,'RETIREMENT_ENTRY_ID_CHANGED')
            need(prior['archive_fingerprint']==digest(archive),'CLOSED_ARCHIVE_BINDING_CHANGED')
            return dict(status='CYCLE_RETIREMENT_HISTORICAL_REPLAY',idempotent_replay=True,
                        current_checks_reexecuted=False,production_execution_enabled=False)
        closeout=authenticate_closeout(one(db,CLOSEOUTS,entry_id),pin)
        source=source_view(db,entry_id)
        need(source==closeout['source'],'CYCLE_SOURCE_CHANGED_AFTER_CLOSEOUT')
        report=position(db,adapter,pin,authority,entry_id,snapshot,clock())
        need(report['status']=='FLAT_CONFIRMED_REFERENCE','TERMINAL_FLAT_RETIREMENT_REQUIRED')
        archive=seal(dict(model='HILEGA_APPLICATION_CLOSED_CYCLE_ARCHIVE_V1',account_scope=pin['scope'],
            entry_id=entry_id,closeout=closeout,closeout_fingerprint=digest(closeout),
            retirement_snapshot=snapshot,retirement_snapshot_fingerprint=digest(snapshot),
            retired_at=clock().isoformat(),entry_permission=False,
            reservation_release_permission=False,production_execution_enabled=False),pin)
        marker=seal(dict(model='HILEGA_APPLICATION_LOCAL_REFERENCE_RETIREMENT_V1',account_scope=pin['scope'],
            entry_id=entry_id,archive_fingerprint=digest(archive),local_references_retired=True,
            broker_cash_release_assessed=False,broker_records_deleted=False,
            entry_permission=False,reservation_release_permission=False,production_execution_enabled=False),pin)
        for table in (ARCHIVES,RETIREMENTS):
            db.execute('CREATE TABLE IF NOT EXISTS '+table+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        db.execute('INSERT INTO '+ARCHIVES+' VALUES(?,?)',(entry_id,port.encode(archive)))
        db.execute('INSERT INTO '+RETIREMENTS+' VALUES(?,?)',(entry_id,port.encode(marker)))
        checkpoint('AFTER_CYCLE_ARCHIVE_INSERT')
        for table in ACTIVE:
            need(db.execute('DELETE FROM '+table+' WHERE id=?',(entry_id,)).rowcount==1,
                 'ACTIVE_CYCLE_REFERENCE_CHANGED')
        checkpoint('AFTER_CYCLE_REFERENCES_RETIRED');checkpoint('BEFORE_CYCLE_RETIREMENT_COMMIT')
        verify(snapshot,pin,as_of=clock().isoformat())
        need(broker_view(db)==source['broker'],'BROKER_EVIDENCE_CHANGED_DURING_RETIREMENT')
        archive_checked(archive,pin)
    return dict(status='APPLICATION_LOCAL_REFERENCES_RETIRED',idempotent_replay=False,
        local_references_retired=True,broker_records_deleted=False,broker_cash_release_assessed=False,
        automatic_next_entry_enabled=False,production_execution_enabled=False)


def order_identity(o):
    return tuple(o[k] for k in ('order_id','instrument','product','side','quantity','filled','pending','status'))+(aware(o['placed_at']),)


def trade_identity(t):
    return tuple(t[k] for k in ('order_id','trade_id','instrument','product','side','quantity'))+(Decimal(str(t['price'])),aware(t['filled_at']))


def attribute_history(db,pin,snapshot,now):
    verify(snapshot,pin,as_of=now.isoformat())
    need(snapshot.get('profile_verified_before_and_after') is True
         and snapshot.get('account_position_rows_complete') is True
         and snapshot.get('source_atomic') is False
         and snapshot.get('position_fill_linkage_verified') is False
         and snapshot.get('live_pnl') is None
         and isinstance(snapshot.get('diagnostics'),dict)
         and not snapshot['diagnostics'].get('issues',[]),'COMPLETE_CLEAN_REENTRY_CAPTURE_REQUIRED')
    orders,positions=validate_account_rows(snapshot)
    archived_orders={};archived_trades={};position_keys=set();entries=set();broker_requests={};broker_attempts={};broker_receipts={};broker_claims={}
    for key,raw in db.execute('SELECT id,data FROM '+ARCHIVES):
        archive=archive_checked(json.loads(raw),pin)
        need(key==archive['entry_id'] and key not in entries,'DUPLICATE_ARCHIVED_CYCLE')
        entries.add(key);closed=archive['closeout']
        marker=signed(one(db,RETIREMENTS,key),pin)
        need(marker['entry_id']==key and marker['archive_fingerprint']==digest(archive),'ARCHIVE_RETIREMENT_BINDING_CHANGED')
        need(aware(closed['snapshot']['completed_at'])<=aware(snapshot['generated_at']),
             'REENTRY_CAPTURE_PRECEDES_CLOSED_HISTORY')
        old_orders,old_positions=validate_account_rows(closed['snapshot']);position_keys.update(old_positions)
        for oid,o in old_orders.items():
            need(oid not in archived_orders,'ORDER_OWNED_BY_MULTIPLE_ARCHIVES')
            archived_orders[oid]=order_identity(o)
        for t in closed['snapshot']['trades']:
            tid=(t['order_id'],t['trade_id']);need(tid not in archived_trades,'TRADE_OWNED_BY_MULTIPLE_ARCHIVES')
            archived_trades[tid]=trade_identity(t)
        for table,result in [('requests',broker_requests),('attempts',broker_attempts),('receipts',broker_receipts),('candidate_existing_request_claims_v1',broker_claims)]:
            for row in closed['source']['broker'][table]:
                need(row[0] not in result,'BROKER_RECORD_OWNED_BY_MULTIPLE_ARCHIVES');result[row[0]]=row
    need(entries,'CLOSED_HISTORY_REQUIRED')
    current=broker_view(db)
    for table,expected in [('requests',broker_requests),('attempts',broker_attempts),('receipts',broker_receipts),('candidate_existing_request_claims_v1',broker_claims)]:
        need({row[0]:row for row in current[table]}==expected,'UNATTRIBUTED_OR_CHANGED_ADAPTER_HISTORY')
    need({oid:order_identity(o) for oid,o in orders.items()}==archived_orders,
         'UNATTRIBUTED_OR_CHANGED_ACCOUNT_ORDER')
    need({(t['order_id'],t['trade_id']):trade_identity(t) for t in snapshot['trades']}==archived_trades,
         'UNATTRIBUTED_OR_CHANGED_ACCOUNT_TRADE')
    need(position_keys<=set(positions) and not any(positions.values()),'EXPLICIT_FLAT_REENTRY_POSITION_REQUIRED')
    return entries


def review_next_entry(app,adapter,pin,authority,*,journal,sequence,account_capture,
                      market_bundle,fee_buffer_cents,clock,expected_version,bridge_run_id):
    exact(app,adapter,pin,authority)
    need(type(fee_buffer_cents) is int and fee_buffer_cents>0,'POSITIVE_REENTRY_FEE_BUFFER_REQUIRED')
    now=clock();records=verified_records(journal)
    need(type(sequence) is int and 1<=sequence<=len(records),'REENTRY_SEQUENCE_INVALID')
    events=accepted(records[sequence-1]);need(len(events)==1 and events[0]['role']=='ENTRY','FRESH_SINGLE_REENTRY_REQUIRED')
    event=events[0]
    with transaction(app,adapter.store.path) as db:
        need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in ACTIVE),
             'ACTIVE_CYCLE_BLOCKS_REENTRY')
        need(one(db,'broker.meta',1)==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'REENTRY_ADAPTER_META_CHANGED')
        need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in ('intents','sim_orders','sim_fills')),
             'REENTRY_CONTROLLER_EXECUTION_REQUIRES_REVIEW')
        entries=attribute_history(db,pin,account_capture,now)
        need(event['id'] not in entries and not db.execute('SELECT 1 FROM preparation_consumed WHERE id=?',(event['id'],)).fetchone(),
             'OLD_OR_CONSUMED_REENTRY_SIGNAL')
        expected_exits=set()
        for raw, in db.execute('SELECT data FROM '+ARCHIVES):
            archived=json.loads(raw)['closeout'];cursor=archived['source']['cursor']
            expected_exits.add(archived['exit_event']['id'])
            need(cursor['path']==str(Path(journal).resolve()) and 0<cursor['sequence']<sequence<=len(records)
                 and records[cursor['sequence']-1]['record_hash']==cursor['hash'],
                 'REENTRY_JOURNAL_HISTORY_PREFIX_CHANGED')
        need({r[0] for r in db.execute('SELECT id FROM preparation_exit_dispatch')}==expected_exits,
             'UNATTRIBUTED_CLOSED_EXIT_BLOCKS_REENTRY')
        control=one(db,'control',1);stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        need(type(expected_version) is int and control['version']==expected_version and control['mode']=='ARMED'
             and control.get('reconciled') is True and control.get('last_reconciled_at')
             and 0<=(now-aware(control['last_reconciled_at'])).total_seconds()<=30
             and stop is not None and stop[0]==stop[1],'REENTRY_CURRENT_CONTROLLER_REQUIRED')
        need(control.get('resumed_at') and aware(event['event_at'])>aware(control['resumed_at'])
             and day(now)==control['session_date']==day(aware(event['event_at']))
             and 0<=(now-aware(event['event_at'])).total_seconds()<=60 and entry_clock_open(now),
             'FRESH_POST_RESUME_REENTRY_REQUIRED')
        health=one(db,'sim_bridge_health',1)
        need(health.get('run_id')==bridge_run_id and effective(health,now)['healthy'],'REENTRY_BRIDGE_NOT_CURRENT')
        plans=validate(market_bundle,pin,as_of=now.isoformat())
        plan=next(p for p in plans if p['direction']==event['direction'])
        # This one activity blocker is attributable ONLY after exact signed
        # history/account/adapter matching above. All other blockers are retained.
        reasons=set(plan['reasons'])-{'ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED'}
        need(not reasons,'REENTRY_MARKET_OR_CASH_REJECTED')
        cash=market_bundle['cash_capture']
        cash_orders,cash_positions=validate_account_rows(dict(cash,completed_at=cash['completed_at']))
        account_orders,account_positions=validate_account_rows(account_capture)
        need({k:order_identity(v) for k,v in cash_orders.items()}=={k:order_identity(v) for k,v in account_orders.items()}
             and cash_positions==account_positions
             and {(t['order_id'],t['trade_id']):trade_identity(t) for t in cash['trades']}==
                 {(t['order_id'],t['trade_id']):trade_identity(t) for t in account_capture['trades']},
             'REENTRY_CASH_ACCOUNT_ROWS_DIFFER')
        need(not cash.get('diagnostics',{}).get('issues',[]),'REENTRY_CASH_DIAGNOSTICS_REQUIRE_REVIEW')
        grid=inspect_quote(plan['contract'],plan['quote'],profile=PROFILE)
        premium=Decimal(grid['ask'])*plan['quantity']*100
        need(premium==premium.to_integral_value() and int(premium)+fee_buffer_cents<=plan['half_cash_cap_cents'],
             'REENTRY_CURRENT_HALF_CASH_CAP_EXCEEDED')
        return dict(status='CLOSED_HISTORY_REENTRY_REVIEW_ELIGIBLE',matched_closed_cycles=len(entries),
            event_id=event['id'],instrument=plan['instrument'],quantity=plan['quantity'],
            proposed_budget_cents=int(premium)+fee_buffer_cents,current_half_cash_cap_cents=plan['half_cash_cap_cents'],
            history_attributed=True,application_source_reentry_integrated=False,
            new_preparation_created=False,automatic_next_entry_enabled=False,
            entry_permission=False,reservation_release_permission=False,production_execution_enabled=False)
