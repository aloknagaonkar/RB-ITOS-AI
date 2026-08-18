from __future__ import annotations

from red_bar_lab.ui.strategy_account_context_source import (
    build_account_context_from_rows,
    load_account_risk_context,
    merge_account_context,
)


class _Database:
    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER-STD"
        return [
            {
                "order_id": "OPEN-1",
                "status": "OPEN",
                "strategy_id": "RSI_EXTREME_REVERSAL",
                "exchange": "NFO",
                "instrument_token": "101",
                "trading_symbol": "NIFTY-PE",
                "option_side": "PE",
                "quantity": 75,
                "entry_price": 100.0,
                "ltp": 104.0,
                "identity_key": "RSI|B1|101|ENTRY_1",
            },
            {
                "order_id": "CLOSED-1",
                "status": "CLOSED",
                "quantity": 75,
                "entry_price": 90.0,
                "exit_price": 92.0,
            },
            {
                "order_id": "PENDING-1",
                "status": "RESERVED",
                "quantity": 50,
                "entry_price": 20.0,
            },
        ]

    def read_paper_account_state(self, account_id):
        return {
            "available_cash": 100000.0,
            "broker_connected": True,
            "trading_enabled": True,
            "kill_switch": False,
        }

    def read_risk_settings(self, account_id):
        return {
            "daily_loss_limit": 5000.0,
            "maximum_portfolio_exposure": 150000.0,
            "maximum_open_positions": 4,
            "maximum_risk_per_trade": 1000.0,
            "default_lots": 1,
            "cooldown_active": False,
            "strategy_risk": {
                "RSI_EXTREME_REVERSAL": {"consumed": 200.0, "limit": 1200.0},
            },
        }


class _OrdersOnlyDatabase:
    def read_paper_execution_orders(self, account_id):
        return [{"status": "OPEN", "quantity": 10, "entry_price": 50.0, "ltp": 55.0}]


def test_build_context_derives_pnl_exposure_positions_and_reserved_capital():
    result = build_account_context_from_rows(
        [
            {"status": "OPEN", "quantity": 10, "entry_price": 100.0, "ltp": 105.0},
            {"status": "CLOSED", "quantity": 5, "entry_price": 50.0, "exit_price": 53.0},
            {"status": "RESERVED", "quantity": 4, "entry_price": 25.0},
        ],
        evaluated_at="2026-08-18T00:00:00+00:00",
    )
    assert result["open_positions"] == 1
    assert result["portfolio_exposure"] == 1050.0
    assert result["daily_unrealized_pnl"] == 50.0
    assert result["daily_realized_pnl"] == 15.0
    assert result["reserved_capital"] == 100.0
    assert result["field_provenance"]["portfolio_exposure"]["source"] == "PAPER_EXECUTION_ORDERS_DERIVED"


def test_loader_combines_orders_snapshot_and_risk_settings_with_provenance():
    result = load_account_risk_context(_Database())
    assert result["context_status"] == "READY"
    assert result["available_cash"] == 100000.0
    assert result["daily_realized_pnl"] == 150.0
    assert result["daily_unrealized_pnl"] == 300.0
    assert result["portfolio_exposure"] == 7800.0
    assert result["reserved_capital"] == 1000.0
    assert result["maximum_open_positions"] == 4.0
    assert result["broker_ready"] is True
    assert result["account_ready"] is True
    assert result["emergency_stop"] is False
    assert result["active_positions"][0]["contract_exposure_key"] == "NFO|101"
    assert result["source_readers"]["orders"] == "read_paper_execution_orders"
    assert result["source_read_only"] is True
    assert result["execution_allowed"] is False


def test_orders_only_source_is_partial_and_does_not_invent_cash_or_limits():
    result = load_account_risk_context(_OrdersOnlyDatabase())
    assert result["context_status"] == "PARTIAL"
    assert result["available_cash"] is None
    assert result["daily_loss_limit"] is None
    assert result["open_positions"] == 1
    assert result["portfolio_exposure"] == 550.0


def test_explicit_context_overrides_discovered_values_and_keeps_provenance():
    merged = merge_account_context(
        {"available_cash": 1000.0, "field_provenance": {}},
        {"available_cash": 2500.0, "maximum_open_positions": 2},
    )
    assert merged["available_cash"] == 2500.0
    assert merged["maximum_open_positions"] == 2
    assert merged["field_provenance"]["available_cash"]["source"] == "EXPLICIT_CALLER_OVERRIDE"
    assert merged["explicit_override_count"] == 2


def test_source_module_has_no_mutating_database_or_execution_calls():
    import red_bar_lab.ui.strategy_account_context_source as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "insert_" not in source
    assert "update_" not in source
    assert "delete_" not in source
    assert "reserve_contract" not in source
