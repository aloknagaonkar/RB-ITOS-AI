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

def test_canonical_futures_vwap_schema_uses_session_vwap(tmp_path):
    from market_lab.oi_futures_vwap_standalone_v1_5min import load_futures_index

    p = tmp_path / "futures.csv"
    p.write_text(
        "session_date,timestamp,close,session_vwap,instrument_key,expiry\n"
        "2026-09-15,2026-09-15T09:20:00+05:30,25010,25000,NSE_FO|TEST,2026-09-29\n"
    )

    idx = load_futures_index(p)
    row = idx[("2026-09-15", "2026-09-15T09:20:00+05:30")]

    assert row["futures_close"] == 25010
    assert row["futures_vwap"] == 25000
