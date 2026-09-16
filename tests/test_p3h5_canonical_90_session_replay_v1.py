from pathlib import Path

from market_lab.historical_multi_session_replay_v1 import (
    CanonicalReplayReport,
    SessionReplayRow,
    _max_drawdown_sum_returns,
)


def test_max_drawdown_additive_returns():
    assert _max_drawdown_sum_returns([5.0, -2.0, -4.0, 3.0]) == -6.0


def test_report_summary_counts_break_even_separately():
    report = CanonicalReplayReport(universe_dates=["2026-08-25"])
    report.session_rows.append(
        SessionReplayRow(
            session_date="2026-08-25",
            status="PASS",
            signals=3,
            entries=3,
            closed=3,
            winners=1,
            losers=1,
            breakeven=1,
        )
    )
    report.trade_returns_pct.extend([10.0, -5.0, 0.0])
    report.trade_directions.extend(["BULLISH", "BEARISH", "BULLISH"])
    report.trade_exit_reasons.extend(
        ["TRAIL_STOP", "HARD_STOP", "BREAKEVEN_STOP"]
    )
    s = report.summary()
    assert s["winners"] == 1
    assert s["losers"] == 1
    assert s["breakeven"] == 1
    assert s["win_rate_non_breakeven_pct"] == 50.0
    assert s["exit_reason_counts"]["TRAIL_STOP"] == 1
