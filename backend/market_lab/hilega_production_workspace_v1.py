"""Authenticated simulator controls with separate opt-in GET-only broker evidence."""
from __future__ import annotations
import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict
from .hilega_production_foundation.core import Store,SimBroker,Service,Blocked
from . import hilega_production_broker_observation_v1 as broker_observation

MODEL='HILEGA_PRODUCTION_WORKSPACE_V1'
router=APIRouter(prefix='/api/hilega-production',tags=['hilega-production-preparation'])

def mode():
    value=os.getenv('HILEGA_PRODUCTION_WORKSPACE_MODE','DISABLED')
    if value not in {'DISABLED','SIMULATION_ONLY'}:raise HTTPException(503,'UNSUPPORTED_WORKSPACE_MODE')
    return value

def authorize(request:Request):
    expected=os.getenv('HILEGA_PRODUCTION_CONTROL_TOKEN','')
    token_file=os.getenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE')
    if token_file:
        try:expected=Path(token_file).read_text().strip()
        except OSError:raise HTTPException(503,'CONTROL_AUTH_NOT_CONFIGURED') from None
    if len(expected)<32:raise HTTPException(503,'CONTROL_AUTH_NOT_CONFIGURED')
    supplied=request.headers.get('authorization','')
    if not supplied.startswith('Bearer ') or not hmac.compare_digest(supplied[7:],expected):
        raise HTTPException(401,'CONTROL_AUTH_REQUIRED')
    # All new routes are same-origin only in the UI. CLI has no Origin header.
    origin=request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'CONTROL_ORIGIN_REJECTED')
    return 'shared-control-credential'

def service():
    if mode()!='SIMULATION_ONLY':raise HTTPException(409,'PRODUCTION_SUBMISSION_DISABLED')
    path=Path(os.getenv('HILEGA_PRODUCTION_SIM_DB','data/research/hilega-production-workspace/sim.sqlite'))
    store=Store(path)
    return Service(store,SimBroker(store),worker_start=False)


def report():
    ready=[dict(check=n,status='NOT_VALIDATED') for n in (
        'PRODUCTION_STATIC_IP','PRODUCTION_AUTHENTICATION','FUNDS_FIELD_MAPPING','PLUS_FEED_ENTITLEMENT',
        'REAL_ORDER_AND_FILL_RECONCILIATION','EXTERNAL_EXIT_ATTRIBUTION','LIVE_QUOTES_AND_PNL',
        'STRATEGY_EVENT_DISPATCH','ALLOCATION_RESERVATION','DAILY_LOSS_LIMIT','CONTROLLED_PILOT')]
    result=dict(model=MODEL,generated_at=datetime.now(timezone.utc).isoformat(),workspace_mode=mode(),
        production_execution_enabled=False,production_orders_sent=False,readiness='NOT_CLEARED_FOR_PRODUCTION',
        policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='bullish-gap2-full-wma2-2.0.0-wma40-reversal',
        source='SIMULATOR_ONLY' if mode()=='SIMULATION_ONLY' else 'DISABLED',
        configuration=dict(strike_offsets=[0],lots_per_strike=1,allocation_fraction='0.50',daily_loss_limit=None,
            editable=False,note='Agreed initial configuration; live cash and contract mapping not wired'),
        readiness_checks=ready,broker_connected=False,available_cash=None,live_pnl=None,
        positions=[],orders=[],closed_trades=[],events=[],blocked_outcomes=[],
        blocked_outcomes_status='NOT_IMPLEMENTED',control=None,label='PRODUCTION_DISABLED',
        strategy_worker_controlled=False)
    if mode()=='SIMULATION_ONLY':
        s=service();snap=s.status();rows=snap['positions']
        positions=[];closed=[]
        for row in rows:
            if row['side']!='BUY':continue
            exits=[i for i in rows if i.get('parent')==row['id']]
            remaining=row['filled']-sum(i['filled'] for i in exits)
            item=dict(position_id=row['id'],instrument=row['instrument'],filled_quantity=row['filled'],
                remaining_quantity=remaining,average_entry=row.get('average_price'),
                external_observed_quantity=row.get('external_observed_quantity'),ltp=None,unrealised_pnl=None,
                simulation_only=True,exit_pending=any(e['status'] not in {'FILLED','CANCELLED','REJECTED'} for e in exits),
                reconciliation_required='external_observed_quantity' in row)
            if remaining>0 or row.get('cleanup') or item['reconciliation_required']:positions.append(item)
            elif row['filled']>0 and exits:closed.append(item)
        result.update(positions=positions,orders=rows,closed_trades=closed,events=s.store.events()[-200:],
            control=snap['control'],label=snap['label'],durable_execution=snap['durable_execution'],bridge_health=snap['bridge_health'],allocation=snap['allocation'],last_reconciled_at=snap['control'].get('last_reconciled_at'))
    from .hilega_execution_port_v1 import availability
    result['broker_execution_port']=availability()
    from .hilega_preparation_runtime_v1 import summary
    result['application_preparation']=summary(s.store) if mode()=='SIMULATION_ONLY' else None
    if result['application_preparation'] and result['application_preparation']['route']=='PREPARATION_ONLY':
        result['source']='EVIDENCE_PREPARATION_ONLY'
        result['broker_execution_port']['active_execution_route']='APPLICATION_PREPARATION_ONLY'
        result['label']=snap['label']
        result['configuration']['note']='One-lot evidence-bound unsent preparation; pricing policy and real reservation still pending'
    result['broker_observation']=broker_observation.display()
    return result

class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['pause','resume','reconcile','exit','flatten']
    request_id:UUID
    expected_version:int|None=None
    session_date:str|None=None
    position_id:str|None=None
    confirmation:str

@router.get('/execution-preparation')
def execution_preparation(actor=Depends(authorize)):
    try:
        from .hilega_preparation_runtime_v1 import summary
        return summary(service().store)
    except HTTPException:raise
    except Exception:raise HTTPException(503,'PREPARATION_STATE_UNAVAILABLE') from None

@router.get('/status')
def status(actor=Depends(authorize)):
    try:return report()
    except HTTPException:raise
    except Exception:raise HTTPException(503,'WORKSPACE_STATE_UNAVAILABLE') from None

@router.post('/commands')
def command(body:Command,actor=Depends(authorize)):
    if body.confirmation!='SIMULATION_ONLY':raise HTTPException(400,'SIMULATION_CONFIRMATION_REQUIRED')
    s=service()
    try:
        answer=s.command(body.action,request_id=str(body.request_id),expected_version=body.expected_version,
            session_date=body.session_date,actor=actor,position_id=body.position_id)
        return dict(result=answer,snapshot=report())
    except Blocked as exc:raise HTTPException(409,str(exc)) from None
    except Exception:raise HTTPException(503,'COMMAND_OUTCOME_UNCONFIRMED_REFRESH_STATE') from None

@asynccontextmanager
async def workspace_lifespan():
    task=None
    broker_task=None
    if os.getenv('HILEGA_PRODUCTION_WORKSPACE_MODE','DISABLED')=='SIMULATION_ONLY':
        s=service()
        # Startup block is durable. Broker checks run even with no browser connected.
        with s.store.lock():s._block('API_START_RECONCILIATION_REQUIRED')
        async def monitor():
            while True:
                def poll():
                    with s.store.lock():s._session();s._reconcile();s._watch_bridge_locked()
                try:await asyncio.to_thread(poll)
                except Exception:
                    # Unavailable state cannot permit entries; exceptions are not printed.
                    pass
                await asyncio.sleep(5)
        task=asyncio.create_task(monitor())
    if broker_observation.enabled() and mode()=='SIMULATION_ONLY':
        broker_task=asyncio.create_task(broker_observation.monitor())
    try:yield
    finally:
        if broker_task:
            broker_task.cancel()
            try:await broker_task
            except asyncio.CancelledError:pass
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
