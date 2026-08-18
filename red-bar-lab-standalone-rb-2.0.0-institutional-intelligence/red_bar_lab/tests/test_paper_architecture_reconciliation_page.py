from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.pages.paper_architecture_reconciliation import (
    SECTION_10_STAGES,
    build_reconciliation_snapshot,
)
from red_bar_lab.ui.workspace_page_runtime import PAGE_MODULE_PATHS


def test_reconciliation_page_is_registered_after_paper_trading():
    pages = list(PAGE_MODULE_PATHS)
    page = "Paper Architecture Reconciliation"

    assert PAGE_MODULE_PATHS[page] == (
        "red_bar_lab.ui.pages.paper_architecture_reconciliation"
    )
    assert pages.index(page) == pages.index("Paper Trading") + 1


def test_section_10_status_sequence_is_explicit():
    assert [row["section"] for row in SECTION_10_STAGES] == [
        "10A",
        "10B",
        "10C",
        "10D",
        "10E",
        "10F",
    ]
    assert [row["status"] for row in SECTION_10_STAGES] == [
        "COMPLETED",
        "COMPLETED",
        "NEXT",
        "PENDING",
        "PENDING",
        "PENDING",
    ]


def test_reconciliation_snapshot_is_read_only_and_does_not_mutate_orders():
    orders = [
        {
            "order_id": "PAPER-1",
            "status": "OPEN",
            "execution_strategy_source": "RED_BAR",
            "signal_id": "RB-1",
            "unrealized_pnl": 125.0,
        },
        {
            "order_id": "PAPER-2",
            "status": "CLOSED",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "signal_id": "RSI-2",
            "realized_pnl": -50.0,
        },
    ]
    original = deepcopy(orders)

    result = build_reconciliation_snapshot(orders)

    assert orders == original
    assert result["order_count"] == 2
    assert result["open_order_count"] == 1
    assert result["closed_order_count"] == 1
    assert result["source_read_only"] is True
    assert result["persisted"] is False
    assert result["execution_allowed"] is False
    assert result["paper_order_created"] is False
    assert result["queue_state_changed"] is False
    assert result["capital_reserved"] is False


def test_reconciliation_snapshot_preserves_strategy_ownership():
    result = build_reconciliation_snapshot(
        [
            {
                "order_id": "PAPER-RB",
                "status": "CLOSED",
                "execution_strategy_source": "RED_BAR",
                "signal_id": "RB-1",
                "realized_pnl": 100.0,
            },
            {
                "order_id": "PAPER-DRI",
                "status": "CLOSED",
                "execution_strategy_source": "DIRECTIONAL_REGIME",
                "signal_id": "DRI-1",
                "realized_pnl": 50.0,
            },
            {
                "order_id": "PAPER-RSI",
                "status": "CLOSED",
                "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
                "signal_id": "RSI-1",
                "realized_pnl": -25.0,
            },
        ]
    )

    sources = {
        row["strategy_source"]
        for row in result["performance_ledger"]["strategy_rows"]
    }
    assert sources == {
        "RED_BAR",
        "DIRECTIONAL_REGIME",
        "RSI_EXTREME_REVERSAL_V1",
    }
