import importlib.util, sys
from pathlib import Path

P=Path(__file__).resolve().parents[1]/"scripts"/"validate_trend_pullback_continuation_price_structure_v1.py"
spec=importlib.util.spec_from_file_location("tpc_v1",P); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)

def test_ema_constant_series_is_constant():
    assert m.ema([10,10,10,10],3)==[10.0,10.0,10.0,10.0]

def test_direction_value_is_symmetric():
    assert m.direction_value("BULLISH",7)==7
    assert m.direction_value("BEARISH",7)==-7

def test_bullish_pullback_resume_detected_causally():
    closes=[100,101,102,103,104,105,106,107,108,109,110,109,108,111]
    e3=m.ema(closes,3); e10=m.ema(closes,10); e21=m.ema(closes,21)
    c=m.conditions_at(13,closes,e3,e10,e21)
    assert c["A_TREND_RESUME"]==(True,"BULLISH")

def test_no_trigger_without_countertrend_pullback():
    closes=list(range(100,114))
    e3=m.ema(closes,3); e10=m.ema(closes,10); e21=m.ema(closes,21)
    c=m.conditions_at(13,closes,e3,e10,e21)
    assert not c["A_TREND_RESUME"][0]
