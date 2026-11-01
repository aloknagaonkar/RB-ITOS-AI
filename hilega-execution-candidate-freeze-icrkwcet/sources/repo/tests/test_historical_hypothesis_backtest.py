import csv
from datetime import datetime, timedelta, timezone

from market_lab.historical_hypothesis_backtest import backtest_hypotheses_csv


def _write_csv(path, minutes=70):
    fields = [
        "session_date", "expiry", "timestamp", "spot",
        "moving_pcr_change_15m", "fixed_moving_pcr_spread",
        "moving_call_oi_change_pct", "moving_put_oi_change_pct",
    ]
    start = datetime(2026, 9, 1, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    rows = []
    for i in range(minutes):
        # First ~20% has falling PCR / low spread and a steadily falling spot afterwards.
        strong = i < 14
        rows.append({
            "session_date": "2026-09-01",
            "expiry": "2026-09-01",
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
            "spot": 24000 - (i if i >= 15 else 0),
            "moving_pcr_change_15m": -0.20 if strong else 0.02 + i * 0.0001,
            "fixed_moving_pcr_spread": -0.30 if strong else 0.03 + i * 0.0001,
            "moving_call_oi_change_pct": 1.0,
            "moving_put_oi_change_pct": 10.0 if strong else 1.5,
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_backtest_builds_four_shortlisted_hypotheses(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = backtest_hypotheses_csv(path, cooldown_minutes=15)
    assert report.status == "AVAILABLE"
    assert report.session_count == 1
    assert len(report.hypotheses) == 4
    assert report.primary_hold_minutes == 15
    assert "moving_pcr_change_15m_q20" in report.global_thresholds


def test_cooldown_collapses_persistent_signal(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = backtest_hypotheses_csv(path, cooldown_minutes=15)
    h4 = next(item for item in report.hypotheses if item.hypothesis_id == "H4_MOVING_PCR_STRONG_FALL")
    assert h4.event_count == 1
    assert h4.skipped_due_to_cooldown > 0


def test_entry_is_next_minute_and_bearish_points_are_positive_on_fall(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = backtest_hypotheses_csv(path, cooldown_minutes=15)
    h4 = next(item for item in report.hypotheses if item.hypothesis_id == "H4_MOVING_PCR_STRONG_FALL")
    event = h4.events[0]
    signal = datetime.fromisoformat(event.signal_time)
    entry = datetime.fromisoformat(event.entry_time)
    assert entry - signal == timedelta(minutes=1)
    outcome = event.outcomes["15m"]
    assert outcome["directional_points"] > 0
    assert outcome["mfe_points"] >= 0
    assert outcome["mae_points"] >= 0


def test_expiry_and_time_segments_are_reported(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = backtest_hypotheses_csv(path)
    h4 = next(item for item in report.hypotheses if item.hypothesis_id == "H4_MOVING_PCR_STRONG_FALL")
    assert any(item.label == "EXPIRY_DAY" for item in h4.expiry_regime)
    assert any(item.label.startswith("OPEN_") for item in h4.time_of_day)
