from __future__ import annotations

from red_bar_lab.ui.strategy_execution_committee import build_execution_committee


def ready_row(candidate_id="C-1"):
    return {
        "candidate_id": candidate_id,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "B-1",
        "signal_id": "S-1",
        "role": "ENTRY_1",
        "instrument_token": "12345",
        "instrument_key": "NFO|12345",
        "contract_exposure_key": "NFO|12345",
        "contract_identity_confidence": "VERIFIED_EXCHANGE_TOKEN",
        "trading_symbol": "NIFTY26AUG25000CE",
        "exchange": "NFO",
        "expiry": "2026-08-27",
        "strike": 25000.0,
        "lot_size": 75,
        "tick_size": 0.05,
        "ltp": 100.0,
        "opportunity_outcome": "PASS",
        "opportunity": {"entry_premium": 100.0, "initial_option_stop": 97.0},
        "quantity": 75,
        "required_capital": 7500.0,
        "total_proposed_risk": 277.5,
        "reservation_outcome": "PROPOSED_READ_ONLY",
        "final_admission_decision": "ADMISSION_READY_READ_ONLY",
        "final_admission_reason": "ALL_ACCOUNT_ADMISSION_CHECKS_PASSED",
        "broker_ready": True,
        "account_ready": True,
        "kill_switch": False,
        "execution_source_enabled": True,
        "admission_priority_rank": 1,
    }


def test_ready_candidate_requires_unanimous_committee_pass():
    result = build_execution_committee({"rows": [ready_row()]})
    row = result["rows"][0]
    assert row["committee_outcome"] == "COMMITTEE_READY_READ_ONLY"
    assert row["order_preparation_allowed"] is True
    assert all(check["status"] == "PASS" for check in row["committee_checks"])


def test_non_admitted_candidate_does_not_reach_committee_ready():
    row = ready_row()
    row["final_admission_decision"] = "WAIT_FOR_CAPITAL"
    row["final_admission_reason"] = "WAIT_FOR_CAPITAL"
    result = build_execution_committee({"rows": [row]})["rows"][0]
    assert result["committee_outcome"] == "WAIT"
    assert "SECTION_8D_NOT_ADMISSION_READY" in result["committee_reason"]


def test_section_8_rejection_is_committee_blocked():
    row = ready_row()
    row["final_admission_decision"] = "REJECT_KILL_SWITCH"
    row["final_admission_reason"] = "EMERGENCY_KILL_SWITCH_ACTIVE"
    result = build_execution_committee({"rows": [row]})["rows"][0]
    assert result["committee_outcome"] == "COMMITTEE_BLOCKED_READ_ONLY"


def test_missing_contract_metadata_waits():
    row = ready_row()
    row["tick_size"] = None
    result = build_execution_committee({"rows": [row]})["rows"][0]
    assert result["committee_outcome"] == "WAIT"
    assert "EXECUTION_CONTRACT_METADATA_INCOMPLETE" in result["committee_reason"]


def test_invalid_stop_waits():
    row = ready_row()
    row["opportunity"]["initial_option_stop"] = 101.0
    result = build_execution_committee({"rows": [row]})["rows"][0]
    assert result["committee_outcome"] == "WAIT"
    assert "OPPORTUNITY_OR_STOP_NOT_READY" in result["committee_reason"]


def test_execution_readiness_must_remain_confirmed():
    row = ready_row()
    row["broker_ready"] = False
    result = build_execution_committee({"rows": [row]})["rows"][0]
    assert result["committee_outcome"] == "WAIT"
    assert "EXECUTION_READINESS_NOT_CONFIRMED" in result["committee_reason"]


def test_committee_is_read_only_and_deterministic():
    first = build_execution_committee({"rows": [ready_row()]})["rows"][0]
    second = build_execution_committee({"rows": [ready_row()]})["rows"][0]
    assert first["committee_id"] == second["committee_id"]
    assert first["order_created"] is False
    assert first["order_submitted"] is False
    assert first["persisted"] is False
    assert first["reserved"] is False
    assert first["bundle_consumed"] is False
    assert first["submitted"] is False
