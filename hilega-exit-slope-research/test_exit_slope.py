from datetime import datetime,timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest
spec=importlib.util.spec_from_file_location('exit_slope',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.mark.parametrize('side,previous,current,allowed',[
    ('BULLISH',51,50,True),('BULLISH',49,50,False),('BULLISH',50,50,False),
    ('BEARISH',49,50,True),('BEARISH',51,50,False),('BEARISH',50,50,False)])
def test_slope_direction(side,previous,current,allowed):
    assert m.slope_check(side,NS(ready=True,wma21_rsi=current),NS(ready=True,wma21_rsi=previous))['slope_pass']==allowed

@pytest.mark.parametrize('side,previous,wma,allowed',[
    ('BULLISH',51,50,True),('BULLISH',49,50,False),
    ('BEARISH',49,50,True),('BEARISH',51,50,False),
    ('BEARISH',38,39,False),('BEARISH',39,40,False)])
def test_actual_normal_exit_preserves_wma40(side,previous,wma,allowed):
    p=m.study_policy({'BULLISH','BEARISH'})
    at=datetime.fromisoformat('2026-10-21T13:05:00+05:30')
    bull=side=='BULLISH'
    snap=NS(ready=True,rsi9=20 if bull else 70,ema3_rsi=25 if bull else 65,wma21_rsi=wma)
    ref=NS(ready=True,wma21_rsi=previous)
    g=p.make_gate({});g.owner=side;g.active=dict(time=at-timedelta(minutes=30),price=110)
    c=NS(on_bar=lambda bar:NS(accepted_events=[]),bullish=NS(previous_indicators=snap))
    tracker=NS(complete=lambda *a:{})
    with patch.object(g,'evaluate',return_value=([],[])),patch.object(g,'can_signal',return_value=False):
        r=p._advance_standard(c,g,NS(ts=at-timedelta(minutes=5),close=100),ref,tracker)
    assert bool(r['exits'])==allowed
    assert r['exit_validation']['original_dual_exit']
    assert r['exit_validation']['normal_exit_pass']==allowed

def test_missing_reference_blocks_slope():
    assert not m.slope_check('BEARISH',NS(ready=True,wma21_rsi=50),None)['slope_pass']

def test_isolation_keeps_live_module_unchanged():
    before=m.base._advance_standard
    p=m.study_policy({'BULLISH'})
    assert m.base._advance_standard is before and p._advance_standard is not before
