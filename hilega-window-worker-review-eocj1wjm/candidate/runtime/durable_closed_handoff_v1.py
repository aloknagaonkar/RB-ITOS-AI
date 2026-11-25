"""Durable closed review of an existing request; never submission authority."""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import hmac
import json
import sqlite3

from authenticated_handoff_v1 import review, need
from market_lab.hilega_preparation_runtime_v1.evidence import digest, aware, day
from market_lab.hilega_preparation_runtime_v1.limit_candidate import fresh_plan
from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open
from market_lab.hilega_preparation_runtime_v1.ownership_state import rollback_database
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
from market_lab.hilega_production_bridge_health_v1 import effective
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE

TABLE='preparation_closed_handoff_receipts_v1'
MODEL='HILEGA_DURABLE_CLOSED_HANDOFF_V1'
FALSE_FLAGS=('entry_permission','orders_sent','production_execution_enabled',
             'reservation_release_permission','execution_adoption_implemented')


def one(db, table, key):
    row=db.execute('SELECT data FROM '+table+' WHERE id=?',(key,)).fetchone()
    need(row is not None,'HANDOFF_SOURCE_ROW_REQUIRED')
    return json.loads(row[0])


@contextmanager
def transaction(app_store, adapter_path):
    app,broker=map(rollback_database,(app_store.path,adapter_path))
    need(not app.samefile(broker),'DISTINCT_HANDOFF_DATABASES_REQUIRED')
    with app_store.lock():
        db=sqlite3.connect(app.as_uri()+'?mode=rw',uri=True,timeout=10)
        try:
            db.execute('ATTACH DATABASE ? AS broker',(broker.as_uri()+'?mode=rw',))
            need(all(db.execute('PRAGMA '+s+'.journal_mode').fetchone()[0]=='delete'
                     for s in ('main','broker')),'DELETE_JOURNAL_REQUIRED')
            db.execute('PRAGMA main.synchronous=FULL')
            db.execute('PRAGMA broker.synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:db.close()


def existing(db,pin,key,provenance):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():
        return None
    raw=db.execute('SELECT data FROM '+TABLE+' WHERE id=?',(key,)).fetchone()
    if raw is None:return None
    row=json.loads(raw[0]);payload=dict(row);signature=payload.pop('signature',None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         'HANDOFF_RECEIPT_SIGNATURE_INVALID')
    need(row['model']==MODEL and row['account_scope']==pin['scope']
         and row['request_id']==key and row['historical_provenance']==provenance
         and all(row.get(k) is False for k in FALSE_FLAGS), 'HANDOFF_RECEIPT_BINDING_CHANGED')
    return row


def current(db,pin,key,bundle,now,expected_version,bridge_run_id):
    control=one(db,'control',1)
    need(type(expected_version) is int and control['version']==expected_version,
         'HANDOFF_CONTROL_VERSION_CHANGED')
    need(control['mode']=='PAUSED'
         and control.get('reason')=='APPLICATION_UNSENT_PREPARATION_REQUIRES_REVIEW',
         'PREPARATION_REVIEW_PAUSE_REQUIRED')
    stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
    need(stop is not None and stop[0]==stop[1],'HANDOFF_STOP_PENDING')
    plan=one(db,'preparation_plans',key)
    need(day(now)==control['session_date']==day(aware(plan['signal_at']))
         and 0<=(now-aware(plan['signal_at'])).total_seconds()<=60
         and control.get('resumed_at') and aware(plan['signal_at'])>aware(control['resumed_at'])
         and entry_clock_open(now),'HANDOFF_SIGNAL_SESSION_OR_WINDOW_INVALID')
    health=one(db,'sim_bridge_health',1)
    need(health.get('run_id')==bridge_run_id and effective(health,now)['healthy'],
         'HANDOFF_BRIDGE_NOT_CURRENT')
    need(all(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==1 for t in (
        'preparation_plans','preparation_shadow_holds','preparation_outbox',
        'preparation_request_bindings','preparation_cash_reservations','broker.requests')),
        'SINGLE_EXISTING_PREPARATION_REQUIRED')
    need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in (
        'broker.attempts','broker.receipts','intents','sim_orders','sim_fills')),
        'HANDOFF_EXISTING_EXECUTION_REQUIRES_RECOVERY')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    need('preparation_exit_dispatch' not in tables or not db.execute(
        'SELECT 1 FROM preparation_exit_dispatch LIMIT 1').fetchone(),
        'HANDOFF_CLOSED_EXIT_REQUIRES_REVIEW')
    selected=fresh_plan(bundle,pin,plan['direction'],now,PROFILE)
    need(selected['instrument']==plan['instrument'] and selected['quantity']==plan['quantity']
         and digest(selected['contract'])==plan['evidence']['contract_fingerprint'],
         'HANDOFF_CURRENT_CONTRACT_CHANGED')
    out=one(db,'preparation_outbox',key);candidate=out['disabled_request_candidate']
    body=candidate['draft']['body'];price=Decimal(str(body['price']))
    ask=Decimal(str(selected['pricing_preview']['ask']))
    need(body['order_type']=='LIMIT' and price>=ask,'HANDOFF_CURRENT_ASK_EXCEEDS_EXISTING_LIMIT')
    cost=price*body['quantity']*100
    need(cost==cost.to_integral_value() and int(cost)==candidate['premium_cents'],
         'HANDOFF_EXISTING_PREMIUM_CHANGED')
    budget=candidate['budget_cents'];buffer=candidate['fee_buffer_cents']
    hold=one(db,'preparation_shadow_holds',key)
    need(type(buffer) is int and buffer>0 and type(budget) is int
         and budget==candidate['premium_cents']+buffer
         and budget<=hold['held_cents']<=selected['half_cash_cap_cents'],
         'HANDOFF_FRESH_CASH_OR_BUDGET_INSUFFICIENT')
    return dict(control_version=control['version'],control_fingerprint=digest(control),
        bridge_run_id=bridge_run_id,bridge_fingerprint=digest(health),
        fresh_bundle_fingerprint=digest(bundle),fresh_cash_cap_cents=selected['half_cash_cap_cents'],
        existing_budget_cents=budget,existing_limit_price=str(price),
        fresh_best_ask=str(ask),reviewed_at=now.isoformat())


def record_closed_handoff(app_store,adapter_path,pin,*,journal,request_id,
                          capture_provider,clock,expected_version,bridge_run_id,
                          checkpoint=lambda point:None):
    # A durable replay is evidence only. It grants no current clearance and needs
    # neither a new capture nor another preparation. Existing attempts go to recovery.
    with transaction(app_store,adapter_path) as db:
        provenance=review(db,pin,journal=journal,request_id=request_id)
        old=existing(db,pin,request_id,provenance)
        if old:return dict(record=old,idempotent_replay=True,current_checks_reexecuted=False,
                           production_execution_enabled=False)
    # Slow capture does not hold the application lock or a database transaction.
    bundle=deepcopy(capture_provider())
    with transaction(app_store,adapter_path) as db:
        provenance=review(db,pin,journal=journal,request_id=request_id)
        old=existing(db,pin,request_id,provenance)
        if old:return dict(record=old,idempotent_replay=True,current_checks_reexecuted=False,
                           production_execution_enabled=False)
        checked=current(db,pin,request_id,bundle,clock(),expected_version,bridge_run_id)
        row=dict(model=MODEL,account_scope=pin['scope'],request_id=request_id,
            historical_provenance=provenance,current_review=checked,
            execution_permission='CLOSED_IN_CODE',
            **{k:False for k in FALSE_FLAGS})
        row['signature']=sign(row,pin)
        db.execute('CREATE TABLE IF NOT EXISTS '+TABLE+'(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        db.execute('INSERT INTO '+TABLE+' VALUES(?,?)',(request_id,json.dumps(row,sort_keys=True)))
        checkpoint('AFTER_HANDOFF_INSERT')
        checkpoint('BEFORE_HANDOFF_COMMIT')
        final=current(db,pin,request_id,bundle,clock(),expected_version,bridge_run_id)
        need({k:v for k,v in final.items() if k!='reviewed_at'}==
             {k:v for k,v in checked.items() if k!='reviewed_at'},'HANDOFF_CURRENT_REVIEW_CHANGED')
        need(review(db,pin,journal=journal,request_id=request_id)==provenance,
             'HANDOFF_PROVENANCE_CHANGED_BEFORE_COMMIT')
    return dict(record=row,idempotent_replay=False,current_checks_reexecuted=True,
                production_execution_enabled=False)
