"""Adopted BUY -> signed owned quantities -> explicit candidate EXIT/SELL.
No service hook, live clearance, reservation release or automatic opposite BUY.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import hmac
import json
from pathlib import Path
import uuid
from existing_request_attempt_v1 import (
    port, ADOPTIONS, CLAIMS, MODEL as ENTRY_MODEL, checked, signed, authority_check,
    EXPECTED_PORT_SHA, request_and_attempts,
)
from authenticated_handoff_v1 import need
from durable_closed_handoff_v1 import transaction, one
from owned_exit_pricing_candidate import review_owned_quote
from market_lab.hilega_preparation_runtime_v1.evidence import digest
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import verify, sign, aware, day
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.source import event_digest
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, normalized_tick

POSITIONS='preparation_candidate_position_reviews_v1'
EXIT_MODEL='HILEGA_APPLICATION_EXIT_ATTEMPT_CANDIDATE_V1'


def exact(app,adapter,pin,authority):
    path=Path(port.__file__)
    need(path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==EXPECTED_PORT_SHA,
         'PINNED_INSTALLED_PORT_REQUIRED')
    need(type(adapter) is port.Adapter and type(adapter.transport) is port.HttpTransport
         and type(adapter.store) is port.Store and adapter.store.mode=='LIVE_CLOSED'
         and adapter.store.scope==pin['scope'],'EXACT_CLOSED_ADAPTER_REQUIRED')
    authority_check(authority,pin)
    need(app.path.stat().st_dev==adapter.store.path.stat().st_dev,'SAME_FILESYSTEM_REQUIRED')


def adoption(db,key,pin,authority,model):
    need(one(db,'broker.meta',1)==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'LIFECYCLE_ADAPTER_META_CHANGED')
    left=checked(one(db,ADOPTIONS,key),authority)
    right=checked(one(db,'broker.'+CLAIMS,key),authority)
    request,fp,attempts=request_and_attempts(db,key)
    need(left==right and left['model']==model and left['account_scope']==pin['scope']
         and left['authority_id']==authority['authority_id'] and left['request_id']==key
         and left['request_fingerprint']==fp and left['production_execution_enabled'] is False
         and left['live_clearance_granted'] is False,'LIFECYCLE_ADOPTION_CHANGED')
    need(len(attempts)==1,'SINGLE_LIFECYCLE_ATTEMPT_REQUIRED')
    aid,rid,op,raw=attempts[0];attempt=json.loads(raw)
    wire=dict(method='POST',host='api-hft.upstox.com',path='/v3/order/place',body=request['draft']['body'])
    need(op=='PLACE' and rid==key and attempt['attempt_id']==aid==left['attempt_id']
         and attempt['request_id']==key and attempt['operation']=='PLACE'
         and attempt['wire']==wire and port.sha(wire)==left['wire_fingerprint'],
         'LIFECYCLE_ATTEMPT_CHANGED')
    return request,attempt,left


def position(db,adapter,pin,authority,entry_id,snapshot,now):
    verify(snapshot,pin,as_of=now.isoformat())
    need(snapshot.get('profile_verified_before_and_after') is True
         and snapshot.get('account_position_rows_complete') is True
         and snapshot.get('source_atomic') is False
         and snapshot.get('position_fill_linkage_verified') is False
         and snapshot.get('live_pnl') is None,'COMPLETE_NONATOMIC_CAPTURE_REQUIRED')
    need(isinstance(snapshot.get('diagnostics'),dict)
         and not snapshot['diagnostics'].get('issues',[]),'ACCOUNT_DIAGNOSTICS_REQUIRE_REVIEW')
    orders,positions=validate_account_rows(snapshot)
    parent,entry_attempt,entry_adoption=adoption(db,entry_id,pin,authority,ENTRY_MODEL)
    need(parent.get('order_id') and parent['state'] not in {'UNKNOWN','IN_FLIGHT'},'ENTRY_OUTCOME_REQUIRES_RECONCILIATION')
    plan=one(db,'preparation_plans',entry_id);hold=one(db,'preparation_shadow_holds',entry_id)
    out=one(db,'preparation_outbox',entry_id);binding=one(db,'preparation_request_bindings',entry_id)
    cash=verify_row(one(db,'preparation_cash_reservations',entry_id),pin)
    need(cash['plan_fingerprint']==digest(plan) and cash['shadow_hold_fingerprint']==digest(hold)
         and cash['outbox_fingerprint']==digest(out)
         and cash['request_fingerprint']==entry_adoption['request_fingerprint']==binding['request_fingerprint']
         and binding['plan_fingerprint']==digest(plan) and binding['hold_fingerprint']==digest(hold)
         and binding['outbox_fingerprint']==digest(out),'OWNED_APPLICATION_REFERENCES_CHANGED')
    need(plan['account_scope']==pin['scope'] and day(aware(parent['signal_at']))==snapshot['session_date'],
         'OWNED_ENTRY_SCOPE_OR_SESSION_CHANGED')
    requests=db.execute('SELECT id,fingerprint,data FROM broker.requests').fetchall()
    attempts=db.execute('SELECT id,request_id,operation,data FROM broker.attempts').fetchall()
    receipts=dict(db.execute('SELECT id,data FROM broker.receipts'))
    links=_check('LIVE_CLOSED',requests,attempts,receipts)
    need(links['unbound_request_count']==0,'UNBOUND_REQUEST_REQUIRES_RECOVERY')
    known={link['order_id']:link for link in links['bindings']}
    need(set(orders)==set(known),'UNATTRIBUTED_OR_MISSING_ACCOUNT_ORDER')
    need(len(requests) in {1,2} and all(link['reservation_reference']==entry_id for link in known.values()),
         'EXACT_SINGLE_LIFECYCLE_REQUIRED')
    for oid,order in orders.items():
        link=known[oid]
        need(all(order[k]==link[k] for k in ('instrument','product','side','quantity')),
             'OWNED_ORDER_CONTRACT_CHANGED')
        request=json.loads(next(raw for key,fp,raw in requests if key==link['request_id']))
        need(aware(order['placed_at'])>=aware(request['draft']['created_at']),'ORDER_PRECEDES_REQUEST')
    body=parent['draft']['body'];buy=orders[parent['order_id']]
    need(body['transaction_type']=='BUY' and buy['status']=='FILLED'
         and buy['filled']==body['quantity'] and buy['pending']==0,
         'FULL_TERMINAL_BUY_REQUIRED')
    sells=[link for link in known.values() if link['side']=='SELL']
    need(len(sells)<=1 and len(known)==1+len(sells),'EXACT_ENTRY_AND_OPTIONAL_EXIT_REQUIRED')
    exit_id=None;filled=pending=0;terminal=True
    if sells:
        link=sells[0];exit_id=link['request_id']
        sell,attempt,record=adoption(db,exit_id,pin,authority,EXIT_MODEL)
        need(record['entry_id']==entry_id and sell['direction']==parent['direction']
             and link['quantity']==buy['quantity'],'OWNED_EXIT_PARENT_CHANGED')
        order=orders[link['order_id']];filled=order['filled'];pending=order['pending']
        terminal=order['status'] in {'FILLED','CANCELLED','REJECTED'}
    remaining=buy['filled']-filled
    key=(body['instrument_token'],body['product'])
    need(key in positions,'MISSING_POSITION_ROW_IS_NOT_FLAT')
    need(positions[key]==remaining and all(q==0 for k,q in positions.items() if k!=key),
         'OWNED_POSITION_QUANTITY_MISMATCH')
    status=('FLAT_CONFIRMED_REFERENCE' if remaining==pending==0 and terminal else
            'EXIT_TERMINAL_RESIDUAL_REVIEW_REQUIRED' if sells and terminal and remaining else
            'EXIT_PARTIAL_PENDING' if filled else 'EXIT_WORKING' if sells else 'ENTRY_FILLED_REFERENCE')
    return dict(model='HILEGA_CANDIDATE_OWNED_POSITION_V1',status=status,
        account_scope=pin['scope'],entry_id=entry_id,exit_id=exit_id,
        entry_filled_quantity=buy['filled'],exit_filled_quantity=filled,
        remaining_quantity=remaining,pending_exit_quantity=pending,
        all_orders_terminal=terminal,snapshot_fingerprint=digest(snapshot),
        capture_completed_at=snapshot['completed_at'],assessed_at=now.isoformat(),
        application_reference_fingerprint=digest(dict(plan=plan,hold=hold,outbox=out,binding=binding,cash=cash)),
        strategy_ownership_verified=False,entry_permission=False,orders_sent=False,
        fees_complete=False,reservation_release_permission=False,production_execution_enabled=False)


def record_position(app,adapter,pin,authority,*,entry_id,capture_provider,clock,checkpoint=lambda at:None):
    exact(app,adapter,pin,authority);snapshot=deepcopy(capture_provider())
    with transaction(app,adapter.store.path) as db:
        report=position(db,adapter,pin,authority,entry_id,snapshot,clock())
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(POSITIONS,)).fetchone()
        old=db.execute('SELECT data FROM '+POSITIONS+' WHERE id=?',(entry_id,)).fetchone() if exists else None
        if old:
            previous=json.loads(old[0]);payload=dict(previous);sig=payload.pop('signature',None)
            need(isinstance(sig,str) and hmac.compare_digest(sign(payload,pin),sig),'POSITION_REVIEW_SIGNATURE_INVALID')
            need(previous['entry_id']==entry_id and previous['account_scope']==pin['scope']
                 and previous['application_reference_fingerprint']==report['application_reference_fingerprint']
                 and previous['production_execution_enabled'] is False,'POSITION_REVIEW_BINDING_CHANGED')
            need(report['exit_filled_quantity']>=previous['exit_filled_quantity']
                 and aware(report['capture_completed_at'])>=aware(previous['capture_completed_at']),
                 'POSITION_FILL_OR_CAPTURE_REGRESSION')
            if report['snapshot_fingerprint']==previous['snapshot_fingerprint']:
                return dict(report=previous,idempotent_replay=True,production_execution_enabled=False)
        row=deepcopy(report);row['signature']=sign(row,pin)
        db.execute('CREATE TABLE IF NOT EXISTS '+POSITIONS+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO '+POSITIONS+' VALUES(?,?)',(entry_id,port.encode(row)))
        checkpoint('AFTER_POSITION_REVIEW_INSERT')
        final=position(db,adapter,pin,authority,entry_id,snapshot,clock())
        need({k:v for k,v in final.items() if k!='assessed_at'}==
             {k:v for k,v in report.items() if k!='assessed_at'},'POSITION_CHANGED_BEFORE_COMMIT')
    return dict(report=row,idempotent_replay=False,production_execution_enabled=False)


def exit_event(db,journal,sequence,parent):
    path=Path(journal);need(path.is_file() and not path.is_symlink(),'REGULAR_EXIT_JOURNAL_REQUIRED')
    records=verified_records(path)
    need(type(sequence) is int and 1<=sequence<=len(records),'EXIT_SEQUENCE_INVALID')
    record=records[sequence-1];events=accepted(record);exits=[e for e in events if e['role']=='EXIT']
    need(len(exits)==1 and len(events) in {1,2},'SINGLE_EXIT_BOUNDARY_REQUIRED')
    event=exits[0]
    need(event['direction']==parent['direction'] and event.get('entry_reference_at')
         and aware(event['entry_reference_at'])==aware(parent['signal_at']),'EXIT_PARENT_REFERENCE_CHANGED')
    dispatch=one(db,'preparation_exit_dispatch',event['id'])
    need(dispatch['model']=='HILEGA_APPLICATION_CLOSED_EXIT_DISPATCH_V1'
         and dispatch['dispatch_status']=='REFUSED_CLOSED'
         and dispatch['automatic_execution_eligible'] is False
         and dispatch['production_execution_enabled'] is False
         and event_digest(dispatch['event'])==event_digest(event)
         and dispatch['boundary_fingerprints']==[list(v) for v in sorted((e['id'],event_digest(e)) for e in events)],
         'APPLICATION_CLOSED_EXIT_REFERENCE_CHANGED')
    cursor=one(db,'preparation_source',1)
    need(cursor['path']==str(path.resolve()) and sequence<=cursor['sequence']<=len(records)
         and records[cursor['sequence']-1]['record_hash']==cursor['hash'],'EXIT_APPLICATION_CURSOR_CHANGED')
    for e in events:
        row=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(e['id'],)).fetchone()
        need(row is not None and row[0]==event_digest(e),'EXIT_APPLICATION_CONSUMPTION_CHANGED')
    return event,record['record_hash']


def recover_exit(db,adapter,pin,authority,entry_id,exit_id):
    request,attempt,adopted=adoption(db,exit_id,pin,authority,EXIT_MODEL)
    need(adopted['entry_id']==entry_id and request['draft']['body']['transaction_type']=='SELL','EXIT_RECOVERY_PARENT_CHANGED')
    return request,attempt


def recover_only(adapter,request,attempt):
    with adapter.store.tx() as db:
        raw=db.execute('SELECT data FROM receipts WHERE id=?',(attempt['attempt_id'],)).fetchone()
    if raw:return adapter._bind_receipt(attempt,json.loads(raw[0]))
    with adapter.store.tx() as db:
        request['state']='UNKNOWN';attempt['state']='UNKNOWN'
        db.execute('UPDATE requests SET data=? WHERE id=?',(port.encode(request),request['request_id']))
        db.execute('UPDATE attempts SET data=? WHERE id=?',(port.encode(attempt),attempt['attempt_id']))
    return attempt


def submit_source_exit(app,adapter,pin,authority,*,entry_id,journal,exit_sequence,
                       capture_provider,clock,expected_version,checkpoint=lambda at:None):
    exact(app,adapter,pin,authority)
    with transaction(app,adapter.store.path) as db:
        parent,_,_=adoption(db,entry_id,pin,authority,ENTRY_MODEL)
        event,record_hash=exit_event(db,journal,exit_sequence,parent)
        exit_id=port.sha(['APPLICATION_EXIT_CANDIDATE_V1',entry_id,event['id']])
        old=db.execute('SELECT 1 FROM broker.requests WHERE id=?',(exit_id,)).fetchone()
        recovered=recover_exit(db,adapter,pin,authority,entry_id,exit_id) if old else None
    if recovered:
        result=recover_only(adapter,*recovered)
        return dict(status='EXISTING_SELL_RECOVERED_NO_SUBMISSION',exit_id=exit_id,
                    adapter_result=result,recovery_only=True,production_execution_enabled=False)
    try:adapter.transport.check()
    except port.GateClosed:
        return dict(status='PRODUCTION_MUTATIONS_CLOSED_IN_CODE',exit_id=exit_id,
                    recovery_only=False,production_execution_enabled=False)
    supplied=deepcopy(capture_provider())
    need(isinstance(supplied,dict) and set(supplied)=={'account','market'},'EXACT_EXIT_CAPTURES_REQUIRED')
    issued=clock();expires=issued+timedelta(seconds=10);checkpoint('AFTER_EXIT_CAPTURE')
    with transaction(app,adapter.store.path) as db:
        if db.execute('SELECT 1 FROM broker.requests WHERE id=?',(exit_id,)).fetchone():
            recovered=recover_exit(db,adapter,pin,authority,entry_id,exit_id)
        else:
            recovered=None;now=clock();need(issued<=now<expires,'EXIT_CANDIDATE_EXPIRED')
            parent,_,_=adoption(db,entry_id,pin,authority,ENTRY_MODEL)
            again,hashed=exit_event(db,journal,exit_sequence,parent)
            need(again==event and hashed==record_hash,'EXIT_JOURNAL_CHANGED')
            control=one(db,'control',1)
            need(type(expected_version) is int and control['version']==expected_version
                 and control['mode'] in {'PAUSED','ARMED'},'EXIT_CONTROL_VERSION_CHANGED')
            need(day(now)==day(aware(event['event_at'])) and 0<=(now-aware(event['event_at'])).total_seconds()<=60,
                 'EXIT_SIGNAL_STALE_OR_FUTURE')
            owned=position(db,adapter,pin,authority,entry_id,supplied['account'],now)
            need(owned['exit_id'] is None and owned['remaining_quantity']==owned['entry_filled_quantity'],
                 'NO_NEW_SELL_WITH_EXISTING_EXIT')
            contract=one(db,'preparation_plans',entry_id)['evidence']['contract']
            pricing=review_owned_quote(supplied['market'],pin,contract,quantity=owned['remaining_quantity'],as_of=now.isoformat())
            selected=dict(contract)
            for k in ('lot_size','minimum_lot','freeze_quantity'):
                need(not isinstance(selected[k],bool) and int(selected[k])==selected[k],'INTEGRAL_EXIT_CONTRACT_REQUIRED')
                selected[k]=int(selected[k])
            need(selected['lot_size']==owned['remaining_quantity'],'FULL_OWNED_LOT_EXIT_ONLY')
            request_draft=draft(selected,request_id=exit_id,side='SELL',lots=1,as_of=now.isoformat(),
                order_type='LIMIT',limit_price=pricing['limit_price'],normalized_tick_rupees=normalized_tick(selected,profile=PROFILE))
            request,fp=port.validated_request(request_draft,signal_id=event['id'],signal_at=event['event_at'],
                direction=event['direction'],reservation_reference=entry_id,as_of=now.isoformat())
            wire=adapter._wire(request,'PLACE');aid=uuid.uuid4().hex
            attempt=dict(attempt_id=aid,request_id=exit_id,operation='PLACE',wire=wire,state='IN_FLIGHT',retry_allowed=False)
            receipt=signed(dict(model=EXIT_MODEL,account_scope=pin['scope'],authority_id=authority['authority_id'],
                authorization_id=uuid.uuid4().hex,entry_id=entry_id,request_id=exit_id,request_fingerprint=fp,
                attempt_id=aid,wire_fingerprint=port.sha(wire),event=event,record_hash=record_hash,
                owned_review=owned,pricing=pricing,issued_at=issued.isoformat(),expires_at=expires.isoformat(),
                live_clearance_granted=False,production_execution_enabled=False),authority)
            db.execute('INSERT INTO '+ADOPTIONS+' VALUES(?,?)',(exit_id,port.encode(receipt)))
            db.execute('INSERT INTO broker.'+CLAIMS+' VALUES(?,?)',(exit_id,port.encode(receipt)))
            checkpoint('AFTER_EXIT_CLAIM')
            final=clock();need(issued<=final<expires,'EXIT_CANDIDATE_EXPIRED')
            final_owned=position(db,adapter,pin,authority,entry_id,supplied['account'],final)
            need({k:v for k,v in final_owned.items() if k!='assessed_at'}==
                 {k:v for k,v in owned.items() if k!='assessed_at'},'OWNED_QUANTITY_CHANGED_BEFORE_SELL')
            review_owned_quote(supplied['market'],pin,contract,quantity=owned['remaining_quantity'],as_of=final.isoformat())
            final_event,final_hash=exit_event(db,journal,exit_sequence,parent)
            need(final_event==event and final_hash==record_hash,'EXIT_JOURNAL_CHANGED_BEFORE_COMMIT')
            request['state']='IN_FLIGHT'
            db.execute('INSERT INTO broker.requests VALUES(?,?,?)',(exit_id,fp,port.encode(request)))
            db.execute('INSERT INTO broker.attempts VALUES(?,?,?,?)',(aid,exit_id,'PLACE',port.encode(attempt)))
            checkpoint('AFTER_EXIT_ATTEMPT_INSERT')
            need(issued<=clock()<expires,'EXIT_CANDIDATE_EXPIRED')
    if recovered:
        result=recover_only(adapter,*recovered)
        return dict(status='EXISTING_SELL_RECOVERED_NO_SUBMISSION',exit_id=exit_id,adapter_result=result,
                    recovery_only=True,production_execution_enabled=False)
    checkpoint('AFTER_EXIT_ATTEMPT_COMMIT')
    try:raw=adapter.transport.send(aid,wire)
    except Exception:
        result=recover_only(adapter,request,attempt)
        return dict(status='SELL_UNKNOWN_NO_RESUBMISSION',exit_id=exit_id,adapter_result=result,
                    recovery_only=False,production_execution_enabled=False)
    checkpoint('AFTER_EXIT_TRANSPORT_BEFORE_RECEIPT')
    adapter._persist_receipt(attempt,raw);checkpoint('AFTER_EXIT_RECEIPT_COMMIT')
    result=adapter._bind_receipt(attempt,raw)
    return dict(status='APPLICATION_EXIT_CANDIDATE_ACKNOWLEDGED',exit_id=exit_id,adapter_result=result,
                recovery_only=False,opposite_buy_submitted=False,production_execution_enabled=False)
