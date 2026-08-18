from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.strategy_adapter_mapping_validation import (
    build_adapter_mapping_validation,
)
from red_bar_lab.ui.strategy_broker_payload_preview import (
    build_broker_payload_preview,
)


def ready_order_specification() -> dict[str, object]:
    return {
        "rows": [
            {
                "order_specification_id": "ORDSPEC-1",
                "committee_id": "COM-1",
                "strategy_id": "RSI_EXTREME_REVERSAL",
                "bundle_id": "BUNDLE-1",
                "signal_id": "SIGNAL-1",
                "candidate_id": "RSI-CAND-1",
                "role": "ENTRY_1",
                "exchange": "NFO",
                "instrument_token": "12345",
                "instrument_key": "NSE_FO|12345",
                "trading_symbol": "NIFTY26AUG25000CE",
                "order_specification_outcome": "ORDER_SPEC_READY_READ_ONLY",
                "order_prepared_read_only": True,
                "order_quantity": 75,
                "limit_price": 100.05,
                "protective_stop_trigger": 96.0,
            }
        ]
    }


def preview() -> dict[str, object]:
    return build_broker_payload_preview(ready_order_specification())


def test_ready_preview_validates_adapter_mapping_and_idempotency():
    result = build_adapter_mapping_validation(preview())
    row = result["rows"][0]

    assert result["outcome"] == "ADAPTER_MAPPING_VALIDATED_READ_ONLY"
    assert row["adapter_mapping_outcome"] == "ADAPTER_MAPPING_VALIDATED_READ_ONLY"
    assert row["fingerprint_matches"] is True
    assert row["duplicate_submission_prevented"] is True
    assert row["protective_parent_order_id"] == row["entry_client_order_id"]
    assert row["submission_enabled"] is False
    assert row["persisted"] is False
    assert row["order_submitted"] is False


def test_validation_id_is_deterministic():
    first = build_adapter_mapping_validation(preview())["rows"][0]
    second = build_adapter_mapping_validation(preview())["rows"][0]

    assert first["adapter_mapping_validation_id"] == second["adapter_mapping_validation_id"]
    assert first["recomputed_payload_fingerprint_sha256"] == second["recomputed_payload_fingerprint_sha256"]


def test_fingerprint_mismatch_waits():
    source = preview()
    source["rows"][0]["payload_fingerprint_sha256"] = "BAD-FINGERPRINT"

    row = build_adapter_mapping_validation(source)["rows"][0]

    assert row["adapter_mapping_outcome"] == "WAIT"
    assert "PAYLOAD_FINGERPRINT_MISMATCH" in row["adapter_mapping_reason"]
    assert row["fingerprint_matches"] is False


def test_parent_link_mismatch_waits():
    source = preview()
    source["rows"][0]["payload_preview"]["protective_stop_order"]["parent_preview_order_id"] = "WRONG"

    row = build_adapter_mapping_validation(source)["rows"][0]

    assert row["adapter_mapping_outcome"] == "WAIT"
    assert "PROTECTIVE_PARENT_LINK_INVALID" in row["adapter_mapping_reason"]


def test_entry_stop_identity_mismatch_waits():
    source = preview()
    source["rows"][0]["payload_preview"]["protective_stop_order"]["trading_symbol"] = "OTHER"

    row = build_adapter_mapping_validation(source)["rows"][0]

    assert row["adapter_mapping_outcome"] == "WAIT"
    assert "ENTRY_STOP_INSTRUMENT_MAPPING_MISMATCH" in row["adapter_mapping_reason"]


def test_submission_enable_attempt_waits():
    source = preview()
    source["rows"][0]["payload_preview"]["entry_order"]["submission_enabled"] = True

    row = build_adapter_mapping_validation(source)["rows"][0]

    assert row["adapter_mapping_outcome"] == "WAIT"
    assert "ADAPTER_MAPPING_NOT_HARD_DISABLED" in row["adapter_mapping_reason"]
    assert row["order_submitted"] is False


def test_validation_does_not_mutate_preview_input():
    source = preview()
    before = deepcopy(source)

    build_adapter_mapping_validation(source)

    assert source == before
