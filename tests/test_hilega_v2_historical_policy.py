import ast
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime,time,timedelta
from pathlib import Path
from types import SimpleNamespace
import random
import unittest
from scripts.backtest_hilega_wma_gap_490 import ordered_gap_confirmation

@dataclass
class Event:
    event_type:str='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'
    event_time:datetime=None
    price:float=None
    entry_time:datetime=None
    entry_price:float=None
    state_before:str=None
    state_after:str=None
    details:dict=None

def load_gate():
    source=Path(__file__).parents[1]/'backend/market_lab/hilega_wma_gap_live_v2.py'
    tree=ast.parse(source.read_text())
    nodes=[x for x in tree.body if isinstance(x,(ast.FunctionDef,ast.ClassDef)) and x.name in {'direction','WmaGapGate'}]
    ns=dict(datetime=datetime,time=time,timedelta=timedelta,replace=replace,
            BEARISH_ENTRY_EVENTS={'ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21'},BEARISH_EXIT_EVENTS=set())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
    return ns['WmaGapGate']

class HistoricalPolicyTest(unittest.TestCase):
    def test_historical_gate_parity(self):
        rng=random.Random(490);start=datetime.fromisoformat('2026-10-09T10:00:00+05:30')
        for side in ['BULLISH','BEARISH']:
            sign=1 if side=='BULLISH' else -1
            for run in range(250):
                gate=load_gate()();event=Event(event_time=start-timedelta(minutes=5),details={})
                if side=='BEARISH':event.event_type='ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21'
                gate.signal(event,start);trace=[];live=None
                for i in range(11):
                    stamp=start+timedelta(minutes=i);strength=rng.choice([-.2,.4,.75,.8,1.2]);gap=rng.choice([-1.,0.,.1,.5,1.,2.])
                    wma=100+sign*strength;ema=wma+sign*gap
                    current=SimpleNamespace(ready=True,wma21_rsi=wma,ema3_rsi=ema,rsi9=ema+sign)
                    reference=SimpleNamespace(ready=True,wma21_rsi=100)
                    trace.append(dict(trade_id='test',session_date='2026-10-09',direction=side,
                        strategy_signal_timestamp=event.event_time.isoformat(),minute_timestamp=stamp.isoformat(),
                        within_confirmation_window=i<10,directional_wma_change=strength,
                        provisional_ema3_rsi=ema,provisional_wma21_rsi=wma,observed_close=200+i))
                    entries,_=gate.evaluate(minute=stamp,current=current,reference=reference,price=200+i)
                    if entries and live is None:live=entries[0].entry_time-timedelta(minutes=1)
                expected,_=ordered_gap_confirmation(trace,.75)
                self.assertEqual(live,datetime.fromisoformat(expected['confirmation_timestamp']) if expected else None)

    def test_exit_boundary_cannot_confirm(self):
        gate=load_gate()();start=datetime.fromisoformat('2026-10-09T10:00:00+05:30')
        gate.signal(Event(event_time=start,details={}),start)
        current=SimpleNamespace(ready=True,wma21_rsi=101,ema3_rsi=103,rsi9=104)
        ref=SimpleNamespace(ready=True,wma21_rsi=100)
        gate.previous={'minute':start-timedelta(minutes=2),'snapshot':current,'wma_change':1}
        entries,checks=gate.evaluate(minute=start-timedelta(minutes=1),current=current,reference=ref,price=200,exit_boundary=True)
        self.assertFalse(entries);self.assertFalse(checks[0]['same_exit_boundary_confirmation'])
