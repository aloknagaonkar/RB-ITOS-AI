from __future__ import annotations

from red_bar_lab.ui.strategy_account_admission_v2 import build_capital_reservation_proposal


def row(candidate_id, role, strategy_id="RSI_EXTREME_REVERSAL"):
    return {
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "role": role,
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


def account(limit=700.0, consumed=100.0):
    return {
        "available_cash": 50000.0,
        "reserved_capital": 0.0,
        "proposed_lots": 1,
        "maximum_risk_per_trade": 500.0,
        "strategy_risk": {
            "RSI_EXTREME_REVERSAL": {"consumed": consumed, "limit": limit},
            "DIRECTIONAL_REGIME": {"consumed": 0.0, "limit": 1000.0},
        },
    }


def test_two_rsi_entries_consume_one_strategy_budget_sequentially():
    result = build_capital_reservation_proposal(
        {"rows": [row("RSI-1", "ENTRY_1"), row("RSI-2", "ENTRY_2")]},
        account_context=account(limit=700.0, consumed=100.0),
    )
    first, second = result["rows"]
    assert first["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert first["total_proposed_risk"] == 277.5
    assert first["projected_strategy_risk"] == 377.5
    assert second["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert second["strategy_risk_proposed_before"] == 277.5
    assert second["projected_strategy_risk"] == 655.0
    assert result["proposed_strategy_risk"]["RSI_EXTREME_REVERSAL"] == 555.0


def test_second_rsi_entry_rejects_when_combined_strategy_risk_exceeds_limit():
    result = build_capital_reservation_proposal(
        {"rows": [row("RSI-1", "ENTRY_1"), row("RSI-2", "ENTRY_2")]},
        account_context=account(limit=600.0, consumed=100.0),
    )
    first, second = result["rows"]
    assert first["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert second["reservation_outcome"] == "REJECT"
    assert "REJECT_STRATEGY_RISK_LIMIT" in second["reservation_reason"]
    assert result["proposed_strategy_risk"]["RSI_EXTREME_REVERSAL"] == 277.5


def test_other_strategy_has_independent_risk_budget():
    result = build_capital_reservation_proposal(
        {
            "rows": [
                row("RSI-1", "ENTRY_1"),
                row("DRI-1", "PRIMARY", strategy_id="DIRECTIONAL_REGIME"),
            ]
        },
        account_context=account(limit=400.0, consumed=100.0),
    )
    by_candidate = {item["candidate_id"]: item for item in result["rows"]}
    assert by_candidate["RSI-1"]["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert by_candidate["DRI-1"]["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert by_candidate["RSI-1"]["strategy_risk_consumed_before"] == 100.0
    assert by_candidate["DRI-1"]["strategy_risk_consumed_before"] == 0.0
    assert by_candidate["DRI-1"]["admission_priority_rank"] == 1
    assert by_candidate["RSI-1"]["admission_priority_rank"] == 2


def test_missing_strategy_scope_waits_without_fabricating_limit():
    values = account()
    values["strategy_risk"].pop("RSI_EXTREME_REVERSAL")
    result = build_capital_reservation_proposal(
        {"rows": [row("RSI-1", "ENTRY_1")]},
        account_context=values,
    )["rows"][0]
    assert result["reservation_outcome"] == "WAIT"
    assert "STRATEGY_RISK_SCOPE_UNAVAILABLE" in result["reservation_reason"]


def test_strategy_risk_proposal_is_read_only():
    result = build_capital_reservation_proposal(
        {"rows": [row("RSI-1", "ENTRY_1")]},
        account_context=account(),
    )
    candidate = result["rows"][0]
    assert candidate["persisted"] is False
    assert candidate["reserved"] is False
    assert candidate["bundle_consumed"] is False
    assert candidate["submitted"] is False
