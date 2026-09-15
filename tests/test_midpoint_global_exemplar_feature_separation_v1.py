from market_lab.midpoint_global_exemplar_feature_separation_v1 import (
    compare_groups,
    flatten,
    is_accepted,
    is_loss,
    is_win,
)


def sample(bucket="GOOD_5M_3_TO_10", family="IMMEDIATE_CONTINUATION", direction="BULLISH"):
    return {
        "block": "TRAIN",
        "session_date": "2026-09-01",
        "setup_type": "GREEN_BREAK" if direction == "BULLISH" else "RED_BREAK",
        "direction": direction,
        "decision_family": family,
        "quality_bucket": bucket,
        "price_features": {
            "acceptance_pct": 100.0,
            "momentum_5m_directional": 20.0,
            "progress_points": 5.0,
            "giveback_from_best_checkpoint_points": 1.0,
            "consecutive_closes": 4.0,
            "velocity": 2.0,
        },
        "price_pass_count": 6,
        "oi_quality": "STRONG",
        "oi": {"ce_state": "LONG_BUILDUP", "pe_state": "SHORT_BUILDUP"},
        "futures": {"distance_points": 10.0, "distance_pct": 0.04, "aligned": True},
        "option_economics": {"net_5m_pct": 5.0},
    }


def test_flatten():
    r = flatten(sample())
    assert r["acceptance_pct"] == 100.0
    assert r["net_5m_pct"] == 5.0


def test_win_loss_groups():
    assert is_win(flatten(sample("EXCELLENT_5M_GE_10"))) is True
    assert is_loss(flatten(sample("LARGE_LOSS_5M_LE_MINUS5"))) is True


def test_accepted_family():
    assert is_accepted(flatten(sample(family="BASE_THEN_GO"))) is True
    assert is_accepted(flatten(sample(family="CANCEL"))) is False


def test_compare_groups_delta():
    a = [flatten(sample())]
    bsrc = sample()
    bsrc["price_features"]["momentum_5m_directional"] = 10.0
    b = [flatten(bsrc)]
    c = compare_groups(a, b)
    assert c["numeric"]["momentum_5m_directional"]["mean_delta_a_minus_b"] == 10.0
