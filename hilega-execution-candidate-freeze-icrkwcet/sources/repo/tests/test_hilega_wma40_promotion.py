from datetime import datetime,timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest
from market_lab import hilega_combined_policy_v1 as p

def scenario(wma=39,rsi=45,ema=44,confirmed=False,side='BEARISH',manual=False):
    at=datetime.fromisoformat('2026-10-21T13:05:00+05:30')
    snap=NS(ready=True,rsi9=rsi,ema3_rsi=ema,wma21_rsi=wma)
    g=p.make_gate({});g.owner=side;g.active=dict(time=at-timedelta(minutes=30),price=110)
    c=NS(bullish=NS(previous_indicators=snap))
    g._bullish_exit_monitor=(c,None,None)
    result=dict(current=snap,entries=[],exits=[],checks=[],policy_events=[],
        exit_validation=dict(direction=side,rsi_opposite=True,ema_opposite=True,
            wma21=wma,dual_exit_pass=True,normal_exit_pass=False,wma40_required=True,
            wma_above40=wma>40,reversal_confirmed=False,action='HOLD_WMA_LE40'))
    event=p.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at,None,'IDLE','ACTIVE',
        price=100,entry_time=at,entry_price=100,details={'qualified_signal_time':(at-timedelta(minutes=5)).isoformat()})
    monitor_result=dict(entries=[event] if confirmed else [],checks=[],policy_events=[],setups=[])
    def advance(cc,*args,**kwargs):return result if cc is not c else monitor_result
    real=NS(bullish=NS(previous_indicators=snap))
    with patch.object(p,'_advance_standard',side_effect=advance):
        output=p.advance_boundary(real,g,NS(ts=at-timedelta(minutes=5),close=100),snap,None,manual)
    return g,output

def test_confirmed_reversal_closes_before_entry():
    g,r=scenario(confirmed=True)
    assert g.owner=='BULLISH'
    assert len(r['exits'])==len(r['entries'])==1
    assert r['exits'][0].exit_reason=='FULLY_CONFIRMED_OPPOSITE_BULLISH'
    assert r['exits'][0].points==10
    assert r['exit_validation']['reversal_confirmed']

def test_unconfirmed_candidate_cannot_reverse():
    g,r=scenario()
    assert g.owner=='BEARISH' and not r['exits'] and not r['entries']

def test_manual_reset_discards_monitor():
    g,r=scenario(confirmed=True,manual=True)
    assert not r['entries'] and g._bullish_exit_monitor is None

def test_reset_pending_clears_monitor():
    g=p.make_gate({});g._bullish_exit_monitor=object();p.reset_pending(g)
    assert g._bullish_exit_monitor is None

@pytest.mark.parametrize('w,allowed',[(39,False),(40,False),(40.001,True)])
def test_actual_normal_exit_threshold(w,allowed):
    # Exercise the actual standard boundary, not a duplicate exit implementation.
    at=datetime.fromisoformat('2026-10-21T13:05:00+05:30')
    snap=NS(ready=True,rsi9=45,ema3_rsi=44,wma21_rsi=w)
    g=p.make_gate({});g.owner='BEARISH';g.active=dict(time=at-timedelta(minutes=30),price=110)
    dec=NS(accepted_events=[])
    c=NS(on_bar=lambda bar:dec,bullish=NS(previous_indicators=snap))
    tracker=NS(complete=lambda *a:{})
    with patch.object(g,'evaluate',return_value=([],[])),patch.object(g,'can_signal',return_value=False):
        r=p._advance_standard(c,g,NS(ts=at-timedelta(minutes=5),close=100),snap,tracker)
    assert bool(r['exits'])==allowed
    assert r['exit_validation']['normal_exit_pass']==allowed

def test_inspection_explains_held_dual_exit():
    from market_lab.hilega_combined_policy_inspection_v1 import inspection
    rows=inspection(dict(exit_validation=dict(direction='BEARISH',dual_exit_pass=True,
        wma40_required=True,wma_above40=False,wma21=39,normal_exit_pass=False,
        reversal_confirmed=False,action='HOLD_WMA_LE40')))
    assert any(r['label']=='Bearish WMA40 exit permission' and r['status']=='FAIL' for r in rows)

def test_production_policy_has_no_dynamic_source_execution():
    import inspect
    source=inspect.getsource(p)
    assert 'exec(' not in source and 'compile(' not in source
