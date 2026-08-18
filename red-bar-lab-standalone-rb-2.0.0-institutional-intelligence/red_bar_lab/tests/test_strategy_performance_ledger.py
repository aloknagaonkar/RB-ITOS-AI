from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.strategy_performance_ledger import (
    build_strategy_performance_ledger,
)


def _order(strategy, status, pnl, signal, *, mode="FRESH_SIGNAL", rank=1, mfe=None, mae=None):
    row = {
        "execution_strategy_source": strategy,
        "status": status,
        "signal_id": signal,
        "entry_mode": mode,
        "candidate_rank": rank,
    }
    if status == "OPEN":
        row["unrealized_pnl"] = pnl
    else:
        row["realized_pnl"] = pnl
    if mfe is not None:
        row["mfe_points"] = mfe
    if mae is not None:
        row["mae_points"] = mae
    return row


def _strategy(result, source):
    return next(row for row in result["strategy_rows"] if row["strategy_source"] == source)


def test_strategy_results_are_isolated_and_open_pnl_is_not_a_completed_result():
    result = build_strategy_performance_ledger([
        _order("RED_BAR", "CLOSED", 100.0, "RB-1"),
        _order("RED_BAR", "CLOSED", -40.0, "RB-2"),
        _order("RED_BAR", "OPEN", 25.0, "RB-3"),
        _order("RSI_EXTREME_REVERSAL_V1", "CLOSED", 80.0, "RSI-1"),
    ])
    red_bar = _strategy(result, "RED_BAR")
    rsi = _strategy(result, "RSI_EXTREME_REVERSAL_V1")
    assert red_bar["completed_trades"] == 2
    assert red_bar["wins"] == 1
    assert red_bar["losses"] == 1
    assert red_bar["realized_net_pnl"] == 60.0
    assert red_bar["open_trades"] == 1
    assert red_bar["open_pnl"] == 25.0
    assert rsi["completed_trades"] == 1
    assert rsi["realized_net_pnl"] == 80.0


def test_win_rate_profit_factor_and_expectancy_are_deterministic():
    result = build_strategy_performance_ledger([
        _order("RED_BAR", "CLOSED", 100.0, "RB-1"),
        _order("RED_BAR", "CLOSED", 50.0, "RB-2"),
        _order("RED_BAR", "CLOSED", -30.0, "RB-3"),
        _order("RED_BAR", "CLOSED", 0.0, "RB-4"),
    ])
    row = _strategy(result, "RED_BAR")
    assert row["wins"] == 2
    assert row["losses"] == 1
    assert row["breakeven"] == 1
    assert row["win_rate_pct"] == 66.67
    assert row["profit_factor"] == 5.0
    assert row["expectancy_per_completed_trade"] == 30.0
    assert row["average_win"] == 75.0
    assert row["average_loss"] == -30.0


def test_entry_mode_and_candidate_rank_breakdowns_remain_strategy_owned():
    result = build_strategy_performance_ledger([
        _order("RED_BAR", "CLOSED", 20.0, "RB-1", mode="FRESH_SIGNAL", rank=1),
        _order("RED_BAR", "CLOSED", -10.0, "RB-2", mode="OPPORTUNITY_EXTENSION", rank=2),
        _order("DIRECTIONAL_REGIME", "CLOSED", 30.0, "DRI-1", mode="FRESH_SIGNAL", rank=1),
    ])
    assert any(
        row["strategy_source"] == "RED_BAR"
        and row["entry_mode"] == "OPPORTUNITY_EXTENSION"
        and row["realized_net_pnl"] == -10.0
        for row in result["entry_mode_rows"]
    )
    assert any(
        row["strategy_source"] == "DIRECTIONAL_REGIME"
        and row["candidate_rank"] == "RANK_1"
        and row["realized_net_pnl"] == 30.0
        for row in result["candidate_rank_rows"]
    )


def test_mfe_and_mae_are_reported_only_when_available():
    result = build_strategy_performance_ledger([
        _order("RED_BAR", "CLOSED", 20.0, "RB-1", mfe=12.0, mae=-4.0),
        _order("RED_BAR", "CLOSED", -10.0, "RB-2", mfe=8.0, mae=-6.0),
        _order("RED_BAR", "CLOSED", 5.0, "RB-3"),
    ])
    row = _strategy(result, "RED_BAR")
    assert row["average_mfe_points"] == 10.0
    assert row["average_mae_points"] == -5.0
    assert row["mfe_sample_size"] == 2
    assert row["mae_sample_size"] == 2


def test_no_losses_does_not_fabricate_infinite_profit_factor():
    result = build_strategy_performance_ledger([
        _order("RSI_EXTREME_REVERSAL_V1", "CLOSED", 40.0, "RSI-1"),
    ])
    row = _strategy(result, "RSI_EXTREME_REVERSAL_V1")
    assert row["profit_factor"] is None


def test_ledger_does_not_mutate_input_orders():
    orders = [_order("RED_BAR", "CLOSED", 10.0, "RB-1")]
    before = deepcopy(orders)
    result = build_strategy_performance_ledger(orders)
    assert orders == before
    assert result["source_read_only"] is True
    assert result["persisted"] is False
    assert result["execution_allowed"] is False
