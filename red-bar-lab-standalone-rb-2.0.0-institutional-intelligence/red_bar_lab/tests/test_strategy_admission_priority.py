from __future__ import annotations

from red_bar_lab.ui.strategy_account_admission_v2 import build_capital_reservation_proposal
from red_bar_lab.ui.strategy_admission_priority import prioritize_candidates


def candidate(candidate_id, role="ENTRY_1", **overrides):
    row = {
        "candidate_id": candidate_id,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "role": role,
        "combined_outcome": "FORWARD",
        "portfolio_outcome": "PORTFOLIO_READY_READ_ONLY",
        "lot_size": 75,
        "ltp": 100.0,
        "opportunity": {
            "entry_premium": 100.0,
            "initial_option_stop": 97.0,
            "estimated_slippage": 0.4,
            "estimated_charges": 0.3,
        },
    }
    row.update(overrides)
    return row


def account(cash=10000.0):
    return {
        "available_cash": cash,
        "reserved_capital": 0.0,
        "proposed_lots": 1,
        "maximum_risk_per_trade": 500.0,
        "strategy_risk": {
            "RSI_EXTREME_REVERSAL": {"consumed": 0.0, "limit": 1000.0},
        },
    }


def test_entry_1_precedes_entry_2_even_when_input_is_reversed():
    rows = prioritize_candidates([
        candidate("RSI-2", "ENTRY_2"),
        candidate("RSI-1", "ENTRY_1"),
    ])
    assert [row["candidate_id"] for row in rows] == ["RSI-1", "RSI-2"]
    assert [row["admission_priority_rank"] for row in rows] == [1, 2]


def test_candidate_score_breaks_tie_within_same_role():
    rows = prioritize_candidates([
        candidate("LOW", candidate_score=70.0),
        candidate("HIGH", candidate_score=90.0),
    ])
    assert [row["candidate_id"] for row in rows] == ["HIGH", "LOW"]


def test_contract_score_breaks_tie_after_candidate_score():
    rows = prioritize_candidates([
        candidate("LOW", candidate_score=90.0, ranking_score=70.0),
        candidate("HIGH", candidate_score=90.0, ranking_score=95.0),
    ])
    assert [row["candidate_id"] for row in rows] == ["HIGH", "LOW"]


def test_explicit_priority_override_has_highest_authority():
    rows = prioritize_candidates([
        candidate("ENTRY-1", "ENTRY_1", admission_priority=2),
        candidate("ENTRY-2", "ENTRY_2", admission_priority=1),
    ])
    assert [row["candidate_id"] for row in rows] == ["ENTRY-2", "ENTRY-1"]
    assert "explicit=1" in rows[0]["admission_priority_reason"]


def test_supported_history_precedes_limited_history_when_other_fields_tie():
    rows = prioritize_candidates([
        candidate("LIMITED", combined_outcome="FORWARD_WITHOUT_HISTORICAL_SUPPORT"),
        candidate("SUPPORTED", combined_outcome="FORWARD"),
    ])
    assert [row["candidate_id"] for row in rows] == ["SUPPORTED", "LIMITED"]


def test_candidate_id_is_stable_final_tie_breaker():
    rows = prioritize_candidates([candidate("B"), candidate("A")])
    assert [row["candidate_id"] for row in rows] == ["A", "B"]


def test_priority_controls_sequential_capital_allocation():
    result = build_capital_reservation_proposal(
        {
            "rows": [
                candidate("RSI-2", "ENTRY_2"),
                candidate("RSI-1", "ENTRY_1"),
            ]
        },
        account_context=account(cash=10000.0),
    )
    first, second = result["rows"]
    assert first["candidate_id"] == "RSI-1"
    assert first["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert first["capital_before_proposal"] == 10000.0
    assert first["capital_remaining_after_proposal"] == 2500.0
    assert second["candidate_id"] == "RSI-2"
    assert second["reservation_outcome"] == "WAIT"
    assert "WAIT_FOR_CAPITAL" in second["reservation_reason"]


def test_priority_layer_is_read_only():
    row = prioritize_candidates([candidate("RSI-1")])[0]
    assert row["priority_source_read_only"] is True

    result = build_capital_reservation_proposal(
        {"rows": [candidate("RSI-1")]},
        account_context=account(),
    )
    assert result["persisted"] is False
    assert result["reserved"] is False
    assert result["bundle_consumed"] is False
    assert result["submitted"] is False
