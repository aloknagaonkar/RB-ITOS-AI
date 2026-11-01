
from datetime import datetime
from market_lab.oi_p1_vwap_36_sessions_v2 import aligned, causal_bar

def test_alignment():
    assert aligned("BULLISH","ABOVE")
    assert aligned("BEARISH","BELOW")
    assert not aligned("BULLISH","BELOW")
    assert not aligned("BEARISH","ABOVE")

def test_causal_bar():
    bars=[
        {"candle_label":"14:20","_avail":datetime.fromisoformat("2026-08-25T14:25:00+05:30")},
        {"candle_label":"14:25","_avail":datetime.fromisoformat("2026-08-25T14:30:00+05:30")},
    ]
    t=datetime.fromisoformat("2026-08-25T14:25:00+05:30")
    assert causal_bar(bars,t)["candle_label"]=="14:20"
