from datetime import date
from types import SimpleNamespace

from red_bar_lab.services.historical_dri_multiday_validation import (
    validate_historical_dri_dates,
)


def test_batch_aggregates_successful_days_and_captures_failure():
    def run_day(trading_date):
        if trading_date.day == 13:
            raise ValueError("option data unavailable")
        return (
            SimpleNamespace(
                active_signals=10,
                approved=4,
                waiting=5,
                blocked=1,
                winners=3,
                losers=1,
                false_positives=1,
                correct_skips=2,
                decision_accuracy_pct=70.0,
                net_points=12.5,
            ),
            5.0,
        )

    result = validate_historical_dri_dates(
        [date(2026, 8, 12), date(2026, 8, 13), date(2026, 8, 14)],
        run_day=run_day,
    )

    assert result.successful_days == 2
    assert result.failed_days == 1
    assert result.take == 8
    assert result.wins == 6
    assert result.net_points == 25.0


def test_batch_removes_duplicate_dates_preserving_order():
    calls = []

    def run_day(trading_date):
        calls.append(trading_date)
        return (
            SimpleNamespace(
                active_signals=0,
                approved=0,
                waiting=0,
                blocked=0,
                winners=0,
                losers=0,
                false_positives=0,
                correct_skips=0,
                decision_accuracy_pct=0.0,
                net_points=0.0,
            ),
            0.1,
        )

    validate_historical_dri_dates(
        [date(2026, 8, 12), date(2026, 8, 12), date(2026, 8, 14)],
        run_day=run_day,
    )
    assert calls == [date(2026, 8, 12), date(2026, 8, 14)]
