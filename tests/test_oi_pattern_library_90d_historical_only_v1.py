from market_lab.oi_pattern_library_90d_historical_only_v1 import pct, state, pattern_family

def test_pct():
    assert pct(110,100)==10.0

def test_states():
    assert state(2,3)=="LONG_BUILDUP"
    assert state(-2,3)=="SHORT_BUILDUP"
    assert state(2,-3)=="SHORT_COVERING"
    assert state(-2,-3)=="LONG_UNWINDING"

def test_family():
    r={"ce_state":"UNAVAILABLE","pe_state":"UNAVAILABLE","m_ce_delta":-10,"m_pe_delta":20}
    assert pattern_family(r)=="BULLISH_QUANTITY_DIVERGENCE"
