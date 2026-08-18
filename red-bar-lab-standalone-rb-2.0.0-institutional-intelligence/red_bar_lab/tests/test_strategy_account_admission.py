from __future__ import annotations

from red_bar_lab.ui.strategy_account_admission import (
    build_capital_reservation_proposal,
    build_final_admission,
    build_portfolio_admission,
)


def _candidate(candidate_id="RSI-CAND-1", role="ENTRY_1", token="TOKEN-1"):
    return {
        "candidate_id": candidate_id,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "role": role,
        "identity_key": f"ID-{candidate_id}",
        "instrument_token": token,
        "trading_symbol": "NIFTY-PE",
        "contract_side": "PE",
        "expiry": "2026-08-27",
        "combined_outcome": "FORWARD",
        "ltp": 100.0,
        "lot_size": 75,
        "opportunity": {
            "entry_premium": 100.0,
            "initial_option_stop": 97.0,
            "estimated_slippage": 0.4,
            "estimated_charges": 0.3,
        },
    }


def _risk(*candidate_ids):
    return {
        "rows": [
            {
                "candidate_id": cid,
                "risk_outcome": "RISK_READY_READ_ONLY",
                "exact_reason": "ALL_ACCOUNT_AND_RISK_CHECKS_PASSED",
            }
            for cid in candidate_ids
        ]
    }


def _context(**overrides):
    value = {
        "available_cash": 20000.0,
        "reserved_capital": 0.0,
        "open_positions": 0,
        "maximum_open_positions": 5,
        "maximum_risk_per_trade": 1000.0,
        "proposed_lots": 1,
        "broker_ready": True,
        "account_ready": True,
        "emergency_stop": False,
        "active_positions": [],
        "admitted_candidates": [],
    }
    value.update(overrides)
    return value


def _source(enabled=True):
    return {"execution_enabled": enabled, "execution_eligible": enabled}


def test_portfolio_rejects_same_contract_already_active_across_strategies():
    candidate = _candidate()
    context = _context(active_positions=[{
        "strategy_id": "DIRECTIONAL_REGIME",
        "instrument_token": "TOKEN-1",
        "contract_side": "PE",
    }])
    row = build_portfolio_admission(
        {"rows": [candidate]},
        _risk("RSI-CAND-1"),
        account_context=context,
    )["rows"][0]
    assert row["portfolio_outcome"] == "REJECT"
    assert "REJECT_DUPLICATE_EXPOSURE" in row["portfolio_reason"]


def test_two_rsi_entries_remain_independent_but_share_remaining_capital():
    first = _candidate("RSI-CAND-1", "ENTRY_1", "TOKEN-1")
    second = _candidate("RSI-CAND-2", "ENTRY_2", "TOKEN-2")
    context = _context(available_cash=10000.0)
    portfolio = build_portfolio_admission(
        {"rows": [first, second]},
        _risk("RSI-CAND-1", "RSI-CAND-2"),
        account_context=context,
    )
    proposal = build_capital_reservation_proposal(portfolio, account_context=context)
    assert proposal["rows"][0]["reservation_outcome"] == "PROPOSED_READ_ONLY"
    assert proposal["rows"][0]["required_capital"] == 7500.0
    assert proposal["rows"][1]["reservation_outcome"] == "WAIT"
    assert "WAIT_FOR_CAPITAL" in proposal["rows"][1]["reservation_reason"]


def test_quantity_and_total_risk_are_transparent():
    candidate = _candidate()
    context = _context()
    portfolio = build_portfolio_admission(
        {"rows": [candidate]},
        _risk("RSI-CAND-1"),
        account_context=context,
    )
    row = build_capital_reservation_proposal(portfolio, account_context=context)["rows"][0]
    assert row["quantity"] == 75
    assert row["initial_option_risk"] == 225.0
    assert row["slippage_reserve"] == 30.0
    assert row["charges_reserve"] == 22.5
    assert row["total_proposed_risk"] == 277.5
    assert row["reserved"] is False


def test_position_slot_waits_before_final_admission():
    candidate = _candidate()
    context = _context(open_positions=1, maximum_open_positions=1)
    portfolio = build_portfolio_admission(
        {"rows": [candidate]},
        _risk("RSI-CAND-1"),
        account_context=context,
    )
    proposal = build_capital_reservation_proposal(portfolio, account_context=context)
    final = build_final_admission(proposal, execution_source_gate=_source(), account_context=context)
    assert final["rows"][0]["final_admission_decision"] == "WAIT_FOR_POSITION_SLOT"


def test_kill_switch_and_broker_readiness_have_final_authority():
    candidate = _candidate()
    base = _context()
    portfolio = build_portfolio_admission({"rows": [candidate]}, _risk("RSI-CAND-1"), account_context=base)
    proposal = build_capital_reservation_proposal(portfolio, account_context=base)

    killed = build_final_admission(
        proposal,
        execution_source_gate=_source(),
        account_context=_context(emergency_stop=True),
    )["rows"][0]
    broker_wait = build_final_admission(
        proposal,
        execution_source_gate=_source(),
        account_context=_context(broker_ready=False),
    )["rows"][0]
    assert killed["final_admission_decision"] == "REJECT_KILL_SWITCH"
    assert broker_wait["final_admission_decision"] == "WAIT_BROKER_NOT_READY"


def test_ready_candidate_stops_at_read_only_final_admission():
    candidate = _candidate()
    context = _context()
    portfolio = build_portfolio_admission({"rows": [candidate]}, _risk("RSI-CAND-1"), account_context=context)
    proposal = build_capital_reservation_proposal(portfolio, account_context=context)
    result = build_final_admission(proposal, execution_source_gate=_source(), account_context=context)
    row = result["rows"][0]
    assert row["final_admission_decision"] == "ADMISSION_READY_READ_ONLY"
    assert row["next_step"].startswith("Section 9")
    assert row["persisted"] is False
    assert row["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False


def test_account_admission_module_has_no_mutation_calls():
    import red_bar_lab.ui.strategy_account_admission as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "reserve_contract" not in source
    assert "mark_bundle_consumed" not in source
    assert "create_candidate" not in source
