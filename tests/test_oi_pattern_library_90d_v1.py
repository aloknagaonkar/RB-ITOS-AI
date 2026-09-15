from market_lab.oi_pattern_library_90d_v1 import pct,state,directional_label

def test_pct():
    assert pct(110,100)==10.0

def test_states():
    assert state(2,3)=="LONG_BUILDUP"
    assert state(-2,3)=="SHORT_BUILDUP"
    assert state(2,-3)=="SHORT_COVERING"
    assert state(-2,-3)=="LONG_UNWINDING"

def test_quantity_family():
    r={"ce_state":"UNAVAILABLE","pe_state":"UNAVAILABLE","m_ce_delta":-2_000_000,"m_pe_delta":3_000_000}
    assert directional_label(r)=="BULLISH_QUANTITY_DIVERGENCE"
