from datetime import date
from types import SimpleNamespace

from red_bar_lab.services.historical_dri_risk_consistency import (
    analyze_historical_dri_risk_consistency,
)


def _row(
    points,
    *,
    direction="BULLISH",
    tier=None,
    reset_seen=False,
    entry=100.0,
    fixed_exit=None,
    adaptive_exit=None,
):
    return SimpleNamespace(
        execution="WOULD_TAKE",
        outcome_points=points,
        direction=direction,
        reset_market_action_tier=tier,
        reset_seen=reset_seen,
        reexpansion_detected=reset_seen,
        option_entry_price=entry,
        trailing_exit_price=fixed_exit,
        adaptive_trailing_exit_price=adaptive_exit,
    )


def _result(day, *rows):
    return SimpleNamespace(trading_date=day, rows=rows)


def test_risk_report_calculates_window_metrics_and_slices():
    report = analyze_historical_dri_risk_consistency(
        [
            _result(
                date(2026, 8, 12),
                _row(
                    10.0,
                    direction="BULLISH",
                    fixed_exit=112.0,
                    adaptive_exit=114.0,
                ),
                _row(
                    -4.0,
                    direction="BEARISH",
                    tier="STRONG",
                    reset_seen=True,
                    fixed_exit=94.0,
                    adaptive_exit=96.0,
                ),
            ),
            _result(
                date(2026, 8, 13),
                _row(
                    -3.0,
                    direction="BEARISH",
                    tier="MODERATE",
                    reset_seen=True,
                    fixed_exit=97.0,
                    adaptive_exit=99.0,
                ),
            ),
            _result(
                date(2026, 8, 14),
                _row(
                    8.0,
                    direction="BULLISH",
                    tier="STRONG",
                    reset_seen=True,
                    fixed_exit=109.0,
                    adaptive_exit=110.0,
                ),
            ),
        ]
    )

    assert report.evaluated_days == 3
    assert report.profitable_days == 2
    assert report.profitable_day_pct == 2 / 3 * 100
    assert report.total_net_points == 11.0
    assert report.median_daily_points == 6.0
    assert report.average_winner == 9.0
    assert report.average_loss == -3.5
    assert report.profit_factor == 18.0 / 7.0
    assert report.maximum_losing_streak == 2
    assert report.maximum_consecutive_losing_days == 1
    assert report.maximum_daily_drawdown == 4.0
    assert report.direction_performance["BULLISH"].net_points == 18.0
    assert report.direction_performance["BEARISH"].net_points == -7.0
    assert report.tier_performance["STRONG"].trades == 2
    assert report.tier_performance["MODERATE"].trades == 1
    assert report.entry_type_performance["FIRST_DIRECTION"].trades == 1
    assert report.entry_type_performance["RESET_ENTRY"].trades == 3
    assert report.trailing_comparison["FIXED"].net_points == 12.0
    assert report.trailing_comparison["ADAPTIVE_AUDIT"].net_points == 19.0


def test_promotion_checks_pass_for_consistent_unconcentrated_window():
    results = []
    daily_rows = (
        (6.0, -2.0),
        (5.0, -1.0),
        (4.0, -1.0),
        (3.0, -1.0),
        (2.0, -1.0),
        (1.0, -1.0),
        (-1.0,),
        (-1.0,),
        (2.0, -1.0),
        (-1.0,),
    )
    for offset, points in enumerate(daily_rows, start=1):
        results.append(
            _result(
                date(2026, 8, offset),
                *[_row(point) for point in points],
            )
        )

    report = analyze_historical_dri_risk_consistency(results)

    assert report.profitable_day_pct == 60.0
    assert report.profit_factor == 23.0 / 11.0
    assert report.median_daily_points > 0.0
    assert report.total_net_points == 12.0
    assert report.single_day_profit_concentration_pct < 50.0
    assert report.maximum_consecutive_losing_days == 2
    assert report.promotion_passed is True
    assert all(report.promotion_checks.values())


def test_non_positive_window_fails_profit_and_concentration_checks():
    report = analyze_historical_dri_risk_consistency(
        [
            _result(date(2026, 8, 12), _row(-2.0)),
            _result(date(2026, 8, 13), _row(1.0)),
        ]
    )

    assert report.total_net_points == -1.0
    assert report.single_day_profit_concentration_pct == 100.0
    assert report.promotion_checks["Total net points positive"] is False
    assert (
        report.promotion_checks[
            "No single day > 50% of total profit"
        ]
        is False
    )
    assert report.promotion_passed is False


def test_ignores_wait_block_and_unresolved_rows():
    ignored = [
        SimpleNamespace(execution="WOULD_WAIT", outcome_points=20.0),
        SimpleNamespace(execution="WOULD_BLOCK", outcome_points=-20.0),
        SimpleNamespace(execution="WOULD_TAKE", outcome_points=None),
    ]
    report = analyze_historical_dri_risk_consistency(
        [_result(date(2026, 8, 12), *ignored)]
    )

    assert report.total_net_points == 0.0
    assert report.direction_performance["BULLISH"].trades == 0
    assert report.maximum_losing_streak == 0
