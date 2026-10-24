import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('independent_rules',HERE/'rules.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def frame(**kw):
 f=dict(open=110,high=110,low=90,close=96,ema10=98,previous_ema10=99)
 f.update(kw);return f

def test_no_existing_setup_needed():
 q=r.candidates(frame());assert len(q)==1 and q[0]['direction']=='BEARISH'

def test_no_outer_quarter_needed():
 assert r.qualify('BEARISH',frame()) # close30% from low

def test_less_than_half_beyond_allowed():
 assert r.qualify('BEARISH',frame())['body_beyond_ema']<.5

def test_bull_symmetric():
 assert r.qualify('BULLISH',frame(open=90,close=104,ema10=102,previous_ema10=101))

def test_exact_sixty_rejected():
 assert r.qualify('BEARISH',frame(close=98,ema10=100)) is None

def test_wick_only_rejected():
 assert r.qualify('BEARISH',frame(ema10=111,previous_ema10=112)) is None

def test_body_endpoint_touch_rejected():
 assert r.qualify('BEARISH',frame(ema10=110,previous_ema10=111)) is None

def test_wrong_slope_rejected():
 assert r.qualify('BEARISH',frame(previous_ema10=97)) is None

def test_bear_breakout_and_midpoint():
 q=r.qualify('BEARISH',frame())
 assert r.decision(q,89)=='ENTRY'
 assert r.decision(q,101)=='CANCEL_MIDPOINT'
 assert r.decision(q,100)=='WAIT'
 assert r.decision(q,90)=='WAIT'

def test_bull_breakout_and_midpoint():
 q=r.qualify('BULLISH',frame(open=90,close=104,ema10=102,previous_ema10=101))
 assert r.decision(q,111)=='ENTRY'
 assert r.decision(q,99)=='CANCEL_MIDPOINT'
 assert r.decision(q,100)=='WAIT'

def test_aug7_1005_now_qualifies():
 q=r.candidates(dict(open=24627.05,high=24627.05,low=24607.5,close=24613.8,
     ema10=24616.75957011018,previous_ema10=24617.41725235689))
 assert len(q)==1 and q[0]['direction']=='BEARISH'

def test_support_preserves_entry(monkeypatch):
 spec=importlib.util.spec_from_file_location('independent_runner',HERE/'run.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 monkeypatch.setattr(m.core.legacy5,'direction',lambda e:e.side)
 from datetime import datetime
 at=datetime.fromisoformat('2026-08-07T10:25:00+05:30')
 active=dict(direction='BEARISH',entry_time='10:07',entry_price=100,quantity=65)
 event=SimpleNamespace(side='BEARISH',entry_price=99,details={'passed':True})
 audit=[]
 assert m.record_support(active,at,dict(entries=[event],frame={'rsi9':40}),audit)
 assert active['entry_time']=='10:07' and active['entry_price']==100 and active['quantity']==65
 assert len(audit)==1 and audit[0]['additional_position'] is False
 assert audit[0]['informational_only'] is True
