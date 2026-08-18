from __future__ import annotations

from red_bar_lab.ui.strategy_execution_decision_gate import (
    build_execution_decision_gate,
)


def _opportunity(candidate_id="RSI-CAND-1", outcome="FORWARD", role="ENTRY_1"):
    return {
        "rows": [{
            "candidate_id": candidate_id,
            "strategy_id": "RSI_EXTREME_REVERSAL",
            "bundle_id": "BUNDLE-1",
            "signal_id": "SIGNAL-1",
            "role": role,
            "contract_side": "PE",
            "trading_symbol": "NIFTY-PE",
            "combined_outcome": outcome,
        }]
    }


def _risk(candidate_id="RSI-CAND-1", outcome="RISK_READY_READ_ONLY"):
    return {
        "rows": [{
            "candidate_id": candidate_id,
            "risk_outcome": outcome,
            "exact_reason": (
                "ALL_ACCOUNT_AND_RISK_CHECKS_PASSED"
                if outcome == "RISK_READY_READ_ONLY"
                else "RISK_REASON"
            ),
        }]
    }


def _source(enabled=True):
    return {
        "execution_enabled": enabled,
        "execution_eligible": enabled,
    }


def test_forward_and_risk_ready_reaches_committee_readiness():
    result = build_execution_decision_gate(
        _opportunity(),
        _risk(),
        execution_source_gate=_source(True),
    )
    row = result["rows"][0]
    assert row["execution_decision"] == "READY_FOR_COMMITTEE_READ_ONLY"
    assert row["historical_authority"] == "SUPPORTED"
    assert result["ready_count"] == 1


def test_forward_without_history_is_explicitly_limited_but_may_proceed():
    row = build_execution_decision_gate(
        _opportunity(outcome="FORWARD_WITHOUT_HISTORICAL_SUPPORT"),
        _risk(),
        execution_source_gate=_source(True),
    )["rows"][0]
    assert row["execution_decision"] == "READY_FOR_COMMITTEE_READ_ONLY"
    assert row["historical_authority"] == "LIMITED"
    assert "LIMITED_HISTORICAL_EVIDENCE" in row["exact_reason"]


def test_execution_source_disabled_blocks_only_at_execution_gate():
    row = build_execution_decision_gate(
        _opportunity(),
        _risk(),
        execution_source_gate=_source(False),
    )["rows"][0]
    assert row["execution_decision"] == "EXECUTION_BLOCKED_READ_ONLY"
    assert "EXECUTION_SOURCE_DISABLED" in row["exact_reason"]


def test_risk_wait_and_block_have_precedence():
    waiting = build_execution_decision_gate(
        _opportunity(),
        _risk(outcome="WAIT"),
        execution_source_gate=_source(True),
    )["rows"][0]
    blocked = build_execution_decision_gate(
        _opportunity(),
        _risk(outcome="RISK_BLOCKED"),
        execution_source_gate=_source(True),
    )["rows"][0]
    assert waiting["execution_decision"] == "WAIT"
    assert blocked["execution_decision"] == "EXECUTION_BLOCKED_READ_ONLY"


def test_observe_only_candidate_does_not_reach_risk_or_committee():
    row = build_execution_decision_gate(
        _opportunity(outcome="OBSERVE_ONLY"),
        {"rows": []},
        execution_source_gate=_source(True),
    )["rows"][0]
    assert row["section_8a_risk_outcome"] == "NOT_EVALUATED"
    assert row["execution_decision"] == "OBSERVE_ONLY"


def test_rsi_entries_are_evaluated_independently():
    opportunity = {
        "rows": [
            _opportunity("RSI-CAND-1", "FORWARD", "ENTRY_1")["rows"][0],
            _opportunity("RSI-CAND-2", "FORWARD", "ENTRY_2")["rows"][0],
        ]
    }
    risk = {
        "rows": [
            _risk("RSI-CAND-1", "RISK_READY_READ_ONLY")["rows"][0],
            _risk("RSI-CAND-2", "RISK_BLOCKED")["rows"][0],
        ]
    }
    rows = build_execution_decision_gate(
        opportunity,
        risk,
        execution_source_gate=_source(True),
    )["rows"]
    assert rows[0]["execution_decision"] == "READY_FOR_COMMITTEE_READ_ONLY"
    assert rows[1]["execution_decision"] == "EXECUTION_BLOCKED_READ_ONLY"


def test_gate_is_read_only():
    result = build_execution_decision_gate(
        _opportunity(),
        _risk(),
        execution_source_gate=_source(True),
    )
    row = result["rows"][0]
    assert row["persisted"] is False
    assert row["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False

    import red_bar_lab.ui.strategy_execution_decision_gate as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
