from datetime import datetime,timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
spec=importlib.util.spec_from_file_location('no_touch_study',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
AT=datetime.fromisoformat('2026-10-21T09:20:00+05:30')

def frame(side='BULLISH',touch=False):
    bull=side=='BULLISH'
    return dict(available_at=AT.isoformat(),rsi_available_at=AT.isoformat(),
        open=102 if bull else 98,close=104 if bull else 96,
        high=105 if bull else (100 if touch else 99),low=(100 if touch else 101) if bull else 95,
        ema10=100,previous_ema10=99 if bull else 101,
        rsi9=70 if bull else 30,previous_rsi9=65 if bull else 35,
        ema3_rsi=60 if bull else 40,previous_ema3_rsi=55 if bull else 45,
        wma21_rsi=50,previous_wma21_rsi=47 if bull else 53)

def evaluate(side='BULLISH',touch=False,enabled=True,weak=False,magnitude_low=False):
    policy=m.study_policy(enabled);f=frame(side,touch)
    if magnitude_low and side=='BULLISH':f['previous_wma21_rsi']=49
    if weak:f['previous_wma21_rsi']=49.5 if side=='BULLISH' else 50.5
    g=policy.make_gate({AT:f})
    event=policy.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',AT,None,'IDLE','ARMED',details={})
    g.pending[side]=dict(event=event,available=AT,armed_at=None)
    snap=NS(ready=True,rsi9=f['rsi9'],ema3_rsi=f['ema3_rsi'],wma21_rsi=f['wma21_rsi'])
    ref=NS(ready=True,rsi9=f['previous_rsi9'],ema3_rsi=f['previous_ema3_rsi'],wma21_rsi=f['previous_wma21_rsi'])
    result=g.evaluate(minute=AT-timedelta(minutes=1),current=snap,reference=ref,price=f['close'])
    return g,result

@pytest.mark.parametrize('side',['BULLISH','BEARISH'])
def test_actual_gate_clear_signal_enters(side):
    g,(entries,checks)=evaluate(side)
    assert len(entries)==1 and g.owner==side
    assert checks[-1]['ema10_entry']['entry_confirmation_route']=='SIGNAL_NO_EMA10_TOUCH'
    assert not getattr(g,'followup_signal',None)

@pytest.mark.parametrize('side',['BULLISH','BEARISH'])
def test_touch_equality_keeps_followup(side):
    g,(entries,checks)=evaluate(side,touch=True)
    assert not entries and g.owner=='NONE'
    assert g.followup_signal['due']==AT+timedelta(minutes=5)

@pytest.mark.parametrize('side',['BULLISH','BEARISH'])
def test_existing_control_still_waits(side):
    g,(entries,checks)=evaluate(side,enabled=False)
    assert not entries and g.followup_signal

@pytest.mark.parametrize('side',['BULLISH','BEARISH'])
def test_strength_failure_cannot_bypass(side):
    _,(entries,checks)=evaluate(side,weak=True)
    assert not entries

def test_bullish_magnitude_one_retains_followup():
    g,(entries,checks)=evaluate(magnitude_low=True)
    assert not entries and g.followup_signal
    assert not checks[-1]['ema10_entry']['no_touch_entry']['passed']

def test_monitor_retains_full_deployed_confirmation():
    p=m.study_policy()
    assert p._start_bullish_exit_monitor is m.base._start_bullish_exit_monitor
    assert m.base.advance_boundary is not p.advance_boundary

@pytest.mark.parametrize('field,value',[('available_at','2026-10-21T09:25:00+05:30'),('low',None),('ema10',float('nan'))])
def test_invalid_evidence_never_authorizes(field,value):
    evidence=dict(frame(),passed=True);evidence[field]=value
    assert not m.no_touch_check('BULLISH',evidence,AT)['passed']

def test_cutoff_denies_bypass():
    at=AT.replace(hour=14,minute=55)
    evidence=dict(frame(),passed=True,available_at=at.isoformat())
    assert not m.no_touch_check('BULLISH',evidence,at)['passed']
