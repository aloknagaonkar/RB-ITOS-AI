from market_lab.midpoint_confirm_wait_cancel_state_machine_v3 import (
    pass_feature,
    classify_t1,
    classify_t3,
)

def test_pass_feature_higher():
    spec = {"threshold": 10.0, "higher_is_better": True}
    assert pass_feature(11.0, spec) is True
    assert pass_feature(9.0, spec) is False

def test_pass_feature_lower():
    spec = {"threshold": 5.0, "higher_is_better": False}
    assert pass_feature(4.0, spec) is True
    assert pass_feature(6.0, spec) is False

def test_bullish_t1_can_be_early_strong():
    scored = {"price_pass_ratio": 0.86, "oi_quality": "SECONDARY"}
    assert classify_t1("BULLISH", scored) == "EARLY_STRONG"

def test_bearish_t1_is_more_conservative():
    scored = {"price_pass_ratio": 0.86, "oi_quality": "STRONG"}
    assert classify_t1("BEARISH", scored) == "WAIT"

def test_t3_price_failure_overrides_strong_oi():
    scored = {"price_pass_ratio": 0.6, "oi_quality": "STRONG"}
    row = {
        "price_features": {
            "acceptance_pct": 50.0,
            "progress_points": -5.0,
            "giveback_from_best_checkpoint_points": 10.0,
            "acceptance_change_from_previous_checkpoint": -25.0,
        }
    }
    assert classify_t3("BEARISH", scored, row) == "CANCEL_BREAKOUT"

def test_t3_strong_price_plus_supportive_oi_confirms():
    scored = {"price_pass_ratio": 0.86, "oi_quality": "SECONDARY"}
    row = {
        "price_features": {
            "acceptance_pct": 100.0,
            "progress_points": 5.0,
            "giveback_from_best_checkpoint_points": 0.0,
            "acceptance_change_from_previous_checkpoint": 0.0,
        }
    }
    assert classify_t3("BULLISH", scored, row) == "CONFIRM_CONTINUATION"

def test_t3_strong_price_weak_oi_waits():
    scored = {"price_pass_ratio": 0.86, "oi_quality": "NONE"}
    row = {
        "price_features": {
            "acceptance_pct": 100.0,
            "progress_points": 5.0,
            "giveback_from_best_checkpoint_points": 0.0,
            "acceptance_change_from_previous_checkpoint": 0.0,
        }
    }
    assert classify_t3("BULLISH", scored, row) == "WAIT_BASE"
