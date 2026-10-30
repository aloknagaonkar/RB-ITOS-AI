"""Authorized synthetic SELL; never production execution permission."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import uuid

from fixture_execution_authorization import (
    aware, claim, need, sha, signature,
)
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, normalized_tick

ADAPTER_SHA = "82c7606a4c4aad8b540b59db35766a736982dac18e9501f26179d9e8fe24b4a4"


def issue_exit(pin, *, request_id, parent_id, event, wire, ownership, at):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_ACCOUNT_REQUIRED")
    now, signal = aware(at), aware(event["event_at"])
    need(event["role"] == "EXIT"
         and event["direction"] == ownership["direction"],
         "EXIT_EVENT_BINDING_MISMATCH")
    need(0 <= (now - signal).total_seconds() <= 60,
         "FRESH_EXIT_EVENT_REQUIRED")
    body = wire["body"]
    quantity = ownership["filled"]
    need(type(quantity) is int and quantity > 0
         and ownership["status"] in {"FILLED", "CANCELLED"},
         "TERMINAL_ENTRY_FILL_REQUIRED")
    need(wire["method"] == "POST"
         and wire["host"] == "api-hft.upstox.com"
         and wire["path"] == "/v3/order/place"
         and body["transaction_type"] == "SELL"
         and body["order_type"] == "LIMIT"
         and type(body["quantity"]) is int
         and body["quantity"] == quantity
         and body["instrument_token"] == ownership["instrument"]
         and body["product"] == ownership["product"],
         "EXIT_WIRE_OWNERSHIP_MISMATCH")
    need(request_id == sha([
        "SYNTHETIC_STRATEGY_EXIT", parent_id, event["id"]
    ]), "EXIT_REQUEST_BINDING_MISMATCH")
    value = dict(
        model="HILEGA_FIXTURE_EXECUTION_AUTHORIZATION_V1",
        purpose="OWNED_QUANTITY_EXIT",
        authorization_id=uuid.uuid4().hex,
        account_scope=pin["scope"],
        request_id=request_id,
        parent_request_id=parent_id,
        event_fingerprint=sha(event),
        ownership_fingerprint=sha(ownership),
        authorized_quantity=quantity,
        wire_fingerprint=sha(wire),
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=10)).isoformat(),
        production_execution_enabled=False,
    )
    value["signature"] = signature(value, pin)
    return value


def claim_exit(db, authorization, pin, *, parent_id, event,
               ownership, request_id, wire, at, attempt_id):
    need(authorization.get("purpose") == "OWNED_QUANTITY_EXIT"
         and authorization.get("parent_request_id") == parent_id
         and authorization.get("event_fingerprint") == sha(event)
         and authorization.get("ownership_fingerprint") == sha(ownership)
         and authorization.get("authorized_quantity") == wire["body"]["quantity"],
         "EXIT_AUTHORIZATION_CONTEXT_CHANGED")
    # Common claim verifies signature, exact wire, expiry and single use.
    return claim(
        db, authorization, pin, request_id=request_id, wire=wire,
        at=at, attempt_id=attempt_id,
    )


def ownership_in_transaction(db, parent_id):
    found = db.execute(
        "SELECT fingerprint,data FROM requests WHERE id=?", (parent_id,)
    ).fetchone()
    need(found is not None, "ENTRY_REQUEST_REQUIRED")
    entry = json.loads(found[1])
    stable = {k: entry[k] for k in (
        "request_id", "draft", "signal_id", "signal_at",
        "direction", "reservation_reference",
    )}
    need(sha(stable) == found[0], "ENTRY_FINGERPRINT_CHANGED")
    body = entry["draft"]["body"]
    need(body["transaction_type"] == "BUY"
         and entry.get("order_id")
         and entry["state"] not in {
             "UNKNOWN", "CANCEL_OUTCOME_UNKNOWN", "CANCEL_IN_FLIGHT",
         }, "ENTRY_OUTCOME_UNRESOLVED")
    row = db.execute(
        "SELECT data FROM fixture_orders WHERE id=?",
        (entry["order_id"],),
    ).fetchone()
    need(row is not None, "ENTRY_ORDER_REQUIRED")
    order = json.loads(row[0])
    filled = order["filled"]
    need(order["side"] == "BUY"
         and order["instrument"] == body["instrument_token"]
         and order["product"] == body["product"]
         and order["quantity"] == body["quantity"],
         "ENTRY_ORDER_IDENTITY_MISMATCH")
    need(type(filled) is int and 0 < filled <= body["quantity"]
         and (
             order["status"] == "CANCELLED"
             or (order["status"] == "FILLED"
                 and filled == body["quantity"])
         ), "TERMINAL_ENTRY_FILL_REQUIRED")
    return entry, dict(
        entry_fingerprint=found[0],
        order_id=entry["order_id"],
        instrument=order["instrument"], product=order["product"],
        requested=order["quantity"], filled=filled,
        status=order["status"], direction=entry["direction"],
    )


def execute_authorized_exit(
    store, pin, *, adapter_module, entry_id, exit_event,
    contract, clock, limit_price="101", timeout_after=False,
):
    path = Path(adapter_module.__file__)
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest() == ADAPTER_SHA,
         "PINNED_STAGED_ADAPTER_REQUIRED")
    need(pin["scope"].startswith("FIXTURE:")
         and type(store) is adapter_module.Store
         and store.mode == "OFFLINE_FIXTURE"
         and store.scope == pin["scope"], "EXACT_FIXTURE_STORE_REQUIRED")
    need(exit_event["role"] == "EXIT", "CONFIRMED_EXIT_EVENT_REQUIRED")
    key = sha(["SYNTHETIC_STRATEGY_EXIT", entry_id, exit_event["id"]])
    transport = adapter_module.FixtureTransport(store)
    adapter = adapter_module.Adapter(store, transport)

    with store.tx() as db:
        entry, ownership = ownership_in_transaction(db, entry_id)
        attempts = db.execute(
            "SELECT id,request_id,operation,data FROM attempts "
            "WHERE request_id=?", (key,),
        ).fetchall()
        other = [
            json.loads(r[0]) for r in
            db.execute("SELECT data FROM requests WHERE id<>?", (key,))
        ]
        need(not any(
            r["draft"]["body"]["transaction_type"] == "SELL"
            for r in other
        ), "OTHER_EXIT_REQUIRES_RECONCILIATION")

        if attempts:
            need(len(attempts) == 1, "SINGLE_EXIT_ATTEMPT_REQUIRED")
            found = db.execute(
                "SELECT fingerprint,data FROM requests WHERE id=?", (key,)
            ).fetchone()
            need(found is not None, "EXIT_REQUEST_REQUIRED")
            saved = json.loads(found[1])
            stable = {k: saved[k] for k in (
                "request_id", "draft", "signal_id", "signal_at",
                "direction", "reservation_reference",
            )}
            body = saved["draft"]["body"]
            attempt = json.loads(attempts[0][3])
            need(sha(stable) == found[0]
                 and sha(body) == saved["draft"]["fingerprint"]
                 and saved["request_id"] == key
                 and saved["signal_id"] == exit_event["id"]
                 and saved["signal_at"] == exit_event["event_at"]
                 and saved["direction"] == ownership["direction"]
                 and saved["reservation_reference"]
                     == entry["reservation_reference"]
                 and body["transaction_type"] == "SELL"
                 and body["quantity"] == ownership["filled"]
                 and body["instrument_token"] == ownership["instrument"]
                 and body["product"] == ownership["product"]
                 and attempt["attempt_id"] == attempts[0][0]
                 and attempt["request_id"] == attempts[0][1] == key
                 and attempt["operation"] == attempts[0][2] == "PLACE"
                 and attempt["wire"] == adapter._wire(saved, "PLACE"),
                 "EXIT_RECOVERY_BINDING_MISMATCH")

    if attempts:
        # Existing attempt inspection deliberately does not require a new grant.
        adapter.recover()
        return dict(
            status="EXISTING_EXIT_RECOVERED_NO_SUBMISSION",
            exit_request_id=key, recovery_only=True,
            new_attempt_created=False, orders_sent_to_upstox=False,
            production_execution_enabled=False,
            reservation_release_permission=False,
        )

    selected = dict(contract)
    for field in ("lot_size", "minimum_lot", "freeze_quantity"):
        value = selected[field]
        need(not isinstance(value, bool) and int(value) == value,
             "INTEGRAL_CONTRACT_QUANTITY_REQUIRED")
        selected[field] = int(value)
    need(selected["instrument_key"] == ownership["instrument"]
         and selected["lot_size"] == ownership["requested"],
         "EXIT_CONTRACT_MISMATCH")
    now = clock()
    request = draft(
        selected, request_id=key, side="SELL", lots=1,
        as_of=exit_event["event_at"], order_type="LIMIT",
        limit_price=limit_price,
        normalized_tick_rupees=normalized_tick(selected, profile=PROFILE),
    )
    request["body"]["quantity"] = ownership["filled"]
    request["fingerprint"] = sha(request["body"])
    wire = dict(
        method="POST", host="api-hft.upstox.com",
        path="/v3/order/place", body=request["body"],
    )
    grant = issue_exit(
        pin, request_id=key, parent_id=entry_id, event=exit_event,
        wire=wire, ownership=ownership, at=now.isoformat(),
    )
    adapter.prepare(
        request, signal_id=exit_event["id"],
        signal_at=exit_event["event_at"],
        direction=exit_event["direction"],
        reservation_reference=entry["reservation_reference"],
        as_of=now.isoformat(),
    )

    def authorize(db, attempt):
        current_entry, current = ownership_in_transaction(db, entry_id)
        need(current == ownership and current_entry == entry,
             "ENTRY_CHANGED_BEFORE_EXIT_ATTEMPT")
        sellers = [
            json.loads(r[0]) for r in db.execute(
                "SELECT data FROM requests WHERE id<>?", (key,))
        ]
        need(not any(
            r["draft"]["body"]["transaction_type"] == "SELL"
            for r in sellers
        ), "OTHER_EXIT_REQUIRES_RECONCILIATION")
        claim_exit(
            db, grant, pin, parent_id=entry_id, event=exit_event,
            ownership=current, request_id=key, wire=attempt["wire"],
            at=clock().isoformat(), attempt_id=attempt["attempt_id"],
        )

    adapter.fixture_authorization_claim = authorize
    transport.timeout_after = timeout_after
    adapter.submit(key)
    return dict(
        status="AUTHORIZED_FIXTURE_EXIT_ATTEMPT_COMMITTED",
        exit_request_id=key, recovery_only=False,
        new_attempt_created=True, orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )
