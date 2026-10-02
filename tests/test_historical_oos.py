from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone

from market_lab.historical_oos import (
    freeze_h3_spec,
    validate_h3_oos,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _rows(session: str, expiry: str, spreads: list[float], spots: list[float]):
    start = datetime.fromisoformat(session + "T09:20:00+05:30")
    result = []
    for i, (spread, spot) in enumerate(zip(spreads, spots)):
        result.append({
            "session_date": session,
            "expiry": expiry,
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
            "dt": start + timedelta(minutes=i),
            "spot": float(spot),
            "fixed_moving_pcr_spread": float(spread),
            "moving_pcr_change_15m": -0.1,
            "moving_call_oi_change_pct": 1.0,
            "moving_put_oi_change_pct": 2.0,
            "moving_oi_imbalance_pct": 1.0,
        })
    return result


def test_freeze_uses_training_q20_only():
    rows = _rows("2026-01-01", "2026-01-08", [0,1,2,3,4,5], [100]*6)
    spec = freeze_h3_spec(rows, "train.csv", cooldown_minutes=15)
    assert spec.frozen_threshold == 1.0
    assert spec.training_row_count == 6
    assert spec.training_session_count == 1


def test_oos_uses_frozen_threshold_and_excludes_expiry_day():
    # Threshold 0.2 from train. OOS contains much larger values; validator must not recalc.
    train = _rows("2026-01-01", "2026-01-08", [0,0.1,0.2,1,2,3], [100]*6)
    spec = freeze_h3_spec(train, "train.csv", cooldown_minutes=15)

    non_expiry_spreads = [0.0] + [9.0] * 40
    non_expiry_spots = [100.0] + [99.0 - i for i in range(40)]
    expiry_spreads = [0.0] + [9.0] * 40
    expiry_spots = [100.0] + [101.0 + i for i in range(40)]
    rows = _rows("2026-02-02", "2026-02-05", non_expiry_spreads, non_expiry_spots)
    rows += _rows("2026-02-05", "2026-02-05", expiry_spreads, expiry_spots)

    report = validate_h3_oos(rows, "oos.csv", spec)
    assert report.frozen_threshold == spec.frozen_threshold
    assert report.excluded_expiry_row_count == 41
    assert report.event_count == 1
    assert report.event_session_count == 1
    assert report.holds["15m"].mean_directional_points > 0


def test_acceptance_gate_passes_for_broad_positive_oos():
    train = _rows("2026-01-01", "2026-01-08", [-1,-.8,-.6,0,1,2], [100]*6)
    spec = freeze_h3_spec(train, "train.csv", cooldown_minutes=15)
    rows = []
    for day in range(1, 9):
        session = f"2026-02-{day:02d}"
        # Signal at 09:20, next-minute entry 100; then lower spots => bearish directional gain.
        spreads = [-2.0] + [5.0] * 40
        spots = [101.0, 100.0] + [99.0 - 0.2*i for i in range(39)]
        rows += _rows(session, "2026-02-20", spreads, spots)
    report = validate_h3_oos(rows, "oos.csv", spec)
    assert report.event_session_count == 8
    assert report.holds["15m"].win_rate_pct == 100.0
    assert report.acceptance_status == "PASS"
    assert all(check.passed for check in report.acceptance_checks)


def test_acceptance_gate_fails_when_oos_edge_reverses():
    train = _rows("2026-01-01", "2026-01-08", [-1,-.8,-.6,0,1,2], [100]*6)
    spec = freeze_h3_spec(train, "train.csv", cooldown_minutes=15)
    rows = []
    for day in range(1, 9):
        session = f"2026-03-{day:02d}"
        spreads = [-2.0] + [5.0] * 40
        spots = [99.0, 100.0] + [101.0 + 0.2*i for i in range(39)]
        rows += _rows(session, "2026-03-20", spreads, spots)
    report = validate_h3_oos(rows, "oos.csv", spec)
    assert report.acceptance_status == "FAIL"
    assert report.holds["15m"].mean_directional_points < 0
