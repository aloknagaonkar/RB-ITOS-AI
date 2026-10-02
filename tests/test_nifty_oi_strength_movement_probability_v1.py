import csv
from pathlib import Path

from market_lab.nifty_oi_strength_movement_probability_v1 import (
    analyze,
    load_checkpoints,
)


def test_bullish_probability_rises_from_exact_counts():
    checkpoints = [
        {
            "imbalance_5m": 1_500_000.0,
            "imbalance_10m": 2_000_000.0,
            "imbalance_15m": 3_000_000.0,
            "bull_excursion_5m": 12.0,
            "bear_excursion_5m": 0.0,
            "bull_excursion_10m": 22.0,
            "bear_excursion_10m": 0.0,
        },
        {
            "imbalance_5m": 2_500_000.0,
            "imbalance_10m": 3_000_000.0,
            "imbalance_15m": 4_000_000.0,
            "bull_excursion_5m": 5.0,
            "bear_excursion_5m": 0.0,
            "bull_excursion_10m": 15.0,
            "bear_excursion_10m": 0.0,
        },
    ]

    rows = analyze(checkpoints)
    target = next(
        r for r in rows
        if r["direction"] == "BULLISH"
        and r["oi_lookback_minutes"] == 5
        and r["forward_horizon_minutes"] == 5
        and r["oi_directional_imbalance_floor"] == 1_000_000
        and r["nifty_move_threshold_points"] == 10
    )

    assert target["eligible_checkpoint_count"] == 2
    assert target["movement_hit_count"] == 1
    assert target["movement_hit_rate_pct"] == 50.0


def test_bearish_uses_negative_raw_imbalance_as_positive_strength():
    checkpoints = [
        {
            "imbalance_5m": -5_000_000.0,
            "imbalance_10m": -5_000_000.0,
            "imbalance_15m": -5_000_000.0,
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
        and r["oi_directional_imbalance_floor"] == 5_000_000
        and r["nifty_move_threshold_points"] == 40
    )

    assert target["eligible_checkpoint_count"] == 1
    assert target["movement_hit_count"] == 1
    assert target["movement_hit_rate_pct"] == 100.0


def test_loader_requires_only_5m_and_10m_forward_columns(tmp_path: Path):
    p = tmp_path / "checkpoints.csv"
    fields = [
        "session_date","timestamp","spot",
        "imbalance_5m","imbalance_10m","imbalance_15m",
        "bull_excursion_5m","bear_excursion_5m",
        "bull_excursion_10m","bear_excursion_10m",
    ]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow({
            "session_date": "2026-08-25",
            "timestamp": "2026-08-25T10:00:00+05:30",
            "spot": "24200",
            "imbalance_5m": "1000000",
            "imbalance_10m": "2000000",
            "imbalance_15m": "3000000",
            "bull_excursion_5m": "12",
            "bear_excursion_5m": "0",
            "bull_excursion_10m": "20",
            "bear_excursion_10m": "0",
        })

    rows = load_checkpoints(p)
    assert len(rows) == 1
    assert rows[0]["imbalance_15m"] == 3_000_000.0
    assert rows[0]["bull_excursion_10m"] == 20.0
