from __future__ import annotations

from datetime import datetime, timedelta

from market_lab.historical_oos import freeze_h3_spec
from market_lab.historical_oos_combined import validate_h3_combined_oos


def _rows(session: str, expiry: str, spread: float, bearish: bool = True):
    start = datetime.fromisoformat(session + "T09:20:00+05:30")
    rows = []
    # One signal at 09:20, then non-signal rows. Next minute is entry.
    for i in range(41):
        if i == 0:
            s = spread
        else:
            s = 5.0
        if bearish:
            spot = 101.0 if i == 0 else 100.0 - 0.3 * (i - 1)
        else:
            spot = 99.0 if i == 0 else 100.0 + 0.3 * (i - 1)
        rows.append({
            "session_date": session,
            "expiry": expiry,
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
            "dt": start + timedelta(minutes=i),
            "spot": spot,
            "fixed_moving_pcr_spread": s,
            "moving_pcr_change_15m": -0.1,
            "moving_call_oi_change_pct": 1.0,
            "moving_put_oi_change_pct": 2.0,
            "moving_oi_imbalance_pct": 1.0,
        })
    return rows


def _training():
    start = datetime.fromisoformat("2026-01-01T09:20:00+05:30")
    vals = [-1.0, -0.8, -0.6, 0.0, 1.0, 2.0]
    return [{
        "session_date": "2026-01-01",
        "expiry": "2026-01-08",
        "timestamp": (start + timedelta(minutes=i)).isoformat(),
        "dt": start + timedelta(minutes=i),
        "spot": 100.0,
        "fixed_moving_pcr_spread": v,
    } for i, v in enumerate(vals)]


def test_combined_oos_reuses_frozen_threshold_and_passes_broad_positive_blocks():
    spec = freeze_h3_spec(_training(), "train.csv", cooldown_minutes=15)
    a = []
    b = []
    for day in range(1, 7):
        a += _rows(f"2026-02-{day:02d}", "2026-02-20", -2.0, bearish=True)
    for day in range(1, 7):
        b += _rows(f"2026-03-{day:02d}", "2026-03-20", -2.0, bearish=True)

    report = validate_h3_combined_oos(a, b, "a.csv", "b.csv", spec)
    assert report.frozen_threshold == spec.frozen_threshold
    assert report.block_a.event_session_count == 6
    assert report.block_b.event_session_count == 6
    assert report.combined.event_session_count == 12
    assert report.robustness_status == "PASS"
    assert all(check.passed for check in report.robustness_checks)


def test_combined_oos_fails_when_second_block_reverses():
    spec = freeze_h3_spec(_training(), "train.csv", cooldown_minutes=15)
    a = []
    b = []
    for day in range(1, 7):
        a += _rows(f"2026-04-{day:02d}", "2026-04-20", -2.0, bearish=True)
    for day in range(1, 7):
        b += _rows(f"2026-05-{day:02d}", "2026-05-20", -2.0, bearish=False)

    report = validate_h3_combined_oos(a, b, "a.csv", "b.csv", spec)
    assert report.block_b.holds["15m"].mean_directional_points < 0
    assert report.robustness_status == "FAIL"
    assert not next(c for c in report.robustness_checks if c.name == "both_blocks_positive_mean_15m").passed
