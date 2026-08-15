from datetime import date
from types import SimpleNamespace

from red_bar_lab.services.historical_dri_10day_validation import (
    run_latest_ready_dri_window,
)


def _result(trading_date, points=10.0):
    row = SimpleNamespace(
        execution="WOULD_TAKE",
        outcome_points=points,
        direction="BULLISH",
        reset_market_action_tier=None,
        reset_seen=False,
        reexpansion_detected=False,
        option_entry_price=100.0,
        trailing_exit_price=110.0,
        adaptive_trailing_exit_price=111.0,
    )
    return SimpleNamespace(
        trading_date=trading_date,
        rows=(row,),
        active_signals=1,
        approved=1,
        waiting=0,
        blocked=0,
        winners=1 if points > 0 else 0,
        losers=1 if points < 0 else 0,
        correct_skips=0,
        decision_accuracy_pct=100.0 if points > 0 else 0.0,
        net_points=points,
    )


def test_window_skips_unready_and_failed_dates_until_target_is_met():
    dates = [date(2026, 8, day) for day in range(3, 15)]
    not_ready = {date(2026, 8, 13), date(2026, 8, 10)}
    replay_failure = date(2026, 8, 12)

    def validate_day(trading_date):
        return SimpleNamespace(
            replay_ready=trading_date not in not_ready,
            reason="missing option coverage",
        )

    def run_day(trading_date):
        if trading_date == replay_failure:
            raise ValueError("broken replay artifact")
        return _result(trading_date)

    window = run_latest_ready_dri_window(
        dates,
        end_date=date(2026, 8, 14),
        requested_days=3,
        validate_day=validate_day,
        run_day=run_day,
    )

    assert window.complete is True
    assert window.selected_dates == (
        date(2026, 8, 9),
        date(2026, 8, 11),
        date(2026, 8, 14),
    )
    assert [attempt.status for attempt in window.attempts] == [
        "REPLAYED",
        "NOT_READY",
        "REPLAY_FAILED",
        "REPLAYED",
        "NOT_READY",
        "REPLAYED",
    ]


def test_incomplete_window_can_never_promote():
    dates = [date(2026, 8, 13), date(2026, 8, 14)]

    window = run_latest_ready_dri_window(
        dates,
        end_date=date(2026, 8, 14),
        requested_days=3,
        validate_day=lambda _: SimpleNamespace(replay_ready=True, reason=""),
        run_day=lambda trading_date: _result(trading_date, 20.0),
    )

    assert window.completed_days == 2
    assert window.complete is False
    assert window.promotion_passed is False


def test_daily_rows_preserve_chronological_replay_summary():
    dates = [date(2026, 8, 13), date(2026, 8, 14)]
    points = {
        date(2026, 8, 13): -4.25,
        date(2026, 8, 14): 26.40,
    }

    window = run_latest_ready_dri_window(
        reversed(dates),
        end_date=date(2026, 8, 14),
        requested_days=2,
        validate_day=lambda _: SimpleNamespace(replay_ready=True, reason=""),
        run_day=lambda trading_date: _result(trading_date, points[trading_date]),
    )

    rows = window.daily_rows()
    assert [row["Trading Date"] for row in rows] == [
        "2026-08-13",
        "2026-08-14",
    ]
    assert [row["Net Option Points"] for row in rows] == [-4.25, 26.4]


def test_requested_days_must_be_positive():
    try:
        run_latest_ready_dri_window(
            [],
            end_date=date(2026, 8, 14),
            requested_days=0,
            validate_day=lambda _: None,
            run_day=lambda _: None,
        )
    except ValueError as exc:
        assert "greater than zero" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
