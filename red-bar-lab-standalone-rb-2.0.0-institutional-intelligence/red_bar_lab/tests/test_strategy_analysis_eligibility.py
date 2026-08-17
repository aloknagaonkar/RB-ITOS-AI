from __future__ import annotations

from red_bar_lab.ui.strategy_analysis_eligibility import _enrich_gate


def _gate(**overrides):
    value = {
        "strategy_id": "RED_BAR",
        "strategy_owner": "Red Bar",
        "signal_state": "CONFIRMED",
        "signal_id": "SIG-1",
        "bundle_state": "FRESH",
        "bundle_id": "BUNDLE-1",
        "section3_outcome": "FORWARD",
        "lifecycle_ready": True,
        "normalized_intent": "BUY CE",
        "execution_enabled": False,
        "eligible": False,
        "checks": [
            {"check": "Strategy-owned signal detected", "status": "PASS", "detail": "CONFIRMED"},
            {"check": "Strategy-owned bundle exists", "status": "PASS", "detail": "BUNDLE-1"},
            {"check": "Section 3 lifecycle permits forward", "status": "PASS", "detail": "FORWARD"},
            {"check": "Requested CE/PE side is explicit", "status": "PASS", "detail": "BUY CE"},
            {"check": "Strategy enabled for execution", "status": "BLOCK", "detail": "disabled"},
        ],
    }
    value.update(overrides)
    return value


def test_disabled_execution_keeps_valid_bundle_analysis_eligible():
    result = _enrich_gate(_gate())

    assert result["analysis_eligible"] is True
    assert result["execution_eligible"] is False
    assert result["eligible"] is False
    assert result["final_outcome"] == "OBSERVE_ONLY_CONTRACT_SELECTION"
    assert result["policy_action"] == "OBSERVE_ONLY"
    assert result["analysis_blocking_reason"] == "None"
    assert "disabled" in result["execution_blocking_reason"].lower()
    execution_check = result["checks"][-1]
    assert execution_check["scope"] == "EXECUTION_ONLY"
    assert execution_check["status"] == "BLOCK_EXECUTION_ONLY"


def test_enabled_execution_requires_same_analysis_prerequisites():
    ready = _enrich_gate(_gate(execution_enabled=True, eligible=True))
    invalid = _enrich_gate(
        _gate(execution_enabled=True, lifecycle_ready=False, section3_outcome="HOLD")
    )

    assert ready["analysis_eligible"] is True
    assert ready["execution_eligible"] is True
    assert ready["final_outcome"] == "FORWARD_TO_CONTRACT_SELECTION"
    assert invalid["analysis_eligible"] is False
    assert invalid["execution_eligible"] is False
    assert invalid["final_outcome"] == "BLOCKED"


def test_missing_side_or_bundle_blocks_analysis_even_when_execution_enabled():
    missing_side = _enrich_gate(
        _gate(execution_enabled=True, normalized_intent="OBSERVE / WAIT")
    )
    missing_bundle = _enrich_gate(
        _gate(execution_enabled=True, bundle_id="Not created")
    )

    assert missing_side["analysis_eligible"] is False
    assert missing_bundle["analysis_eligible"] is False


def test_separation_module_is_read_only():
    import red_bar_lab.ui.strategy_analysis_eligibility as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
    assert "update_position" not in source
