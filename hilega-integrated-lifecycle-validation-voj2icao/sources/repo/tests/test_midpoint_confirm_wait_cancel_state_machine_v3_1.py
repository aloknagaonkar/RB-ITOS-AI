from market_lab.midpoint_confirm_wait_cancel_state_machine_v3_1 import (
    derive_feature_rule,
    pass_feature,
    classify_t1,
    classify_t3,
)

def test_higher_polarity_learned():
    spec = derive_feature_rule("progress_points", [5, 6, 7], [-2, -1, 0])
    assert spec["status"] == "ACTIVE"
    assert spec["polarity"] == "HIGHER_IS_BETTER"

def test_lower_polarity_learned():
    spec = derive_feature_rule("giveback_from_best_checkpoint_points", [0, 1, 1], [5, 6, 7])
    assert spec["status"] == "ACTIVE"
    assert spec["polarity"] == "LOWER_IS_BETTER"

def test_equal_feature_becomes_non_discriminative():
    spec = derive_feature_rule("acceptance_pct", [100, 100, 100], [100, 100, 100])
    assert spec["status"] == "NON_DISCRIMINATIVE"
    assert spec["threshold"] is None

def test_non_discriminative_feature_does_not_vote():
    spec = {
        "status": "NON_DISCRIMINATIVE",
        "polarity": None,
        "threshold": None,
    }
    assert pass_feature(100.0, spec) is None

def test_t1_never_confirms_entry():
    assert classify_t1({"price_pass_ratio": 1.0}) == "DEVELOPING_STRONG"

def test_t3_structural_failure_overrides_oi():
    scored = {"price_pass_ratio": 0.7, "oi_quality": "STRONG"}
    row = {"price_features": {
        "acceptance_pct": 50.0,
        "progress_points": -5.0,
        "progress_change_from_previous_checkpoint": -4.0,
        "giveback_from_best_checkpoint_points": 8.0,
        "acceptance_change_from_previous_checkpoint": -25.0,
    }}
    assert classify_t3(scored, row) == "CANCEL_BREAKOUT"

def test_t3_strong_price_supportive_oi_confirms():
    scored = {"price_pass_ratio": 0.8, "oi_quality": "SECONDARY"}
    row = {"price_features": {
        "acceptance_pct": 100.0,
        "progress_points": 5.0,
        "progress_change_from_previous_checkpoint": 3.0,
        "giveback_from_best_checkpoint_points": 0.0,
        "acceptance_change_from_previous_checkpoint": 0.0,
    }}
    assert classify_t3(scored, row) == "CONFIRM_CONTINUATION"
