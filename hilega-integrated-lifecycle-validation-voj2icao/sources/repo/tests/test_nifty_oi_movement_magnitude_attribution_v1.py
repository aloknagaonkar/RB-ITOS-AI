from market_lab.nifty_oi_movement_magnitude_attribution_v1 import (
    analyze,
    build_checkpoint_dataset,
)


def row(ts, spot, imb5, imb10, imb15, ce5=0, pe5=0):
    return {
        "session_date": "2026-08-25",
        "timestamp": ts,
        "spot": spot,
        "moving_atm": 24200,
        "ce_delta_5m": ce5,
        "pe_delta_5m": pe5,
        "imbalance_5m": imb5,
        "pcr_change_5m": 0.1 if imb5 > 0 else -0.1,
        "ce_delta_10m": ce5,
        "pe_delta_10m": pe5,
        "imbalance_10m": imb10,
        "pcr_change_10m": 0.2 if imb10 > 0 else -0.2,
        "ce_delta_15m": ce5,
        "pe_delta_15m": pe5,
        "imbalance_15m": imb15,
        "pcr_change_15m": 0.3 if imb15 > 0 else -0.3,
    }


def test_builds_forward_checkpoint_excursions():
    rows = [
        row("2026-08-25T10:00:00+05:30", 100, 1, 2, 3),
        row("2026-08-25T10:05:00+05:30", 112, 2, 3, 4),
        row("2026-08-25T10:10:00+05:30", 125, 3, 4, 5),
        row("2026-08-25T10:15:00+05:30", 118, 4, 5, 6),
    ]
    out = build_checkpoint_dataset(rows)
    first = out[0]

    assert first["bull_excursion_5m"] == 12
    assert first["bull_excursion_10m"] == 25
    assert first["bull_excursion_15m"] == 25
    assert first["bear_excursion_15m"] == 0
    assert first["net_change_15m"] == 18


def test_bearish_directional_imbalance_sign_is_reversed():
    rows = [
        row("2026-08-25T10:00:00+05:30", 100, -10, -20, -30),
        row("2026-08-25T10:05:00+05:30", 88, -9, -19, -29),
        row("2026-08-25T10:10:00+05:30", 75, -8, -18, -28),
        row("2026-08-25T10:15:00+05:30", 70, -7, -17, -27),
    ]
    checkpoints = build_checkpoint_dataset(rows)
    result = analyze(checkpoints)

    target = next(
        r for r in result
        if r["direction"] == "BEARISH"
        and r["forward_horizon_minutes"] == 5
        and r["nifty_move_threshold_points"] == 10
        and r["oi_lookback_minutes"] == 5
    )
    assert target["movement_sample_count"] >= 1
    assert target["robust_min_p10_directional_imbalance"] > 0
    assert target["directional_imbalance_aligned_rate_pct"] == 100.0


def test_robust_min_is_p10_not_literal_min():
    rows = []
    # Ten independent two-checkpoint mini sessions to make a simple distribution.
    # Build analyze() directly from synthetic checkpoint records.
    checkpoints = []
    for i in range(10):
        checkpoints.append({
            "session_date": f"2026-08-{i+1:02d}",
            "timestamp": f"2026-08-{i+1:02d}T10:00:00+05:30",
            "spot": 100.0,
            "imbalance_5m": float(i + 1),
            "imbalance_10m": float(i + 1),
            "imbalance_15m": float(i + 1),
            "ce_delta_5m": 0.0,
            "pe_delta_5m": float(i + 1),
            "ce_delta_10m": 0.0,
            "pe_delta_10m": float(i + 1),
            "ce_delta_15m": 0.0,
            "pe_delta_15m": float(i + 1),
            "pcr_change_5m": 0.1,
            "pcr_change_10m": 0.1,
            "pcr_change_15m": 0.1,
            "bull_excursion_5m": 20.0,
            "bear_excursion_5m": 0.0,
            "bull_excursion_10m": 20.0,
            "bear_excursion_10m": 0.0,
            "bull_excursion_15m": 20.0,
            "bear_excursion_15m": 0.0,
        })

    result = analyze(checkpoints)
    target = next(
        r for r in result
        if r["direction"] == "BULLISH"
        and r["forward_horizon_minutes"] == 5
        and r["nifty_move_threshold_points"] == 10
        and r["oi_lookback_minutes"] == 5
    )

    assert target["observed_min_directional_imbalance"] == 1.0
    assert target["robust_min_p10_directional_imbalance"] > 1.0
