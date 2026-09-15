from datetime import datetime
from market_lab.oi_futures_vwap_standalone_v1_5min import confluence_direction,is_five_minute_checkpoint,oi_direction

def test_bullish_oi(): assert oi_direction("LONG_BUILDUP","SHORT_BUILDUP")=="BULLISH"
def test_bearish_oi(): assert oi_direction("SHORT_BUILDUP","LONG_BUILDUP")=="BEARISH"
def test_other_is_neutral(): assert oi_direction("LONG_UNWINDING","SHORT_COVERING")=="NEUTRAL"
def test_bullish_needs_vwap_alignment():
    assert confluence_direction("LONG_BUILDUP","SHORT_BUILDUP",101,100)=="BULLISH"
    assert confluence_direction("LONG_BUILDUP","SHORT_BUILDUP",99,100)=="NEUTRAL"
def test_bearish_needs_vwap_alignment():
    assert confluence_direction("SHORT_BUILDUP","LONG_BUILDUP",99,100)=="BEARISH"
    assert confluence_direction("SHORT_BUILDUP","LONG_BUILDUP",101,100)=="NEUTRAL"
def test_five_minute_clock():
    assert is_five_minute_checkpoint(datetime(2026,9,15,9,20))
    assert not is_five_minute_checkpoint(datetime(2026,9,15,9,21))
