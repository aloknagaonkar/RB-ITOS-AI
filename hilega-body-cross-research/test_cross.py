import importlib.util
from pathlib import Path
s=importlib.util.spec_from_file_location('bodycross_rules',Path(__file__).with_name('rules.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def frame(**kw):
 f=dict(open=110,high=110,low=90,close=95,ema10=98,previous_ema10=99);f.update(kw);return f

def test_bear_less_than_half_beyond_allowed():
 r=m.qualify('BEARISH',frame());assert r and r['body_beyond_ema']<.5

def test_bull_symmetric():
 assert m.qualify('BULLISH',frame(open=90,close=105,ema10=102,previous_ema10=101))

def test_exact_sixty_fails():
 assert m.qualify('BEARISH',frame(open=110,close=98,ema10=100)) is None

def test_wick_only_fails():
 assert m.qualify('BEARISH',frame(ema10=111,previous_ema10=112)) is None

def test_body_endpoint_touch_fails():
 assert m.qualify('BEARISH',frame(ema10=110,previous_ema10=111)) is None

def test_close_location_still_required():
 assert m.qualify('BEARISH',frame(close=96,ema10=98)) is None

def test_slope_still_required():
 assert m.qualify('BEARISH',frame(previous_ema10=97)) is None

def test_midpoint_waiting_unchanged():
 s=m.qualify('BEARISH',frame())
 assert m.decision(s,100)=='WAIT'
 assert m.decision(s,101)=='CANCEL_MIDPOINT'
 assert m.decision(s,89)=='ENTRY'
