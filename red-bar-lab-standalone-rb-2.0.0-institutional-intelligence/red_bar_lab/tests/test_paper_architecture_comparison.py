from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.paper_architecture_comparison import (
    build_paper_architecture_comparison,
)
from red_bar_lab.ui.strategy_shadow_evidence_registry import (
    clear_shadow_evidence_for_tests,
    read_shadow_evidence,
    record_shadow_result,
)


def _order(**overrides):
    row = {
        "order_id": "PAPER-1",
        "status": "CLOSED",
        "execution_strategy_source": "RED_BAR",
        "signal_id": "RB-1",
        "bundle_id": "BUNDLE-1",
        "candidate_id": "CAND-1",
        "tradingsymbol": "NIFTY-CE",
        "entry_timestamp": "2026-08-18T10:05:00+05:30",
    }
    row.update(overrides)
    return row


def _evidence(**overrides):
    row = {
        "strategy_id": "RED_BAR",
        "signal_id": "RB-1",
        "bundle_id": "BUNDLE-1",
        "candidate_id": "CAND-1",
        "trading_symbol": "NIFTY-CE",
        "evaluation_timestamp": "2026-08-18T10:04:30+05:30",
        "new_chain_decision": "ADMIT_READ_ONLY",
        "new_chain_reason": "SHADOW_HANDOFF_READY_DISABLED",
    }
    row.update(overrides)
    return row


def test_time_safe_matching_admission_agrees_with_legacy_execution():
    order = _order()
    evidence = _evidence()
    original_order = deepcopy(order)
    original_evidence = deepcopy(evidence)

    result = build_paper_architecture_comparison([order], [evidence])

    assert order == original_order
    assert evidence == original_evidence
    assert result["counts"]["AGREE_EXECUTE"] == 1
    assert result["comparable_count"] == 1
    assert result["rows"][0]["comparison_category"] == "AGREE_EXECUTE"
    assert result["persisted"] is False
    assert result["execution_allowed"] is False


def test_later_shadow_evidence_is_never_used_for_legacy_trade():
    result = build_paper_architecture_comparison(
        [_order()],
        [_evidence(evaluation_timestamp="2026-08-18T10:05:01+05:30")],
    )

    assert result["counts"]["NOT_COMPARABLE"] == 1
    assert result["counts"]["NEW_ONLY_ADMIT"] == 1
    assert result["comparable_count"] == 0


def test_matched_new_wait_is_legacy_only_execute():
    result = build_paper_architecture_comparison(
        [_order()],
        [_evidence(
            new_chain_decision="REJECT_OR_WAIT_READ_ONLY",
            new_chain_reason="WAIT_FOR_CAPITAL",
        )],
    )

    assert result["counts"]["LEGACY_ONLY_EXECUTE"] == 1
    assert result["rows"][0]["comparison_reason"] == (
        "LEGACY_EXECUTED_BUT_NEW_CHAIN_DID_NOT_ADMIT"
    )


def test_signal_mismatch_is_not_comparable():
    result = build_paper_architecture_comparison(
        [_order()],
        [_evidence(signal_id="RB-OTHER")],
    )

    assert result["counts"]["NOT_COMPARABLE"] == 1
    assert result["counts"]["NEW_ONLY_ADMIT"] == 1


def test_shadow_registry_is_process_local_bounded_read_only_copy():
    clear_shadow_evidence_for_tests()
    result = {
        "rows": [{
            "strategy_id": "RED_BAR",
            "signal_id": "RB-1",
            "bundle_id": "BUNDLE-1",
            "candidate_id": "CAND-1",
            "evaluation_timestamp": "2026-08-18T10:04:30+05:30",
            "shadow_handoff_ready": True,
            "shadow_rehearsal_outcome": "SHADOW_HANDOFF_READY_DISABLED",
        }]
    }

    capture = record_shadow_result(result)
    rows = read_shadow_evidence()
    rows[0]["signal_id"] = "MUTATED"

    assert capture["captured_count"] == 1
    assert capture["persisted"] is False
    assert read_shadow_evidence()[0]["signal_id"] == "RB-1"
    assert read_shadow_evidence()[0]["new_chain_decision"] == "ADMIT_READ_ONLY"
    clear_shadow_evidence_for_tests()
