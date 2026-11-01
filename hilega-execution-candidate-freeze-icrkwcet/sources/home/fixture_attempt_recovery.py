"""Inspect existing fixture attempts without authorizing another submission."""
import json

from market_lab.hilega_execution_port_v1.adapter import (
    Adapter, FixtureTransport, sha,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def recover_existing(execution, event, parent_key, parent_request, parent_fp):
    if event["role"] == "ENTRY":
        key = parent_key
    else:
        need(event["role"] == "EXIT", "EXECUTION_EVENT_ROLE_INVALID")
        key = sha(["SYNTHETIC_STRATEGY_EXIT", parent_key, event["id"]])

    with execution.tx() as db:
        attempts = db.execute(
            "SELECT id,request_id,operation,data FROM attempts "
            "WHERE request_id=?", (key,),
        ).fetchall()
        if not attempts:
            return None
        found = db.execute(
            "SELECT fingerprint,data FROM requests WHERE id=?", (key,)
        ).fetchone()

    need(len(attempts) == 1 and attempts[0][2] == "PLACE",
         "EXISTING_ATTEMPTS_REQUIRE_SEPARATE_RECONCILIATION")
    need(found is not None, "ATTEMPT_REQUEST_MISSING")
    fingerprint, raw = found
    request = json.loads(raw)
    stable = {
        k: request[k] for k in (
            "request_id", "draft", "signal_id", "signal_at",
            "direction", "reservation_reference",
        )
    }
    need(sha(stable) == fingerprint
         and request["request_id"] == key
         and request["signal_id"] == event["id"]
         and request["signal_at"] == event["event_at"]
         and request["direction"] == event["direction"],
         "RECOVERY_EVENT_REQUEST_MISMATCH")
    need(sha(request["draft"]["body"]) == request["draft"]["fingerprint"],
         "RECOVERY_BODY_FINGERPRINT_MISMATCH")
    need(all(request["draft"].get(k) is False for k in (
        "submission_enabled", "entry_permission", "orders_sent",
    )), "DISABLED_DRAFT_REQUIRED")

    if event["role"] == "ENTRY":
        need(fingerprint == parent_fp, "RECOVERY_ENTRY_CHANGED")
    else:
        body = request["draft"]["body"]
        parent = parent_request["draft"]["body"]
        need(
            body["transaction_type"] == "SELL"
            and body["instrument_token"] == parent["instrument_token"]
            and body["product"] == parent["product"]
            and body["quantity"] == parent["quantity"]
            and request["reservation_reference"]
                == parent_request["reservation_reference"],
            "RECOVERY_EXIT_PARENT_MISMATCH",
        )

    attempt_id, request_id, operation, raw_attempt = attempts[0]
    attempt = json.loads(raw_attempt)
    need(
        attempt["attempt_id"] == attempt_id
        and attempt["request_id"] == request_id == key
        and attempt["operation"] == operation == "PLACE"
        and attempt["wire"] == dict(
            method="POST", host="api-hft.upstox.com",
            path="/v3/order/place", body=request["draft"]["body"],
        ),
        "RECOVERY_ATTEMPT_IDENTITY_OR_WIRE_MISMATCH",
    )

    # recover() performs local receipt binding, never submit().
    adapter = Adapter(execution, FixtureTransport(execution))
    status = adapter.recover()
    saved = next(r for r in status["requests"] if r["request_id"] == key)
    return dict(
        status="EXISTING_ATTEMPT_INSPECTED_NO_SUBMISSION",
        request_state=saved["state"],
        recovery_only=True,
        fresh_evidence_revalidated=False,
        new_submission_authorized=False,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )