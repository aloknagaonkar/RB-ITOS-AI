from market_lab.midpoint_four_arm_decision_research_v1 import (
    ARM_CONFIGS,
    STANDARD_FEATURES,
    feature_pass,
    extract_features,
)


def test_all_four_arms_exist():
    assert set(ARM_CONFIGS) == {
        "RED_BEARISH_CONTINUATION",
        "RED_BULLISH_RECLAIM",
        "GREEN_BULLISH_CONTINUATION",
        "GREEN_BEARISH_RECLAIM",
    }


def test_option_sides_are_symmetric():
    assert ARM_CONFIGS["RED_BEARISH_CONTINUATION"]["option_side"] == "PE"
    assert ARM_CONFIGS["RED_BULLISH_RECLAIM"]["option_side"] == "CE"
    assert ARM_CONFIGS["GREEN_BULLISH_CONTINUATION"]["option_side"] == "CE"
    assert ARM_CONFIGS["GREEN_BEARISH_RECLAIM"]["option_side"] == "PE"


def test_standard_feature_count_is_nine():
    assert len(STANDARD_FEATURES) == 9


def test_feature_pass_higher():
    spec = {"favorable_direction": "HIGHER_IS_FAVORABLE", "threshold_train_only": 5}
    assert feature_pass(6, spec)
    assert not feature_pass(4, spec)


def test_feature_pass_lower():
    spec = {"favorable_direction": "LOWER_IS_FAVORABLE", "threshold_train_only": -5}
    assert feature_pass(-6, spec)
    assert not feature_pass(-4, spec)


def test_side_aware_option_mapping_for_bearish_arm():
    snap = {
        "directional_momentum_5m": 1,
        "directional_distance_beyond_boundary_points": 2,
        "directional_acceptance_pct": 100,
        "consecutive_closes_beyond_boundary": 4,
        "new_directional_close_extreme_count": 2,
        "directional_progress_points": 5,
        "directional_velocity_points_per_minute": 1,
        "pe_5m_premium_change_pct": 12,
        "ce_5m_oi_change_pct": 18,
    }
    values = extract_features(
        snap,
        ARM_CONFIGS["RED_BEARISH_CONTINUATION"],
    )
    assert values["favored_option_premium_change_5m_pct"] == 12
    assert values["opposite_option_oi_change_5m_pct"] == 18


def test_side_aware_option_mapping_for_bullish_arm():
    snap = {
        "directional_momentum_5m": 1,
        "directional_distance_beyond_boundary_points": 2,
        "directional_acceptance_pct": 100,
        "consecutive_closes_beyond_boundary": 4,
        "new_directional_close_extreme_count": 2,
        "directional_progress_points": 5,
        "directional_velocity_points_per_minute": 1,
        "ce_5m_premium_change_pct": 15,
        "pe_5m_oi_change_pct": 9,
    }
    values = extract_features(
        snap,
        ARM_CONFIGS["GREEN_BULLISH_CONTINUATION"],
    )
    assert values["favored_option_premium_change_5m_pct"] == 15
    assert values["opposite_option_oi_change_5m_pct"] == 9
