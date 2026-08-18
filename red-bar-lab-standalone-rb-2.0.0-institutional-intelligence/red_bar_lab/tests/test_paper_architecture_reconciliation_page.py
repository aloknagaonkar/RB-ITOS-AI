from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.pages.paper_architecture_reconciliation_v4 import (
    SECTION_10_STAGES,
    build_reconciliation_snapshot,
)
from red_bar_lab.ui.workspace_page_runtime import PAGE_MODULE_PATHS


def test_reconciliation_page_is_registered_after_paper_trading():
    pages = list(PAGE_MODULE_PATHS)
    page = "Paper Architecture Reconciliation"

    assert PAGE_MODULE_PATHS[page] == (
        "red_bar_lab.ui.pages.paper_architecture_reconciliation_v4"
    )
    assert pages.index(page) == pages.index("Paper Trading") + 1


def test_section_10_status_sequence_is_explicit():
    assert [row["section"] for row in SECTION_10_STAGES] == [
        "10A", "10B", "10C", "10D", "10E", "10F",
    ]
    assert [row["status"] for row in SECTION_10_STAGES] == [
        "COMPLETED",
        "COMPLETED",
        "COMPLETED",
        "COMPLETED",
        "IMPLEMENTED_DISABLED",
        "NEXT",
    ]
    assert SECTION_10_STAGES[3]["authority"] == "SHADOW_ONLY"
    assert SECTION_10_STAGES[4]["authority"] == "DISABLED"
    assert SECTION_10_STAGES[5]["authority"] == "NOT_EVALUATED"


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
    assert result["comparison"]["counts"]["NOT_COMPARABLE"] == 2
    assert result["shadow_router"]["outcome"] == "NO_SHADOW_EVIDENCE"
    assert result["controlled_paper_activation"]["outcome"] == "NO_SHADOW_ROUTES"
    assert result["source_read_only"] is True
    assert result["persisted"] is False
    assert result["execution_allowed"] is False
    assert result["paper_order_created"] is False
    assert result["queue_state_changed"] is False
    assert result["capital_reserved"] is False


def test_reconciliation_snapshot_builds_shadow_routes_and_blocks_activation():
    evidence = [
        {
            "strategy_id": "RED_BAR",
            "signal_id": "RB-1",
            "bundle_id": "BUNDLE-1",
            "candidate_id": "CANDIDATE-1",
            "snapshot_timestamp": "2026-08-18T09:20:00+05:30",
            "evaluation_timestamp": "2026-08-18T09:20:01+05:30",
            "new_chain_decision": "ADMIT_READ_ONLY",
        }
    ]

    result = build_reconciliation_snapshot([], evidence)

    assert result["shadow_router"]["outcome"] == "ROUTED_SHADOW_ONLY"
    assert result["shadow_router"]["routed_count"] == 1
    assert result["shadow_router"]["execution_enabled"] is False
    assert result["shadow_router"]["position_created"] is False
    assert result["controlled_paper_activation"]["outcome"] == "PAPER_ACTIVATION_BLOCKED"
    assert result["controlled_paper_activation"]["position_created"] is False
    assert result["controlled_paper_activation"]["lifecycle_started"] is False


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
        "RED_BAR", "DIRECTIONAL_REGIME", "RSI_EXTREME_REVERSAL_V1",
    }
