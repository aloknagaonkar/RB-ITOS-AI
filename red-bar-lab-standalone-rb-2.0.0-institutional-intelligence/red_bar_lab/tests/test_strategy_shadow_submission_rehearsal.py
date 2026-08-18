from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.strategy_shadow_submission_rehearsal import (
    build_shadow_submission_rehearsal,
)


def ready_row():
    return {
        "adapter_mapping_validation_id": "MAPVAL-1",
        "broker_payload_preview_id": "PAYLOAD-1",
        "order_specification_id": "ORDSPEC-1",
        "committee_id": "COM-1",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "candidate_id": "RSI-CAND-1",
        "broker_adapter": "GENERIC_BROKER_DISABLED",
        "adapter_mapping_outcome": "ADAPTER_MAPPING_VALIDATED_READ_ONLY",
        "entry_client_order_id": "PAYLOAD-1-ENTRY",
        "protective_client_order_id": "PAYLOAD-1-STOP",
        "payload_fingerprint_sha256": "ABC123",
        "fingerprint_matches": True,
        "duplicate_submission_prevented": True,
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
        "payload_preview": {
            "submission_enabled": False,
            "broker_client_attached": False,
            "credentials_attached": False,
        },
    }


def build(row=None):
    return build_shadow_submission_rehearsal({"rows": [row or ready_row()]})


def test_validated_disabled_mapping_reaches_shadow_handoff_ready():
    result = build()
    row = result["rows"][0]
    assert result["outcome"] == "SHADOW_HANDOFF_READY_DISABLED"
    assert row["shadow_rehearsal_outcome"] == "SHADOW_HANDOFF_READY_DISABLED"
    assert row["shadow_handoff_ready"] is True
    assert row["live_activation_allowed"] is False
    assert row["execution_boundary_state"]["submission_available"] is False


def test_attached_live_dependency_blocks_rehearsal():
    row = ready_row()
    row["transport_attached"] = True
    result = build(row)
    assert result["rows"][0]["shadow_rehearsal_outcome"] == "WAIT"
    assert "LIVE_EXECUTION_DEPENDENCY_ATTACHED" in result["rows"][0]["shadow_rehearsal_reason"]


def test_broken_idempotency_blocks_rehearsal():
    row = ready_row()
    row["fingerprint_matches"] = False
    result = build(row)
    assert result["rows"][0]["shadow_rehearsal_outcome"] == "WAIT"
    assert "IDEMPOTENCY_NOT_CONFIRMED" in result["rows"][0]["shadow_rehearsal_reason"]


def test_incomplete_execution_lineage_blocks_rehearsal():
    row = ready_row()
    row["signal_id"] = None
    result = build(row)
    assert "EXECUTION_LINEAGE_INCOMPLETE" in result["rows"][0]["shadow_rehearsal_reason"]


def test_reenabled_payload_blocks_rehearsal():
    row = ready_row()
    row["payload_preview"] = dict(row["payload_preview"])
    row["payload_preview"]["submission_enabled"] = True
    result = build(row)
    assert "PAYLOAD_NO_LONGER_HARD_DISABLED" in result["rows"][0]["shadow_rehearsal_reason"]


def test_rehearsal_id_is_deterministic():
    first = build()["rows"][0]["shadow_rehearsal_id"]
    second = build()["rows"][0]["shadow_rehearsal_id"]
    assert first == second
    assert first.startswith("SHADOW-")


def test_builder_does_not_mutate_input():
    source = {"rows": [ready_row()]}
    before = deepcopy(source)
    build_shadow_submission_rehearsal(source)
    assert source == before


def test_no_side_effect_flags_can_be_enabled_by_ready_result():
    row = build()["rows"][0]
    for field in (
        "live_activation_allowed", "submission_enabled", "broker_client_attached",
        "credentials_attached", "transport_attached", "broker_payload_created",
        "order_created", "order_submitted", "persisted", "reserved",
        "bundle_consumed", "submitted",
    ):
        assert row[field] is False
