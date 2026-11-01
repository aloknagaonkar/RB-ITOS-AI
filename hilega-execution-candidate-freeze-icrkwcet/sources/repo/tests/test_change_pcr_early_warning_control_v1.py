from market_lab.change_pcr_early_warning_control_v1 import (
    normalized_oi_dominance,
    build_candle_table,
    candidate_warning,
)


def test_normalized_oi_dominance_bounded_examples():
    assert normalized_oi_dominance(10, 20) == 1/3
    assert normalized_oi_dominance(20, 10) == -1/3
    assert normalized_oi_dominance(-10, 20) == 1.0
    assert normalized_oi_dominance(10, -20) == -1.0
    assert normalized_oi_dominance(0, 0) == 0.0


def test_warning_from_opposite_mechanics():
    candle = {
        "all3_state": "BULLISH_ALL_3",
        "hrows": {
            "5m": {
                "change_pcr_mechanics": "BOTH_BUILD_CE_DOMINANT",
                "delta_pattern": "CE+/PE+",
                "oi_imbalance": -5,
                "regular_pcr_change": -0.1,
            }
        },
        "mechanics_direction_5m": "BEARISH",
        "normalized_dominance_5m": -0.3,
        "normalized_dominance_change_5m": -0.2,
        "change_pcr_5m": 0.5,
        "change_pcr_change_5m": -0.4,
    }
    warning = candidate_warning(candle)
    assert warning is not None
    assert warning["target_direction"] == "BEARISH"
    assert warning["warning_type"] == "MECHANICS_AND_DOMINANCE"
