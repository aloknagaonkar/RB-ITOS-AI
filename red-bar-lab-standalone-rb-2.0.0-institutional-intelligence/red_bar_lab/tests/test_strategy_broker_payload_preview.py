from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.strategy_broker_payload_preview import build_broker_payload_preview


def ready_row(**overrides):
    row = {
        "order_specification_id": "ORDSPEC-1",
        "committee_id": "COM-1",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "B-1",
        "signal_id": "S-1",
        "candidate_id": "C-1",
        "role": "ENTRY_1",
        "exchange": "NFO",
        "instrument_token": "12345",
        "instrument_key": "NSE_FO|12345",
        "trading_symbol": "NIFTY26AUG25000CE",
        "order_quantity": 75,
        "limit_price": 100.05,
        "protective_stop_trigger": 96.0,
        "order_specification_outcome": "ORDER_SPEC_READY_READ_ONLY",
        "order_prepared_read_only": True,
    }
    row.update(overrides)
    return row


def build(row):
    return build_broker_payload_preview({"rows": [row]})


def test_ready_specification_builds_two_disabled_payload_legs():
    result = build(ready_row())
    row = result["rows"][0]
    assert row["broker_payload_preview_outcome"] == "PAYLOAD_PREVIEW_READY_DISABLED"
    assert row["entry_payload_preview"]["transaction_type"] == "BUY"
    assert row["entry_payload_preview"]["order_type"] == "LIMIT"
    assert row["protective_payload_preview"]["transaction_type"] == "SELL"
    assert row["protective_payload_preview"]["activation_condition"] == "AFTER_ENTRY_FILL"
    assert row["submission_enabled"] is False
    assert row["broker_client_attached"] is False
    assert row["order_submitted"] is False


def test_preview_id_and_fingerprint_are_deterministic():
    first = build(ready_row())["rows"][0]
    second = build(ready_row())["rows"][0]
    assert first["broker_payload_preview_id"] == second["broker_payload_preview_id"]
    assert first["payload_fingerprint_sha256"] == second["payload_fingerprint_sha256"]


def test_payload_contains_no_credentials_account_or_endpoint_fields():
    payload = build(ready_row())["rows"][0]["payload_preview"]
    flattened = str(payload).lower()
    for sensitive in ("access_token", "api_key", "api_secret", "account_id", "client_id", "endpoint"):
        assert sensitive not in flattened


def test_unready_order_specification_waits():
    row = build(ready_row(order_specification_outcome="WAIT", order_prepared_read_only=False))["rows"][0]
    assert row["broker_payload_preview_outcome"] == "WAIT"
    assert "ORDER_SPECIFICATION_NOT_READY" in row["broker_payload_preview_reason"]
    assert row["payload_fingerprint_sha256"] is None


def test_missing_broker_identity_waits():
    row = build(ready_row(instrument_token=None, instrument_key=None))["rows"][0]
    assert row["broker_payload_preview_outcome"] == "WAIT"
    assert "BROKER_INSTRUMENT_IDENTITY_INCOMPLETE" in row["broker_payload_preview_reason"]


def test_invalid_protective_stop_waits():
    row = build(ready_row(protective_stop_trigger=100.05))["rows"][0]
    assert row["broker_payload_preview_outcome"] == "WAIT"
    assert "PAYLOAD_PROTECTIVE_STOP_INVALID" in row["broker_payload_preview_reason"]


def test_builder_does_not_mutate_order_specification_input():
    source = {"rows": [ready_row()]}
    before = deepcopy(source)
    build_broker_payload_preview(source)
    assert source == before
