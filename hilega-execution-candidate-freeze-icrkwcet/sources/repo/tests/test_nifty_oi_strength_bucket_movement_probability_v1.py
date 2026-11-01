from market_lab.nifty_oi_strength_bucket_movement_probability_v1 import analyze


def test_non_overlapping_buckets():
    checkpoints = [
        {
            "imbalance_5m": 500_000.0,
            "imbalance_10m": 500_000.0,
            "imbalance_15m": 500_000.0,
            "bull_excursion_5m": 12.0,
            "bear_excursion_5m": 0.0,
            "bull_excursion_10m": 20.0,
            "bear_excursion_10m": 0.0,
        },
        {
            "imbalance_5m": 1_500_000.0,
            "imbalance_10m": 1_500_000.0,
            "imbalance_15m": 1_500_000.0,
            "bull_excursion_5m": 15.0,
            "bear_excursion_5m": 0.0,
            "bull_excursion_10m": 25.0,
            "bear_excursion_10m": 0.0,
        },
    ]

    rows = analyze(checkpoints)

    b0 = next(
        r for r in rows
        if r["direction"] == "BULLISH"
        and r["oi_lookback_minutes"] == 5
        and r["forward_horizon_minutes"] == 5
        and r["oi_bucket"] == "0-1M"
        and r["nifty_move_threshold_points"] == 10
    )
    b1 = next(
        r for r in rows
        if r["direction"] == "BULLISH"
        and r["oi_lookback_minutes"] == 5
        and r["forward_horizon_minutes"] == 5
        and r["oi_bucket"] == "1-2M"
        and r["nifty_move_threshold_points"] == 10
    )

    assert b0["eligible_checkpoint_count"] == 1
    assert b1["eligible_checkpoint_count"] == 1
    assert b0["movement_hit_rate_pct"] == 100.0
    assert b1["movement_hit_rate_pct"] == 100.0


def test_bearish_directional_bucket_sign_normalization():
    checkpoints = [
        {
            "imbalance_5m": -4_000_000.0,
            "imbalance_10m": -4_000_000.0,
            "imbalance_15m": -4_000_000.0,
            "bull_excursion_5m": 0.0,
            "bear_excursion_5m": 35.0,
            "bull_excursion_10m": 0.0,
            "bear_excursion_10m": 45.0,
        }
    ]

    rows = analyze(checkpoints)

    target = next(
        r for r in rows
        if r["direction"] == "BEARISH"
        and r["oi_lookback_minutes"] == 5
        and r["forward_horizon_minutes"] == 10
        and r["oi_bucket"] == "3-5M"
        and r["nifty_move_threshold_points"] == 40
    )

    assert target["eligible_checkpoint_count"] == 1
    assert target["movement_hit_count"] == 1
    assert target["movement_hit_rate_pct"] == 100.0


def test_opposite_direction_oi_is_excluded():
    checkpoints = [
        {
            "imbalance_5m": -2_000_000.0,
            "imbalance_10m": -2_000_000.0,
            "imbalance_15m": -2_000_000.0,
            "bull_excursion_5m": 30.0,
            "bear_excursion_5m": 0.0,
            "bull_excursion_10m": 30.0,
            "bear_excursion_10m": 0.0,
        }
    ]

    rows = analyze(checkpoints)

    target = next(
        r for r in rows
        if r["direction"] == "BULLISH"
        and r["oi_lookback_minutes"] == 5
        and r["forward_horizon_minutes"] == 5
        and r["oi_bucket"] == "1-2M"
        and r["nifty_move_threshold_points"] == 10
    )

    assert target["eligible_checkpoint_count"] == 0
    assert target["movement_hit_rate_pct"] is None
