
from market_lab.oi_price_regime_transition_audit_v1_1 import classify_futures_oi

def test_futures_oi_status():
    assert classify_futures_oi(1, 1) == ("LONG_BUILDUP", "BULLISH")
    assert classify_futures_oi(-1, 1) == ("SHORT_BUILDUP", "BEARISH")
    assert classify_futures_oi(1, -1) == ("SHORT_COVERING", "BULLISH")
    assert classify_futures_oi(-1, -1) == ("LONG_UNWINDING", "BEARISH")
