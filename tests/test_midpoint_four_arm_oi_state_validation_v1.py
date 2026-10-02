from market_lab.midpoint_four_arm_oi_state_validation_v1 import classify_oi_support


def test_strong_bearish():
    out = classify_oi_support(
        ce_state="SHORT_BUILDUP",
        pe_state="LONG_BUILDUP",
        direction="BEARISH",
    )
    assert out["combined_oi_state"] == "STRONG_BEARISH"
    assert out["support_level"] == "STRONG"
    assert out["directionally_supportive"] is True


def test_strong_bullish():
    out = classify_oi_support(
        ce_state="LONG_BUILDUP",
        pe_state="SHORT_BUILDUP",
        direction="BULLISH",
    )
    assert out["combined_oi_state"] == "STRONG_BULLISH"
    assert out["support_level"] == "STRONG"
    assert out["directionally_supportive"] is True


def test_secondary_bearish():
    out = classify_oi_support(
        ce_state="SHORT_BUILDUP",
        pe_state="SHORT_COVERING",
        direction="BEARISH",
    )
    assert out["support_level"] == "SECONDARY"
    assert out["directionally_supportive"] is True


def test_secondary_bullish():
    out = classify_oi_support(
        ce_state="SHORT_COVERING",
        pe_state="SHORT_BUILDUP",
        direction="BULLISH",
    )
    assert out["support_level"] == "SECONDARY"
    assert out["directionally_supportive"] is True


def test_mixed_not_supportive():
    out = classify_oi_support(
        ce_state="LONG_BUILDUP",
        pe_state="LONG_BUILDUP",
        direction="BEARISH",
    )
    assert out["combined_oi_state"] == "MIXED_OR_OPPOSING"
    assert out["support_level"] == "NONE"
    assert out["directionally_supportive"] is False


def test_missing_state_is_unavailable():
    out = classify_oi_support(
        ce_state=None,
        pe_state="LONG_BUILDUP",
        direction="BEARISH",
    )
    assert out["status"] == "UNAVAILABLE"
    assert out["directionally_supportive"] is None
