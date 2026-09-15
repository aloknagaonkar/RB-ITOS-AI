
from datetime import datetime
from market_lab.oi_p1_vwap_alignment_v1 import causal_bar, aligned

def test_causal_bar_uses_completed_only():
    bars=[
        {"candle_label":"14:20","_avail":datetime.fromisoformat("2026-08-25T14:25:00+05:30")},
        {"candle_label":"14:25","_avail":datetime.fromisoformat("2026-08-25T14:30:00+05:30")},
    ]
    e=datetime.fromisoformat("2026-08-25T14:25:00+05:30")
    assert causal_bar(bars,e)["candle_label"]=="14:20"

def test_alignment():
    assert aligned("BULLISH","ABOVE")
    assert aligned("BEARISH","BELOW")
    assert not aligned("BULLISH","BELOW")
