from market_lab.midpoint_stable_feature_state_machine_v3_2 import (
    derive_t3_rules,
    observe_t1,
    classify_t3,
)

def test_t1_is_observation_only_strong():
    row = {
        "price_features": {
            "momentum_5m_directional": 10.0,
            "progress_points": 4.0,
            "giveback_from_best_checkpoint_points": 0.0,
            "acceptance_pct": 100.0,
        },
        "oi": {"support_level": "STRONG"},
    }
    out = observe_t1(row)
    assert out["state"] == "OBSERVE_STRONG"

def test_t1_is_observation_only_weak():
    row = {
        "price_features": {
            "momentum_5m_directional": -5.0,
            "progress_points": -3.0,
            "giveback_from_best_checkpoint_points": 6.0,
            "acceptance_pct": 50.0,
        },
        "oi": {"support_level": "STRONG"},
    }
    out = observe_t1(row)
    assert out["state"] == "OBSERVE_WEAK"

def test_structural_failure_overrides_oi():
    row = {
        "price_features": {
            "acceptance_pct": 50.0,
            "momentum_5m_directional": 4.0,
            "progress_points": -5.0,
            "giveback_from_best_checkpoint_points": 8.0,
            "consecutive_closes": 0.0,
            "velocity": -2.0,
        }
    }
    scored = {"price_pass_ratio": 0.7, "oi_quality": "STRONG"}
    assert classify_t3(row, scored) == "CANCEL_BREAKOUT"

def test_confirm_requires_supportive_oi():
    row = {
        "price_features": {
            "acceptance_pct": 100.0,
            "momentum_5m_directional": 20.0,
            "progress_points": 8.0,
            "giveback_from_best_checkpoint_points": 0.0,
            "consecutive_closes": 4.0,
            "velocity": 2.0,
        }
    }
    scored = {"price_pass_ratio": 0.9, "oi_quality": "SECONDARY"}
    assert classify_t3(row, scored) == "CONFIRM_CONTINUATION"

def test_strong_price_weak_oi_waits():
    row = {
        "price_features": {
            "acceptance_pct": 100.0,
            "momentum_5m_directional": 20.0,
            "progress_points": 8.0,
            "giveback_from_best_checkpoint_points": 0.0,
            "consecutive_closes": 4.0,
            "velocity": 2.0,
        }
    }
    scored = {"price_pass_ratio": 0.9, "oi_quality": "NONE"}
    assert classify_t3(row, scored) == "WAIT_BASE"

def test_unstable_train_direction_is_not_activated():
    rows = []
    # Bullish TRAIN T+3 progress_change is not part of T3_FEATURES by design.
    # Build simple rows where velocity conflicts with its structural polarity:
    for value in (1.0, 2.0, 3.0):
        rows.append({
            "block": "TRAIN",
            "direction": "BULLISH",
            "checkpoint_minutes": 3,
            "outcome_label": "CONTINUATION",
            "price_features": {
                "acceptance_pct": 100,
                "momentum_5m_directional": 20,
                "progress_points": 5,
                "giveback_from_best_checkpoint_points": 0,
                "consecutive_closes": 4,
                "velocity": value,
            }
        })
    for value in (4.0, 5.0, 6.0):
        rows.append({
            "block": "TRAIN",
            "direction": "BULLISH",
            "checkpoint_minutes": 3,
            "outcome_label": "REVERSAL",
            "price_features": {
                "acceptance_pct": 50,
                "momentum_5m_directional": 0,
                "progress_points": -5,
                "giveback_from_best_checkpoint_points": 10,
                "consecutive_closes": 0,
                "velocity": value,
            }
        })
    # add BEARISH rows so derive_t3_rules can build both sides
    for outcome, velocity in (("CONTINUATION", 2.0), ("REVERSAL", -2.0)):
        rows.append({
            "block": "TRAIN",
            "direction": "BEARISH",
            "checkpoint_minutes": 3,
            "outcome_label": outcome,
            "price_features": {
                "acceptance_pct": 100 if outcome == "CONTINUATION" else 50,
                "momentum_5m_directional": 20 if outcome == "CONTINUATION" else 0,
                "progress_points": 5 if outcome == "CONTINUATION" else -5,
                "giveback_from_best_checkpoint_points": 0 if outcome == "CONTINUATION" else 10,
                "consecutive_closes": 4 if outcome == "CONTINUATION" else 0,
                "velocity": velocity,
            }
        })
    rules = derive_t3_rules(rows)
    assert rules["BULLISH"]["features"]["velocity"]["status"] == "DIAGNOSTIC_ONLY"
