from datetime import date
from types import SimpleNamespace

from red_bar_lab.services.historical_dri_outcome_reconciliation import (
    reconcile_historical_dri_outcomes,
)


def _row(*, execution="WOULD_TAKE", headline=10.0, entry=100.0, baseline=112.0, fixed=108.0, adaptive=109.0):
    return SimpleNamespace(
        execution=execution,
        outcome_points=headline,
        option_entry_price=entry,
        option_exit_price=baseline,
        trailing_exit_price=fixed,
        adaptive_trailing_exit_price=adaptive,
        timestamp="10:00",
        signal_id="s1",
        direction="BULLISH",
        outcome_basis="OPTION_EXIT",
        exit_reason="BASELINE",
        trailing_exit_reason="TRAIL",
        adaptive_trailing_exit_reason="ADAPTIVE",
    )


def _result(*rows):
    return SimpleNamespace(trading_date=date(2026, 8, 14), rows=rows)


def test_reconciliation_uses_same_executed_trade_set():
    report = reconcile_historical_dri_outcomes(
        [_result(_row(), _row(execution="WOULD_WAIT", headline=99.0))]
    )

    assert report.executed_trades == 1
    assert report.headline_net_points == 10.0
    assert report.baseline_net_points == 12.0
    assert report.fixed_net_points == 8.0
    assert report.adaptive_net_points == 9.0
    assert report.headline_vs_fixed_delta == 2.0


def test_missing_exit_is_counted_as_non_comparable_not_zero():
    report = reconcile_historical_dri_outcomes(
        [_result(_row(fixed=None, adaptive=None))]
    )

    assert report.executed_trades == 1
    assert report.fixed_comparable == 0
    assert report.adaptive_comparable == 0
    assert report.fixed_net_points == 0.0
    assert report.rows[0]["Comparable"] is False


def test_summary_identifies_each_measurement_basis():
    report = reconcile_historical_dri_outcomes([_result(_row())])
    rows = report.summary_rows()

    assert [row["Model"] for row in rows] == [
        "HEADLINE_OUTCOME",
        "BASELINE_EXIT",
        "FIXED_TRAILING",
        "ADAPTIVE_TRAILING_AUDIT",
    ]
    assert "option_exit_price" in rows[1]["Basis"]
