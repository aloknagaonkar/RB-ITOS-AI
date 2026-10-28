from pathlib import Path

module = Path(
    "backend/market_lab/hilega_execution_port_v1/receipt_review.py"
)
tests = Path("tests/test_hilega_receipt_review_v1.py")

module_text = r'''"""Historical durable-reference review, without ownership or execution authority."""
from contextlib import closing
import json
import sqlite3

from .adapter import Store, Blocked, sha
from .mapping import place_ack


def need(condition, reason):
    if not condition:
        raise Blocked(reason)


def review(store):
    need(type(store) is Store, "EXACT_ADAPTER_STORE_REQUIRED")
    need(
        store.mode in {"LIVE_CLOSED", "OFFLINE_FIXTURE"},
        "ADAPTER_MODE_INVALID",
    )
    path = store.path
    need(path.is_file() and not path.is_symlink(), "REGULAR_DATABASE_REQUIRED")

    # One read-only SQLite snapshot for all local reference checks.
    with closing(sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10,
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        meta = db.execute("SELECT data FROM meta WHERE id=1").fetchone()
        need(
            meta is not None and json.loads(meta[0]) == {
                "scope": store.scope, "mode": store.mode,
            },
            "ADAPTER_SCOPE_OR_MODE_CHANGED",
        )
        requests = db.execute(
            "SELECT id,fingerprint,data FROM requests ORDER BY rowid"
        ).fetchall()
        attempts = db.execute(
            "SELECT id,request_id,operation,data FROM attempts"
        ).fetchall()
        receipts = dict(db.execute("SELECT id,data FROM receipts").fetchall())
        db.rollback()

    try:
        return _check(store.mode, requests, attempts, receipts)
    except Blocked:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Blocked("DURABLE_REFERENCE_SCHEMA_INVALID") from None


def _check(mode, requests, attempts, receipts):
    request_ids = {row[0] for row in requests}
    attempt_ids = {row[0] for row in attempts}
    need(
        all(row[1] in request_ids for row in attempts)
        and set(receipts) <= attempt_ids,
        "ORPHAN_ATTEMPT_OR_RECEIPT",
    )

    links, seen, unbound = [], set(), 0
    for request_id, fingerprint, raw in requests:
        request = json.loads(raw)
        need(request["request_id"] == request_id, "REQUEST_ID_MISMATCH")
        if request.get("order_id") is None:
            # Even a persisted receipt cannot silently adopt an order here.
            # Existing adapter recovery must perform the binding.
            unbound += 1
            continue

        plan = {
            key: request[key] for key in (
                "request_id", "draft", "signal_id", "signal_at",
                "direction", "reservation_reference",
            )
        }
        need(sha(plan) == fingerprint, "REQUEST_FINGERPRINT_MISMATCH")
        draft = request["draft"]
        body = draft["body"]
        need(sha(body) == draft["fingerprint"], "BODY_FINGERPRINT_MISMATCH")
        need(draft["request_id"] == request_id, "DRAFT_REQUEST_ID_MISMATCH")
        need(
            (draft["documented_method"], draft["documented_host"],
             draft["documented_path"]) ==
            ("POST", "api-hft.upstox.com", "/v3/order/place"),
            "PLACE_ENDPOINT_MISMATCH",
        )
        need(
            all(draft[key] is False for key in (
                "submission_enabled", "entry_permission", "orders_sent",
            )),
            "DISABLED_DRAFT_REQUIRED",
        )

        places = [
            row for row in attempts
            if row[1] == request_id and row[2] == "PLACE"
        ]
        need(len(places) == 1, "EXACTLY_ONE_PLACE_ATTEMPT_REQUIRED")
        attempt_id, _, _, raw_attempt = places[0]
        attempt = json.loads(raw_attempt)
        need(
            attempt["attempt_id"] == attempt_id
            and attempt["request_id"] == request_id
            and attempt["operation"] == "PLACE",
            "ATTEMPT_IDENTITY_MISMATCH",
        )
        expected_wire = dict(
            method="POST", host="api-hft.upstox.com",
            path="/v3/order/place", body=body,
        )
        need(attempt["wire"] == expected_wire, "ATTEMPT_WIRE_MISMATCH")
        need(attempt_id in receipts, "DURABLE_PLACE_RECEIPT_REQUIRED")
        receipt = json.loads(receipts[attempt_id])
        expected_origin = (
            "EXPLICIT_FIXTURE_TRANSPORT"
            if mode == "OFFLINE_FIXTURE" else "LOCAL_HTTP_TRANSPORT"
        )
        need(
            receipt["origin"] == expected_origin
            and receipt["attempt_id"] == attempt_id
            and receipt["wire_fingerprint"] == sha(expected_wire),
            "RECEIPT_PROVENANCE_MISMATCH",
        )
        need(
            type(receipt["http_status"]) is int
            and receipt["http_status"] == 200,
            "SUCCESSFUL_PLACE_RECEIPT_REQUIRED",
        )
        acknowledgement = place_ack(receipt["body"])
        need(
            acknowledgement["status"] == "ACKNOWLEDGED_NOT_FILLED"
            and acknowledgement["order_id"] == request["order_id"],
            "ACK_ORDER_BINDING_MISMATCH",
        )
        need(request["order_id"] not in seen, "ORDER_ID_BOUND_TWICE")
        seen.add(request["order_id"])
        links.append(dict(
            request_id=request_id, order_id=request["order_id"],
            signal_id=request["signal_id"],
            reservation_reference=request["reservation_reference"],
            body_fingerprint=draft["fingerprint"],
            instrument=body["instrument_token"], product=body["product"],
            side=body["transaction_type"], quantity=body["quantity"],
        ))

    status = (
        "UNBOUND_REQUESTS_REQUIRE_RECONCILIATION" if unbound else
        "DURABLE_ACKNOWLEDGEMENT_REFERENCES_CHECKED" if links else
        "NO_BOUND_ACKNOWLEDGEMENTS"
    )
    return dict(
        model="HILEGA_DURABLE_RECEIPT_REVIEW_V1",
        status=status, adapter_mode=mode,
        bindings=links, unbound_request_count=unbound,
        historical_references_only=True,
        current_fills_assessed=False,
        application_hold_link_verified=False,
        strategy_ownership_verified=False,
        real_funds_reservation_verified=False,
        reservation_release_permission=False,
        entry_permission=False, production_execution_enabled=False,
        production_ready=False, orders_sent=False,
    )
'''

test_text = r'''import json
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
'''

for path, content in ((module, module_text), (tests, test_text)):
    if not path.parent.is_dir():
        raise SystemExit("STOP: parent directory missing: " + str(path.parent))
    if path.exists() or path.is_symlink():
        raise SystemExit("STOP: file already exists: " + str(path))
    compile(content, str(path), "exec")

for path, content in ((module, module_text), (tests, test_text)):
    with path.open("x") as stream:
        stream.write(content)
    print("Created:", path)

print("Syntax checked. Tests not executed. No activation performed.")