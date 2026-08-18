from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.strategy_live_activation_readiness import (
    build_live_activation_readiness,
)


def ready_row() -> dict[str, object]:
    return {
        "shadow_rehearsal_id": "SHADOW-1",
        "adapter_mapping_validation_id": "MAPVAL-1",
        "broker_payload_preview_id": "PAYLOAD-1",
        "order_specification_id": "ORDSPEC-1",
        "committee_id": "COM-1",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "candidate_id": "RSI-CAND-1",
        "entry_client_order_id": "PAYLOAD-1-ENTRY",
        "protective_client_order_id": "PAYLOAD-1-STOP",
        "payload_fingerprint_sha256": "ABC123",
        "shadow_rehearsal_outcome": "SHADOW_HANDOFF_READY_DISABLED",
        "shadow_handoff_ready": True,
        "live_activation_allowed": False,
        "submission_enabled": False,
        "broker_client_attached": False,
        "credentials_attached": False,
        "transport_attached": False,
        "broker_payload_created": False,
        "order_created": False,
        "order_submitted": False,
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def build(row: dict[str, object] | None = None):
    return build_live_activation_readiness({"rows": [row or ready_row()]})


def test_shadow_ready_is_still_blocked_from_live_activation():
    result = build()
    row = result["rows"][0]
    assert result["outcome"] == "LIVE_ACTIVATION_BLOCKED_READ_ONLY"
    assert row["shadow_validation_complete"] is True
    assert row["live_activation_allowed"] is False
    assert row["activation_requirement_count"] == 12
    assert row["activation_available_count"] == 3
    assert row["activation_missing_count"] == 9


def test_missing_production_requirements_are_explicit():
    row = build()["rows"][0]
    missing = set(row["activation_missing_requirements"])
    assert "Durable idempotency registry" in missing
    assert "Atomic capital and risk reservation" in missing
    assert "Broker credential provider" in missing
    assert "Broker transport adapter" in missing
    assert "Order acknowledgement reconciliation" in missing
    assert "Protective-order recovery" in missing
    assert "Operator approval record" in missing
    assert "Kill-switch integration test" in missing
    assert "Production activation configuration" in missing


def test_attached_live_dependency_breaks_shadow_validation():
    row = ready_row()
    row["transport_attached"] = True
    audited = build(row)["rows"][0]
    assert audited["shadow_validation_complete"] is False
    boundary = next(
        item for item in audited["activation_requirements"]
        if item["requirement"] == "Disabled boundary intact"
    )
    assert boundary["available"] is False


def test_incomplete_lineage_is_reported_without_fabrication():
    row = ready_row()
    row["signal_id"] = None
    audited = build(row)["rows"][0]
    assert audited["shadow_validation_complete"] is False
    lineage = next(
        item for item in audited["activation_requirements"]
        if item["requirement"] == "Execution lineage complete"
    )
    assert lineage["status"] == "NOT_IMPLEMENTED"


def test_audit_id_is_deterministic():
    first = build()["rows"][0]
    second = build()["rows"][0]
    assert first["live_activation_audit_id"] == second["live_activation_audit_id"]


def test_input_is_not_mutated_and_no_execution_flag_is_enabled():
    source = {"rows": [ready_row()]}
    original = deepcopy(source)
    result = build_live_activation_readiness(source)
    assert source == original
    row = result["rows"][0]
    for field in (
        "live_activation_allowed", "submission_enabled", "broker_client_attached",
        "credentials_attached", "transport_attached", "broker_payload_created",
        "order_created", "order_submitted", "persisted", "reserved",
        "bundle_consumed", "submitted", "production_approval_recorded",
    ):
        assert row[field] is False
