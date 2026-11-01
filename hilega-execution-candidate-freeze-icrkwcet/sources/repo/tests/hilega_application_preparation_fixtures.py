"""Synthetic signed records only. No live provenance or trading approval claimed."""
import copy
import json
import sqlite3
from datetime import datetime,timedelta
import pytest
from market_lab.hilega_preparation_runtime_v1.evidence import MODEL,MODE,FLAGS,validate,evaluate,Blocked
from market_lab.hilega_production_account_adapter_v1 import sign
from market_lab.hilega_production_foundation.core import Store,encode
from market_lab.hilega_production_bridge_health_v1 import MODEL as HEALTH_MODEL

T=datetime.fromisoformat('2026-10-26T09:25:00+05:30')
PIN=dict(scope='UPSTOX:'+'b'*64,key='11'*32)


def ts(seconds=0):return (T+timedelta(seconds=seconds)).isoformat()


def resign(bundle):
    bundle.pop('signature',None)
    bundle['signature']=sign(bundle,PIN)
    return bundle


def resign_cash(bundle):
    cash=bundle['cash_capture'];cash.pop('signature',None);cash['signature']=sign(cash,PIN)
    return resign(bundle)


def bundle():
    funds=dict(cash_available_to_trade='100000',cash_margin_used='0',
               field='data.available_to_trade.cash_available_to_trade.total')
    cash=dict(model='HILEGA_READ_ONLY_CASH_OBSERVATION_V1',evidence_mode=MODE,
        snapshot_id='synthetic-cash',account_scope=PIN['scope'],account_identity_verified=True,
        status='READ_ONLY_CAPTURED',started_at=ts(1),completed_at=ts(2),session_date='2026-10-26',
        production_execution_enabled=False,orders_sent=False,entry_permission=False,
        funds_before=copy.deepcopy(funds),funds_after=copy.deepcopy(funds),
        funds_changed_during_capture=False,orders=[],trades=[],positions=[],
        diagnostics=dict(issues=[]),account_position_rows_complete=True)
    cash['signature']=sign(cash,PIN)
    contracts=[]
    for strike in (24950,25000,25050):
        for side in ('CE','PE'):
            contracts.append(dict(instrument_key='NSE_FO|'+str(strike*10+(1 if side=='CE' else 2)),
                underlying_key='NSE_INDEX|Nifty 50',instrument_type=side,segment='NSE_FO',exchange='NSE',
                expiry='2026-10-27',strike_price=strike,lot_size=65,minimum_lot=65,
                freeze_quantity=1800,tick_size=5))
    quotes={'underlying':dict(instrument_token='NSE_INDEX|Nifty 50',last_price=25000,timestamp=ts(2))}
    for c in contracts:
        if c['strike_price']==25000:
            quotes[c['instrument_key']]=dict(instrument_token=c['instrument_key'],last_price=100,
                timestamp=ts(2),last_trade_time=ts(2),volume=10000,
                depth=dict(buy=[dict(price=99.95,quantity=130)],sell=[dict(price=100,quantity=130)]))
    result=dict(model=MODEL,evidence_mode=MODE,snapshot_id='synthetic-bundle',account_scope=PIN['scope'],
        started_at=ts(),completed_at=ts(3),session_date='2026-10-26',profile_verified_before_and_after=True,
        market_before=dict(exchange='NSE',status='NORMAL_OPEN'),market_after=dict(exchange='NSE',status='NORMAL_OPEN'),
        cash_before_market=copy.deepcopy(funds),cash_after_market=copy.deepcopy(funds),cash_capture=cash,
        spot_initial=25000,contracts=contracts,quotes=quotes,**FLAGS)
    return resign(result)


