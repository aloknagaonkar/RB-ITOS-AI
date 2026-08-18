from __future__ import annotations

from red_bar_lab.ui.strategy_attribution import (
    DIRECTIONAL_REGIME_STRATEGY_SOURCE,
    RED_BAR_STRATEGY_SOURCE,
    RSI_STRATEGY_SOURCE,
    UNKNOWN_STRATEGY_SOURCE,
    build_strategy_attribution,
    build_strategy_performance_summary,
    normalize_strategy_source,
)


def test_explicit_strategy_sources_remain_primary_owners():
    assert normalize_strategy_source({"execution_strategy_source": "RED_BAR"}) == RED_BAR_STRATEGY_SOURCE
    assert normalize_strategy_source({"execution_strategy_source": "DIRECTIONAL_REGIME"}) == DIRECTIONAL_REGIME_STRATEGY_SOURCE
    assert normalize_strategy_source({"execution_strategy_source": "RSI_EXTREME_REVERSAL_V1"}) == RSI_STRATEGY_SOURCE


def test_legacy_signal_prefixes_are_inferred_without_rewriting_orders():
    assert normalize_strategy_source({"signal_id": "RB-ABC"}) == RED_BAR_STRATEGY_SOURCE
    assert normalize_strategy_source({"signal_id": "DRI-ABC"}) == DIRECTIONAL_REGIME_STRATEGY_SOURCE
    assert normalize_strategy_source({"signal_id": "RSI-ABC"}) == RSI_STRATEGY_SOURCE
    assert normalize_strategy_source({"signal_id": "UNKNOWN-ABC"}) == UNKNOWN_STRATEGY_SOURCE


def test_supporting_dri_does_not_take_ownership_from_red_bar():
    order = {
        "order_id": "PAPER-1",
        "signal_id": "RB-1",
        "execution_strategy_source": "RED_BAR",
        "tradingsymbol": "NIFTY26AUG25000PE",
        "entry_reason": (
            "RB093_QUEUE_APPROVED RANK=1 TSS=75.00 PROB=82.00 "
            "EV=1.200 DIRECTIONAL_REGIME_BONUS=5.0 MODE=OPPORTUNITY_EXTENSION"
        ),
        "directional_regime_status": "ALIGNED",
        "selection_score": 75.0,
        "execution_probability_pct": 82.0,
        "expected_value_pct": 1.2,
    }
    result = build_strategy_attribution(order, None, None)
    assert result["strategy_source"] == RED_BAR_STRATEGY_SOURCE
    assert result["strategy"] == "Red Bar"
    assert "DRI ALIGNED" in result["supporting_intelligence"]
    assert "Institutional Committee" in result["supporting_intelligence"]
    assert result["opened_by"] == "RB093_BACKGROUND_QUEUE_EXECUTOR"
    assert result["queue_source"] == "RB093_QUEUE"


def test_rsi_signal_and_entry_role_are_preserved():
    result = build_strategy_attribution(
        {
            "order_id": "PAPER-RSI",
            "signal_id": "RSI-1",
            "rsi_signal_id": "RSI-1",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "rsi_entry_role": "ENTRY_2",
            "tradingsymbol": "NIFTY26AUG25000CE",
        },
        None,
        None,
    )
    assert result["strategy_source"] == RSI_STRATEGY_SOURCE
    assert result["entry_role"] == "ENTRY_2"
    assert result["signal_id"] == "RSI-1"


def test_performance_summary_is_separate_by_primary_strategy():
    rows = build_strategy_performance_summary([
        {
            "execution_strategy_source": "RED_BAR",
            "status": "OPEN",
            "unrealized_pnl": 100.0,
        },
        {
            "execution_strategy_source": "RED_BAR",
            "status": "CLOSED",
            "realized_pnl": -50.0,
        },
        {
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "status": "CLOSED",
            "realized_pnl": 25.0,
        },
    ])
    by_source = {row["strategy_source"]: row for row in rows}
    assert by_source[RED_BAR_STRATEGY_SOURCE]["open_trades"] == 1
    assert by_source[RED_BAR_STRATEGY_SOURCE]["closed_pnl"] == -50.0
    assert by_source[RSI_STRATEGY_SOURCE]["closed_trades"] == 1
    assert by_source[RSI_STRATEGY_SOURCE]["closed_pnl"] == 25.0


def test_attribution_builder_does_not_mutate_input():
    order = {"signal_id": "RB-1", "entry_reason": "RB093_QUEUE_APPROVED"}
    before = dict(order)
    build_strategy_attribution(order, None, None)
    assert order == before
