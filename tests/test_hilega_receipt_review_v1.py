import json
import pytest

from market_lab.hilega_execution_port_v1.adapter import (
    Adapter, Store, FixtureTransport, Blocked,
)
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_execution_port_v1.receipt_review import review

AT = "2026-10-26T09:25:00+05:30"


@pytest.fixture
def prepared(tmp_path):
    store = Store(tmp_path / "adapter.sqlite", "TEST_SCOPE", "OFFLINE_FIXTURE")
    transport = FixtureTransport(store)
    adapter = Adapter(store, transport)
    contract = dict(
        instrument_key="NSE_FO|12345", underlying_key="NSE_INDEX|Nifty 50",
        instrument_type="CE", segment="NSE_FO", expiry="2026-10-27",
        lot_size=65, minimum_lot=65, freeze_quantity=1800,
    )
    request = draft(
        contract, request_id="entry", side="BUY", lots=1, as_of=AT,
    )
    adapter.prepare(
        request, signal_id="signal", signal_at=AT, direction="BULLISH",
        reservation_reference="hold-reference", as_of=AT,
    )
    return adapter, transport


def dump(store):
    with store.tx() as db:
        return list(db.iterdump())


def test_receipt_links_reference_without_granting_authority(prepared):
    adapter, _ = prepared
    adapter.submit("entry")
    before = dump(adapter.store)
    result = review(adapter.store)
    assert result["status"] == "DURABLE_ACKNOWLEDGEMENT_REFERENCES_CHECKED"
    assert len(result["bindings"]) == 1
    binding = result["bindings"][0]
    assert binding["request_id"] == "entry"
    assert binding["reservation_reference"] == "hold-reference"
    assert binding["quantity"] == 65
    for key in (
        "application_hold_link_verified", "strategy_ownership_verified",
        "real_funds_reservation_verified", "reservation_release_permission",
        "entry_permission", "production_execution_enabled", "production_ready",
        "orders_sent", "current_fills_assessed",
    ):
        assert result[key] is False
    assert dump(adapter.store) == before


def test_unsent_request_remains_unbound(prepared):
    adapter, _ = prepared
    result = review(adapter.store)
    assert result["unbound_request_count"] == 1
    assert result["bindings"] == []


def test_lost_response_does_not_adopt_fixture_order(prepared):
    adapter, transport = prepared
    transport.timeout_after = True
    adapter.submit("entry")
    assert len(transport.orders()) == 1
    before = dump(adapter.store)
    assert review(adapter.store)["bindings"] == []
    assert adapter.store.requests()[0]["order_id"] is None
    assert dump(adapter.store) == before


def test_review_does_not_replace_existing_recovery(prepared):
    adapter, _ = prepared

    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == "AFTER_RECEIPT_COMMIT":
            raise Interrupted()

    adapter.checkpoint = checkpoint
    with pytest.raises(Interrupted):
        adapter.submit("entry")
    assert review(adapter.store)["bindings"] == []
    assert adapter.store.requests()[0]["order_id"] is None
    adapter.recover()
    assert len(review(adapter.store)["bindings"]) == 1


@pytest.mark.parametrize("case", [
    "missing_receipt", "origin", "wire_hash", "ack_order", "http_status",
    "attempt_wire", "reservation_reference", "request_fingerprint",
])
def test_changed_persisted_chain_is_rejected(prepared, case):
    adapter, _ = prepared
    adapter.submit("entry")
    with adapter.store.tx() as db:
        if case == "missing_receipt":
            db.execute("DELETE FROM receipts")
        elif case == "request_fingerprint":
            db.execute("UPDATE requests SET fingerprint='changed'")
        elif case == "reservation_reference":
            row = json.loads(db.execute(
                "SELECT data FROM requests WHERE id='entry'"
            ).fetchone()[0])
            row["reservation_reference"] = "another-hold"
            db.execute(
                "UPDATE requests SET data=? WHERE id='entry'",
                (json.dumps(row),),
            )
        elif case == "attempt_wire":
            key, raw = db.execute("SELECT id,data FROM attempts").fetchone()
            row = json.loads(raw)
            row["wire"]["body"]["quantity"] = 130
            db.execute(
                "UPDATE attempts SET data=? WHERE id=?",
                (json.dumps(row), key),
            )
        else:
            key, raw = db.execute("SELECT id,data FROM receipts").fetchone()
            row = json.loads(raw)
            if case == "origin":
                row["origin"] = "LOCAL_HTTP_TRANSPORT"
            elif case == "wire_hash":
                row["wire_fingerprint"] = "changed"
            elif case == "ack_order":
                row["body"]["data"]["order_ids"] = ["FIXTURE-OTHER"]
            else:
                row["http_status"] = 500
            db.execute(
                "UPDATE receipts SET data=? WHERE id=?",
                (json.dumps(row), key),
            )
    before = dump(adapter.store)
    with pytest.raises(Blocked):
        review(adapter.store)
    assert dump(adapter.store) == before


def test_empty_live_store_is_not_ownership_proof(tmp_path):
    store = Store(tmp_path / "live.sqlite", "TEST_SCOPE", "LIVE_CLOSED")
    before = dump(store)
    result = review(store)
    assert result["status"] == "NO_BOUND_ACKNOWLEDGEMENTS"
    assert result["strategy_ownership_verified"] is False
    assert dump(store) == before
