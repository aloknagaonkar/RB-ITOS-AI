"""Central single-leg simulator reservation gate. No real cash or broker transport."""
from datetime import datetime
from decimal import Decimal,ROUND_DOWN,ROUND_UP
import json,os
from .hilega_production_foundation.core import Blocked,TERMINAL,encode,money

def ensure(store,at):
    """Called under the Service control lock. Enrollment cannot be cleared by env."""
    with store.db() as d:
        row=d.execute('SELECT data FROM sim_allocation_config WHERE id=1').fetchone()
        if row:return
        d.execute('INSERT INTO sim_allocation_config VALUES(1,?)',(encode(dict(required=True,buffer='100',enrolled_at=at.isoformat(),evidence_mode='SYNTHETIC_SIMULATOR_ONLY')),))
    store.event('SIM_ALLOCATION_ENROLLED',at.isoformat(),production_execution_enabled=False)

def config(store):
    with store.db() as d:r=d.execute('SELECT data FROM sim_allocation_config WHERE id=1').fetchone()
    return json.loads(r[0]) if r else None

def rows(store):
    with store.db() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM sim_allocation_reservations ORDER BY rowid')]

def amount(cents):return str((Decimal(cents)/100).quantize(Decimal('.01')))

def needs_hold(row,intents):
    exits=[x for x in intents.values() if x.get('parent')==row['id']]
    return row['status'] not in TERMINAL or row['filled']-sum(x['filled'] for x in exits)!=0 or any(x['status'] not in TERMINAL for x in exits)

def summary(store,at):
    try:
        c=config(store)
        if c is None:return dict(required=False,status='NOT_ENABLED_LEGACY_FIXTURE',ready=False,production_execution_enabled=False)
        if c.get('required') is not True:raise ValueError()
        holds=rows(store);intents={i['id']:i for i in store.intents()}
        held=sum(x['held_cents'] for x in holds);funds=c.get('funds');age=None;cap=None;reason=None
        if funds:
            stamp=datetime.fromisoformat(funds['at']);age=(at-stamp).total_seconds()
            if stamp.date()!=at.date() or not 0<=age<=30:reason='FUNDS_STALE_OR_WRONG_SESSION'
            cap=int((money(funds['cash'])*Decimal('.5')*100).to_integral_value(rounding=ROUND_DOWN))
        else:reason='SYNTHETIC_FUNDS_NOT_CONFIGURED'
        orphan=any(x['held_cents'] and (x['id'] not in intents or intents[x['id']]['status'] in {'UNKNOWN','REQUESTED'}) for x in holds)
        missing=any(i['side']=='BUY' and needs_hold(i,intents) and i['id'] not in {x['id'] for x in holds} for i in intents.values())
        if orphan or missing:reason='ALLOCATION_OUTCOME_REVIEW_REQUIRED'
        if cap is not None and held>cap:reason='HOLDS_EXCEED_LATEST_CAP'
        return dict(model='HILEGA_CENTRAL_SIM_ALLOCATION_V1',required=True,status=reason or 'READY_SIMULATION_ONLY',ready=reason is None,
            evidence_mode='SYNTHETIC_SIMULATOR_ONLY',synthetic_available_cash=funds['cash'] if funds else None,
            half_cash_cap=amount(cap) if cap is not None else None,held_total=amount(held),
            remaining_capacity=amount(max(0,cap-held)) if cap is not None else None,funds_age_seconds=round(age,3) if age is not None else None,
            buffer_per_entry=c['buffer'],reservations=holds,production_execution_enabled=False,entry_permission=False,
            multi_leg_supported=False,real_funds_mapping='NOT_WIRED')
    except Exception:return dict(required=True,status='ALLOCATION_EVIDENCE_UNAVAILABLE',ready=False,production_execution_enabled=False)

def require_ready(store,at):
    state=summary(store,at)
    if state['required'] and not state['ready']:raise Blocked('SIM_ALLOCATION_'+state['status'])

def synthetic_funds(service,cash):
    value=money(cash)
    with service.store.lock():
        ensure(service.store,service.now());c=config(service.store)
        c['funds']=dict(cash=str(value),at=service.now().isoformat(),evidence_mode='EXPLICIT_SYNTHETIC_FIXTURE')
        with service.store.db() as d:d.execute('UPDATE sim_allocation_config SET data=? WHERE id=1',(encode(c),))
        service.store.event('SIM_ALLOCATION_SYNTHETIC_FUNDS_UPDATED',service.now().isoformat(),production_execution_enabled=False)
        return summary(service.store,service.now())

def reserve(service,sid,*,instrument,quantity,price):
    store=service.store;at=service.now();c=config(store)
    if c is None:return # Legacy standalone fixture only; workspace/reader enroll on startup.
    require_ready(store,at)
    if instrument not in {'SIMULATOR|CE','SIMULATOR|PE'}:raise Blocked('SIM_ALLOCATION_SYNTHETIC_INSTRUMENT_ONLY')
    raw=money(price)*quantity+money(c['buffer']);requested=int((raw*100).to_integral_value(rounding=ROUND_UP))
    state=summary(store,at)
    if Decimal(state['held_total'])+Decimal(requested)/100>Decimal(state['half_cash_cap']):raise Blocked('SIM_ALLOCATION_HALF_CASH_CAP_EXCEEDED')
    row=dict(id=sid,instrument=instrument,quantity=quantity,price=str(money(price)),amount_cents=requested,held_cents=requested,
        state='RESERVED',created_at=at.isoformat(),evidence_mode='SYNTHETIC_SIMULATOR_ONLY')
    with store.db() as d:d.execute('INSERT INTO sim_allocation_reservations VALUES(?,?)',(sid,encode(row)))
    store.event('SIM_ALLOCATION_RESERVED_BEFORE_BUY',at.isoformat(),intent_id=sid,amount=amount(requested))

def reconcile(service):
    """Only after installed Service has checked all simulator order/position evidence."""
    store=service.store
    if config(store) is None:return
    intents={x['id']:x for x in store.intents()};holds=rows(store)
    if any(i['side']=='BUY' and needs_hold(i,intents) and i['id'] not in {x['id'] for x in holds} for i in intents.values()):raise Blocked('UNRESERVED_SIM_ENTRY_REQUIRES_REVIEW')
    for hold in holds:
        row=intents.get(hold['id'])
        if row is None:
            if hold['held_cents']:raise Blocked('RESERVATION_WITHOUT_INTENT_REQUIRES_REVIEW')
            continue
        if row['instrument']!=hold['instrument'] or row['quantity']!=hold['quantity']:raise Blocked('ALLOCATION_INTENT_MISMATCH')
        remaining,exits=service._remaining(row)
        flat=(row['status'] in TERMINAL and remaining==0 and all(e['status'] in TERMINAL for e in exits) and not row.get('cleanup'))
        if hold['state']=='RELEASED' and not flat:raise Blocked('RELEASED_ALLOCATION_HAS_EXPOSURE')
        if row['filled'] and money(row['average_price'])*row['filled']>Decimal(hold['amount_cents'])/100:raise Blocked('FILL_EXCEEDS_RESERVED_COST')
        new='RELEASED' if flat else 'EXPOSURE_HELD' if row['filled'] else 'ORDER_PENDING'
        if hold['state']!=new:
            hold.update(state=new,held_cents=0 if flat else hold['amount_cents'],updated_at=service.now().isoformat())
            with store.db() as d:d.execute('UPDATE sim_allocation_reservations SET data=? WHERE id=?',(encode(hold),hold['id']))
            store.event('SIM_ALLOCATION_RECONCILED',service.now().isoformat(),intent_id=hold['id'],state=new,held=amount(hold['held_cents']))
