from market_lab.midpoint_break_strength_failure_v2 import classify_oi_pair, feature_pass

def test_strong_bearish():
    x=classify_oi_pair("BEARISH","SHORT_BUILDUP","LONG_BUILDUP")
    assert x["support_level"]=="STRONG" and x["combined_state"]=="STRONG_BEARISH"

def test_bearish_reversal_warning():
    x=classify_oi_pair("BEARISH","SHORT_COVERING","LONG_UNWINDING")
    assert x["reversal_warning"] is True

def test_strong_bullish():
    x=classify_oi_pair("BULLISH","LONG_BUILDUP","SHORT_BUILDUP")
    assert x["support_level"]=="STRONG" and x["combined_state"]=="STRONG_BULLISH"

def test_bullish_reversal_warning():
    x=classify_oi_pair("BULLISH","LONG_UNWINDING","SHORT_COVERING")
    assert x["reversal_warning"] is True

def test_secondary_states_preserved():
    assert classify_oi_pair("BEARISH","LONG_UNWINDING","LONG_BUILDUP")["support_level"]=="SECONDARY"
    assert classify_oi_pair("BULLISH","SHORT_COVERING","SHORT_BUILDUP")["support_level"]=="SECONDARY"

def test_feature_pass_higher():
    s={"threshold":10.0,"preferred_direction":"HIGHER"}
    assert feature_pass(11,s) is True and feature_pass(9,s) is False

def test_feature_pass_lower():
    s={"threshold":2.0,"preferred_direction":"LOWER"}
    assert feature_pass(1,s) is True and feature_pass(3,s) is False
