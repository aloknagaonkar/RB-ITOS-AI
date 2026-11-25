"""Dedicated history-aware NEXT disabled preparation. No submission authority."""
from copy import deepcopy
from decimal import Decimal
import hmac
import json
from pathlib import Path
from application_cycle_close_v1 import (
    ACTIVE, ARCHIVES, attribute_history, archive_checked, transaction, one, broker_view,
    maybe, signed, seal, need, digest, port, exact, validate, inspect_quote, PROFILE,
    verified_records, accepted, aware, day, effective, entry_clock_open,
)
from market_lab.hilega_preparation_runtime_v1.evidence import FLAGS
from market_lab.hilega_preparation_runtime_v1.cash_reservation import reserve_local
from market_lab.hilega_preparation_runtime_v1.source import event_digest
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_nifty_option_price_grid_v1 import normalized_tick

ADMISSIONS='preparation_history_aware_admissions_v1'
MODEL='HILEGA_HISTORY_AWARE_DISABLED_PREPARATION_V1'


def replay(db,pin,key,input_fp):
    old=maybe(db,ADMISSIONS,key)
    if old is None:return None
    signed(old,pin)
    need(old['model']==MODEL and old['request_id']==key and old['input_fingerprint']==input_fp,
         'IMMUTABLE_HISTORY_PREPARATION_CONFLICT')
    for table in ACTIVE:
        need(digest(one(db,table,key))==old['active_fingerprints'][table],
             'HISTORY_PREPARATION_REFERENCE_CHANGED')
    found=db.execute('SELECT fingerprint,data FROM broker.requests WHERE id=?',(key,)).fetchone()
    need(found is not None and found[0]==old['request_fingerprint'],
         'HISTORY_PREPARATION_REQUEST_CHANGED')
    row=json.loads(found[1])
    stable={k:row[k] for k in ('request_id','draft','signal_id','signal_at','direction','reservation_reference')}
    need(port.sha(stable)==found[0],'HISTORY_PREPARATION_REQUEST_CHANGED')
    return dict(status='HISTORICAL_NEXT_PREPARATION_REPLAY',request_id=key,
                idempotent_replay=True,new_preparation_created=False,
                entry_permission=False,orders_sent=False,production_execution_enabled=False)


def reviewed_snapshot(db,pin,*,journal,sequence,account,market,now,
                      expected_version,bridge_run_id,fee_buffer_cents):
    need(type(fee_buffer_cents) is int and fee_buffer_cents>0,'POSITIVE_REENTRY_FEE_BUFFER_REQUIRED')
    need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in ACTIVE),
         'ACTIVE_CYCLE_BLOCKS_REENTRY')
    need(one(db,'broker.meta',1)==dict(scope=pin['scope'],mode='LIVE_CLOSED'),
         'REENTRY_ADAPTER_META_CHANGED')
    need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone()
                 for t in ('intents','sim_orders','sim_fills')),
         'REENTRY_CONTROLLER_EXECUTION_REQUIRES_REVIEW')
    entries=attribute_history(db,pin,account,now)
    path=Path(journal)
    need(path.is_file() and not path.is_symlink(),'REGULAR_REENTRY_JOURNAL_REQUIRED')
    records=verified_records(path)
    need(type(sequence) is int and 1<=sequence<=len(records),'REENTRY_SEQUENCE_INVALID')
    events=accepted(records[sequence-1])
    need(len(events)==1 and events[0]['role']=='ENTRY','FRESH_SINGLE_REENTRY_REQUIRED')
    event=events[0];key=event['id']
    need(key not in entries and not db.execute('SELECT 1 FROM preparation_consumed WHERE id=?',(key,)).fetchone(),
         'OLD_OR_CONSUMED_REENTRY_SIGNAL')
    archives=[];expected_exits=set()
    for raw, in db.execute('SELECT data FROM '+ARCHIVES):
        archive=archive_checked(json.loads(raw),pin);archives.append(digest(archive))
        closed=archive['closeout'];cursor=closed['source']['cursor']
        expected_exits.add(closed['exit_event']['id'])
        need(cursor['path']==str(path.resolve()) and 0<cursor['sequence']<sequence<=len(records)
             and records[cursor['sequence']-1]['record_hash']==cursor['hash'],
             'REENTRY_JOURNAL_HISTORY_PREFIX_CHANGED')
    need({r[0] for r in db.execute('SELECT id FROM preparation_exit_dispatch')}==expected_exits,
         'UNATTRIBUTED_CLOSED_EXIT_BLOCKS_REENTRY')
    cursor=one(db,'preparation_source',1)
    need(cursor['path']==str(path.resolve()) and cursor['sequence']+1==sequence
         and (cursor['sequence']==0 or records[cursor['sequence']-1]['record_hash']==cursor['hash']),
         'NEXT_CONSECUTIVE_SOURCE_RECORD_REQUIRED')
    control=one(db,'control',1);stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
    need(type(expected_version) is int and control['version']==expected_version
         and control['mode']=='ARMED' and control.get('reconciled') is True
         and control.get('last_reconciled_at')
         and 0<=(now-aware(control['last_reconciled_at'])).total_seconds()<=30
         and stop is not None and stop[0]==stop[1],'REENTRY_CURRENT_CONTROLLER_REQUIRED')
    need(control.get('resumed_at') and aware(event['event_at'])>aware(control['resumed_at'])
         and day(now)==control['session_date']==day(aware(event['event_at']))
         and 0<=(now-aware(event['event_at'])).total_seconds()<=60 and entry_clock_open(now),
         'FRESH_POST_RESUME_REENTRY_REQUIRED')
    health=one(db,'sim_bridge_health',1)
    need(health.get('run_id')==bridge_run_id and effective(health,now)['healthy'],
         'REENTRY_BRIDGE_NOT_CURRENT')
    selected=next(p for p in validate(market,pin,as_of=now.isoformat()) if p['direction']==event['direction'])
    reasons=set(selected['reasons'])-{'ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED'}
    need(not reasons,'REENTRY_MARKET_OR_CASH_REJECTED')
    from application_cycle_close_v1 import validate_account_rows,order_identity,trade_identity
    cash=market['cash_capture'];co,cp=validate_account_rows(cash);ao,ap=validate_account_rows(account)
    need({k:order_identity(v) for k,v in co.items()}=={k:order_identity(v) for k,v in ao.items()}
         and cp==ap and {(t['order_id'],t['trade_id']):trade_identity(t) for t in cash['trades']}==
             {(t['order_id'],t['trade_id']):trade_identity(t) for t in account['trades']},
         'REENTRY_CASH_ACCOUNT_ROWS_DIFFER')
    need(not cash.get('diagnostics',{}).get('issues',[]),'REENTRY_CASH_DIAGNOSTICS_REQUIRE_REVIEW')
    grid=inspect_quote(selected['contract'],selected['quote'],profile=PROFILE)
    premium=Decimal(grid['ask'])*selected['quantity']*100
    need(premium==premium.to_integral_value() and int(premium)+fee_buffer_cents<=selected['half_cash_cap_cents'],
         'REENTRY_CURRENT_HALF_CASH_CAP_EXCEEDED')
    return event,records[sequence-1],control,selected,grid,int(premium),sorted(archives)


def prepare_next_disabled(app,adapter,pin,authority,*,journal,sequence,account_capture,
                          market_bundle,fee_buffer_cents,clock,expected_version,bridge_run_id,
                          checkpoint=lambda at:None):
    exact(app,adapter,pin,authority)
    path=Path(journal)
    need(path.is_file() and not path.is_symlink(),'REGULAR_REENTRY_JOURNAL_REQUIRED')
    records=verified_records(path)
    need(type(sequence) is int and 1<=sequence<=len(records),'REENTRY_SEQUENCE_INVALID')
    events=accepted(records[sequence-1])
    need(len(events)==1 and events[0]['role']=='ENTRY','FRESH_SINGLE_REENTRY_REQUIRED')
    key=events[0]['id'];account=deepcopy(account_capture);market=deepcopy(market_bundle)
    input_fp=digest(dict(journal=str(path.resolve()),sequence=sequence,record_hash=records[sequence-1]['record_hash'],
        account=account,market=market,fee_buffer_cents=fee_buffer_cents,
        expected_version=expected_version,bridge_run_id=bridge_run_id))
    with transaction(app,adapter.store.path) as db:
        old=replay(db,pin,key,input_fp)
        if old:return old
        event,record,control,selected,grid,premium,archives=reviewed_snapshot(
            db,pin,journal=path,sequence=sequence,account=account,market=market,now=clock(),
            expected_version=expected_version,bridge_run_id=bridge_run_id,fee_buffer_cents=fee_buffer_cents)
        now=clock();budget=premium+fee_buffer_cents
        evidence=deepcopy(selected)
        evidence.update(reasons=[],evidence_checks_passed=True,proposed_cost_cents=budget,
                        closed_history_fingerprints=archives,history_attribution_scope='EXACT_CLOSED_CYCLES_ONLY')
        plan=dict(FLAGS,id=key,signal_at=event['event_at'],direction=event['direction'],
            source_sequence=sequence,source_record_hash=record['record_hash'],
            instrument=selected['instrument'],quantity=selected['quantity'],status='EVIDENCE_LINKED_UNSENT',
            evidence=evidence,account_scope=pin['scope'],created_at=now.isoformat())
        hold=dict(FLAGS,id=key,held_cents=budget,evidence_mode='REAL_CASH_OBSERVED_SHADOW_ONLY',real_cash_reserved=False)
        out=dict(FLAGS,id=key,reservation_reference=key,bundle_fingerprint=digest(market),
            instrument=selected['instrument'],quantity=selected['quantity'],
            status='NON_EXECUTABLE_PRICING_POLICY_PENDING',request_body=None)
        contract=dict(selected['contract'])
        for name in ('lot_size','minimum_lot','freeze_quantity'):
            need(not isinstance(contract[name],bool) and int(contract[name])==contract[name],
                 'INTEGRAL_REENTRY_CONTRACT_REQUIRED')
            contract[name]=int(contract[name])
        need(selected['quantity']==contract['lot_size'],'EXACTLY_ONE_REENTRY_LOT_REQUIRED')
        request_draft=draft(contract,request_id=key,side='BUY',lots=1,as_of=now.isoformat(),
            order_type='LIMIT',limit_price=grid['ask'],normalized_tick_rupees=normalized_tick(contract,profile=PROFILE))
        out['disabled_request_candidate']=dict(FLAGS,model='HILEGA_HISTORY_AWARE_DISABLED_LIMIT_CANDIDATE_V1',
            preparation_id=key,reservation_reference=key,premium_cents=premium,fee_buffer_cents=fee_buffer_cents,
            budget_cents=budget,pricing_policy_approved=False,fee_buffer_approved_for_production=False,
            production_ready=False,draft=request_draft)
        request,fp=port.validated_request(request_draft,signal_id=key,signal_at=event['event_at'],
            direction=event['direction'],reservation_reference=key,as_of=now.isoformat())
        need(db.execute('SELECT 1 FROM broker.requests WHERE id=?',(key,)).fetchone() is None,
             'NEXT_REQUEST_ID_ALREADY_EXISTS')
        binding=dict(FLAGS,model='HILEGA_HISTORY_AWARE_DISABLED_REQUEST_BINDING_V1',id=key,
            account_scope=pin['scope'],request_fingerprint=fp,plan_fingerprint=digest(plan),
            hold_fingerprint=digest(hold),outbox_fingerprint=digest(out),held_cents=budget,
            cash_cap_cents=selected['half_cash_cap_cents'],bundle_fingerprint=digest(market),
            local_budget_reference_bound=True,broker_cash_locked=False,status='PREPARED_DISABLED_HOLD_RETAINED',
            closed_history_fingerprints=archives)
        # Last full eligibility check occurs before creating active references.
        reviewed_snapshot(db,pin,journal=path,sequence=sequence,account=account,market=market,now=clock(),
            expected_version=expected_version,bridge_run_id=bridge_run_id,fee_buffer_cents=fee_buffer_cents)
        before_broker=broker_view(db)
        db.execute('INSERT INTO preparation_plans VALUES(?,?)',(key,port.encode(plan)))
        db.execute('INSERT INTO preparation_shadow_holds VALUES(?,?)',(key,port.encode(hold)))
        db.execute('INSERT INTO preparation_outbox VALUES(?,?)',(key,port.encode(out)))
        db.execute('INSERT INTO preparation_request_bindings VALUES(?,?)',(key,port.encode(binding)))
        reserve_local(db,plan,hold,out,pin,selected,fp,now=now)
        checkpoint('AFTER_NEXT_ACTIVE_REFERENCES')
        db.execute('INSERT INTO broker.requests VALUES(?,?,?)',(key,fp,port.encode(request)))
        db.execute('INSERT INTO broker.events(data) VALUES(?)',(port.encode(dict(
            type='REQUEST_PREPARED',request_id=key,origin='HISTORY_AWARE_DISABLED_PREPARATION',
            production_execution_enabled=False)),))
        checkpoint('AFTER_NEXT_DISABLED_REQUEST')
        old_evidence=db.execute('SELECT data FROM preparation_evidence WHERE digest=?',(digest(market),)).fetchone()
        need(old_evidence is None or json.loads(old_evidence[0])==market,'REENTRY_EVIDENCE_CONFLICT')
        db.execute('INSERT OR IGNORE INTO preparation_evidence VALUES(?,?)',(digest(market),port.encode(market)))
        receipt=seal(dict(model=MODEL,account_scope=pin['scope'],request_id=key,input_fingerprint=input_fp,
            request_fingerprint=fp,closed_history_fingerprints=archives,
            active_fingerprints={t:digest(one(db,t,key)) for t in ACTIVE},
            entry_permission=False,reservation_release_permission=False,production_execution_enabled=False),pin)
        db.execute('CREATE TABLE IF NOT EXISTS '+ADMISSIONS+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        db.execute('INSERT INTO '+ADMISSIONS+' VALUES(?,?)',(key,port.encode(receipt)))
        db.execute('INSERT INTO preparation_consumed VALUES(?,?)',(key,event_digest(event)))
        db.execute('UPDATE preparation_source SET data=? WHERE id=1',(port.encode(dict(
            path=str(path.resolve()),sequence=sequence,hash=record['record_hash'])),))
        paused=deepcopy(control);paused.update(mode='PAUSED',version=control['version']+1,reconciled=False,
            reason='APPLICATION_UNSENT_PREPARATION_REQUIRES_REVIEW')
        db.execute('UPDATE control SET data=? WHERE id=1',(port.encode(paused),))
        checkpoint('BEFORE_NEXT_PREPARATION_COMMIT')
        final=clock()
        need(day(final)==day(now) and 0<=(final-now).total_seconds()<=10
             and 0<=(final-aware(event['event_at'])).total_seconds()<=60 and entry_clock_open(final),
             'NEXT_PREPARATION_EXPIRED_BEFORE_COMMIT')
        # All old broker evidence must remain byte-for-byte intact; only this
        # new disabled request and its preparation event may be added.
        current=broker_view(db);new_rows=[r for r in current['requests'] if r[0]==key]
        need(len(new_rows)==1 and json.loads(new_rows[0][2])==request,'NEXT_REQUEST_CHANGED_BEFORE_COMMIT')
        current['requests']=[r for r in current['requests'] if r[0]!=key]
        need(current==before_broker,'OLD_BROKER_EVIDENCE_CHANGED_DURING_PREPARATION')
        # Revalidate signed current market/cash freshness after all waits.
        again=next(p for p in validate(market,pin,as_of=final.isoformat()) if p['direction']==event['direction'])
        need(set(again['reasons'])<={'ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED'}
             and again['instrument']==selected['instrument'] and again['quantity']==selected['quantity']
             and again['half_cash_cap_cents']==selected['half_cash_cap_cents'],'NEXT_EVIDENCE_CHANGED_OR_STALE')
        inspect_quote(again['contract'],again['quote'],profile=PROFILE)
        final_records=verified_records(path)
        need(len(final_records)>=sequence and final_records[sequence-1]['record_hash']==record['record_hash'],
             'NEXT_JOURNAL_CHANGED_BEFORE_COMMIT')
        need(one(db,'control',1)==paused,'NEXT_CONTROL_CHANGED_BEFORE_COMMIT')
    return dict(status='HISTORY_AWARE_NEXT_DISABLED_PREPARATION_COMMITTED',request_id=key,
        idempotent_replay=False,new_preparation_created=True,new_buy_attempt_created=False,
        installed_source_reentry_hook_enabled=False,entry_permission=False,orders_sent=False,
        production_execution_enabled=False)
