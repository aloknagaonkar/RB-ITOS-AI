from __future__ import annotations

import pytest

from red_bar_lab.ui.strategy_opportunity_history_gate import (
    build_opportunity_history_gate,
    forward_candidates_for_risk,
)


def _candidate(candidate_id="RSI-CAND-1", role="ENTRY_1"):
    return {
        "candidate_id": candidate_id,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "role": role,
        "validation_outcome": "HANDOFF_READY",
        "contract_side": "PE",
        "requested_side": "PE",
        "ltp": 100.0,
        "bid": 99.5,
        "ask": 100.5,
        "spread_pct": 1.0,
        "lot_size": 75,
        "snapshot_freshness": "FRESH",
        "bundle_freshness": "FRESH",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def _opportunity(candidate_id="RSI-CAND-1", **overrides):
    value = {
        "initial_option_stop": 97.0,
        "estimated_slippage": 0.4,
        "estimated_charges": 0.3,
        "expected_favourable_excursion": 8.0,
        "expected_adverse_excursion": 2.5,
        "available_capital": 100000.0,
        "proposed_lots": 1,
    }
    value.update(overrides)
    return {"candidates": {candidate_id: value}}


def _history(strategy="RSI_EXTREME_REVERSAL", side="PE", points=3.0, count=20):
    return [
        {
            "strategy_id": strategy,
            "side": side,
            "status": "CLOSED",
            "net_points": points,
            "estimated_costs": 0.2,
            "mfe_points": 6.0,
            "mae_points": 2.0,
        }
        for _ in range(count)
    ]


def test_opportunity_passes_with_positive_cost_adjusted_edge():
    result = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
        historical_records=[],
    )
    row = result["rows"][0]
    assert row["opportunity_outcome"] == "PASS"
    assert row["opportunity"]["initial_risk"] == pytest.approx(3.0)
    assert row["opportunity"]["effective_risk"] == pytest.approx(3.7)
    assert row["opportunity"]["expected_net_edge"] == pytest.approx(4.8)
    assert row["combined_outcome"] == "FORWARD_WITHOUT_HISTORICAL_SUPPORT"


def test_missing_stop_waits_and_negative_edge_rejects():
    waiting = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(initial_option_stop=None),
    )["rows"][0]
    rejected = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(expected_favourable_excursion=2.0, expected_adverse_excursion=3.0),
    )["rows"][0]
    assert waiting["opportunity_outcome"] == "WAIT"
    assert "INVALID_OR_MISSING_INITIAL_STOP" in waiting["opportunity"]["exact_reason"]
    assert rejected["opportunity_outcome"] == "REJECT"
    assert rejected["combined_outcome"] == "REJECT"


def test_history_is_strictly_strategy_owned():
    records = _history(count=3) + _history(strategy="DIRECTIONAL_REGIME", count=50)
    row = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
        historical_records=records,
    )["rows"][0]
    assert row["historical"]["sample_count"] == 3
    assert row["historical_outcome"] == "NO_VETO_INSUFFICIENT_DATA"


def test_sample_confidence_thresholds_and_positive_history():
    observe = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
        historical_records=_history(count=10),
    )["rows"][0]
    passed = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
        historical_records=_history(count=20),
    )["rows"][0]
    assert observe["historical_outcome"] == "OBSERVE_ONLY"
    assert observe["combined_outcome"] == "OBSERVE_ONLY"
    assert passed["historical_outcome"] == "PASS"
    assert passed["combined_outcome"] == "FORWARD"


def test_materially_negative_history_rejects_when_sample_is_sufficient():
    row = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
        historical_records=_history(points=-2.0, count=20),
    )["rows"][0]
    assert row["historical_outcome"] == "REJECT"
    assert row["combined_outcome"] == "REJECT"


def test_rsi_entries_are_independent_and_only_forward_results_reach_risk():
    first = _candidate("RSI-CAND-1", "ENTRY_1")
    second = _candidate("RSI-CAND-2", "ENTRY_2")
    context = _opportunity("RSI-CAND-1")
    context["candidates"]["RSI-CAND-2"] = {
        **context["candidates"]["RSI-CAND-1"],
        "expected_favourable_excursion": 1.0,
        "expected_adverse_excursion": 3.0,
    }
    result = build_opportunity_history_gate(
        {"candidates": [first, second]},
        opportunity_context=context,
        historical_records=[],
    )
    assert result["rows"][0]["combined_outcome"] == "FORWARD_WITHOUT_HISTORICAL_SUPPORT"
    assert result["rows"][1]["combined_outcome"] == "REJECT"
    forwarded = forward_candidates_for_risk(result)
    assert [row["candidate_id"] for row in forwarded["candidates"]] == ["RSI-CAND-1"]


def test_gate_is_read_only():
    result = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
    )
    row = result["rows"][0]
    assert row["persisted"] is False
    assert row["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False

    import red_bar_lab.ui.strategy_opportunity_history_gate as module
    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
