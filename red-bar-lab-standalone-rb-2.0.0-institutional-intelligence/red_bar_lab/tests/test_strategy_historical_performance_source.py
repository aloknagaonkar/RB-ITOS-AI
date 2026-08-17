from __future__ import annotations

from red_bar_lab.ui.strategy_historical_performance_source import (
    load_completed_trade_history,
    normalize_completed_trade,
)


class _Database:
    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER-STD"
        return [
            {
                "order_id": "O-1",
                "strategy_id": "RSI_EXTREME_REVERSAL",
                "strategy_version": "RSI-V1",
                "option_side": "PE",
                "status": "CLOSED",
                "entry_price": 100.0,
                "exit_price": 106.0,
                "estimated_costs": 0.4,
                "mfe_points": 8.0,
                "mae_points": 2.0,
                "exit_policy_version": "EXIT-V1",
            },
            {"order_id": "O-OPEN", "status": "OPEN", "entry_price": 100.0},
        ]


class _BrokenDatabase:
    def read_paper_execution_orders(self, account_id):
        raise RuntimeError("unavailable")


def test_normalize_completed_trade_derives_option_points_read_only():
    row = normalize_completed_trade({
        "strategy_id": "DIRECTIONAL_REGIME",
        "direction": "BULLISH",
        "trade_status": "COMPLETED",
        "entry_price": 50.0,
        "exit_price": 54.5,
    })
    assert row["side"] == "CE"
    assert row["net_points"] == 4.5
    assert row["source_read_only"] is True
    assert row["execution_allowed"] is False


def test_loader_uses_established_paper_order_reader_and_filters_open_rows():
    result = load_completed_trade_history(_Database())
    assert result["source_status"] == "READY"
    assert result["raw_row_count"] == 2
    assert result["normalized_row_count"] == 1
    assert result["records"][0]["trade_id"] == "O-1"
    assert result["records"][0]["net_points"] == 6.0


def test_loader_reports_unavailable_without_fabricating_history():
    result = load_completed_trade_history(_BrokenDatabase())
    assert result["source_status"] == "UNAVAILABLE"
    assert result["records"] == []
    assert "HISTORY_READ_FAILED" in result["source_reason"]


def test_source_module_has_no_write_or_execution_calls():
    import red_bar_lab.ui.strategy_historical_performance_source as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "create_" not in source
    assert "insert_" not in source
    assert "update_" not in source
    assert "submit_order" not in source
