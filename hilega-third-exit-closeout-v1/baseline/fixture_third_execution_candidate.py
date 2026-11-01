"""Dedicated third-entry fixture authorization. Never live execution."""
from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3

from fixture_execution_authorization import issue, claim
from third_entry_preparation_candidate import market_plan, TABLE as ADMISSIONS
from third_entry_cash_candidate import review_repeat_entry
from third_entry_history_candidate import load_closed_history
from fixture_reference_retirement_candidate import ACTIVE
from market_lab.hilega_preparation_runtime_v1.ownership_state import (
    SourceReader, rollback_database,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_connection
from market_lab.hilega_preparation_runtime_v1.ownership_checks.reservation_checks import verify_row
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check, sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign, aware
from market_lab.hilega_execution_port_v1.adapter import validated_request

ADAPTER_SHA = "82c7606a4c4aad8b540b59db35766a736982dac18e9501f26179d9e8fe24b4a4"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def preparation_proof(app, source, pin, key):
    found = app.execute(
        "SELECT data FROM "+ADMISSIONS+" WHERE id=?", (key,)
    ).fetchone()
    need(found is not None, "REPEAT_PREPARATION_PROOF_REQUIRED")
    proof = json.loads(found[0])
    payload = dict(proof)
    signed = payload.pop("signature", None)
    need(isinstance(signed, str)
         and hmac.compare_digest(sign(payload, pin), signed)
         and proof.get("production_execution_enabled") is False,
         "REPEAT_PREPARATION_SIGNATURE_INVALID")
    need(proof["event"]["id"] == key
         and proof["event"]["role"] == "ENTRY",
         "REPEAT_SIGNAL_BINDING_MISMATCH")
    for table, category in ACTIVE.items():
        need(set(source[category]) == {key},
             "SINGLE_REPEAT_REFERENCE_REQUIRED")
        need(sha(source[category][key])
             == proof["active_fingerprints"][table],
             "REPEAT_ACTIVE_REFERENCE_CHANGED")
    need(source["bindings"][key]["model"]
         == "HILEGA_FIXTURE_THIRD_DISABLED_BINDING_V1",
         "DEDICATED_REPEAT_BINDING_REQUIRED")
    archives = load_closed_history(app, pin)
    need(sorted(sha(row) for row in archives)
         == sorted(proof["closed_history_fingerprints"]),
         "CLOSED_HISTORY_CHANGED_AFTER_PREPARATION")
    return proof, archives



def repeat_context(app, source, pin, key, captures, as_of):
    proof, archives = preparation_proof(app, source, pin, key)
    need(source["mode"] == "OFFLINE_FIXTURE"
         and source["scope"] == pin["scope"]
         and source["control"].get("mode") == "PAUSED"
         and source["control"].get("production_execution_enabled") is False,
         "PAUSED_FIXTURE_CONTEXT_REQUIRED")
    stop = source["stop_state"]
    need(isinstance(stop, list) and len(stop) == 2
         and all(type(v) is int and v >= 0 for v in stop)
         and stop[0] == stop[1], "STOP_RECONCILIATION_REQUIRED")
    need(not any(source["counts"][name] for name in (
        "intents", "sim_orders", "sim_fills", "sim_allocation_reservations",
    )), "SIMULATOR_ACTIVITY_PRESENT")
    requests = {
        rid: (fp, json.loads(raw))
        for rid, fp, raw in source["requests"]
    }
    need(len(requests) == len(source["requests"]),
         "DUPLICATE_REQUEST_ID")
    expected_requests, expected_attempts, expected_receipts = {}, {}, {}
    for archived in archives:
        previous = archived["source"]
        for rid, fp, raw in previous["requests"]:
            need(rid not in expected_requests, "DUPLICATE_ARCHIVED_REQUEST")
            expected_requests[rid] = fp
        for aid, rid, operation, raw in previous["attempts"]:
            need(aid not in expected_attempts, "DUPLICATE_ARCHIVED_ATTEMPT")
            saved = json.loads(raw)
            expected_attempts[aid] = (rid, operation, sha(saved["wire"]))
        for aid, raw in previous["receipts"].items():
            need(aid not in expected_receipts, "DUPLICATE_ARCHIVED_RECEIPT")
            expected_receipts[aid] = sha(json.loads(raw))
    need(set(requests) == set(expected_requests) | {key}
         and key not in expected_requests,
         "UNATTRIBUTED_ADAPTER_REQUEST")
    for rid, fp in expected_requests.items():
        need(requests[rid][0] == fp
             and requests[rid][1]["state"] not in {
                 "UNKNOWN", "IN_FLIGHT", "CANCEL_IN_FLIGHT",
                 "CANCEL_OUTCOME_UNKNOWN",
             }, "HISTORICAL_REQUEST_CHANGED_OR_UNRESOLVED")
    current_attempts = {}
    for aid, rid, operation, raw in source["attempts"]:
        saved = json.loads(raw)
        need(saved["attempt_id"] == aid
             and saved["request_id"] == rid
             and saved["operation"] == operation
             and saved["state"] not in {
                 "UNKNOWN", "IN_FLIGHT", "CANCEL_OUTCOME_UNKNOWN",
             }, "HISTORICAL_ATTEMPT_UNRESOLVED")
        need(aid not in current_attempts, "DUPLICATE_ATTEMPT_ID")
        current_attempts[aid] = (rid, operation, sha(saved["wire"]))
    need(current_attempts == expected_attempts,
         "UNATTRIBUTED_OR_CHANGED_TRANSPORT_ATTEMPT")
    need({
        aid: sha(json.loads(raw))
        for aid, raw in source["receipts"].items()
    } == expected_receipts, "HISTORICAL_RECEIPT_CHANGED")
    historical = _check(
        "OFFLINE_FIXTURE", source["requests"],
        source["attempts"], source["receipts"])
    need(historical["unbound_request_count"] == 1
         and key in requests
         and requests[key][1]["state"] == "PREPARED"
         and requests[key][1].get("order_id") is None,
         "EXACT_UNSUBMITTED_REPEAT_REQUEST_REQUIRED")


    fp, request = requests[key]
    now = aware(as_of)
    need(0 <= (now-aware(request["draft"]["created_at"])).total_seconds() <= 10,
         "REPEAT_REQUEST_STALE_OR_FUTURE")
    plan = source["plans"][key]
    reservation = source["cash_reservations"][key]
    verify_row(reservation, pin)
    need(reservation["state"] == "RESERVED_DISABLED_REQUEST"
         and reservation["request_fingerprint"] == fp
         and fp == source["bindings"][key]["request_fingerprint"]
             == proof["request_fingerprint"]
         and reservation["plan_fingerprint"] == sha(plan)
         and reservation["shadow_hold_fingerprint"] == sha(source["holds"][key])
         and reservation["outbox_fingerprint"] == sha(source["outbox"][key]),
         "REPEAT_RESERVATION_BINDING_CHANGED")
    event = proof["event"]
    need(request["signal_id"] == key
         and request["signal_at"] == event["event_at"] == plan["signal_at"]
         and request["direction"] == event["direction"] == plan["direction"]
         and request["reservation_reference"] == key,
         "REPEAT_REQUEST_SIGNAL_CHANGED")
    contract, quantity, pricing = market_plan(
        captures["market"], pin, event["direction"], now)
    need(contract == plan["evidence"]["contract"]
         and quantity == plan["quantity"],
         "CURRENT_REPEAT_CONTRACT_CHANGED")
    candidate = source["outbox"][key]["disabled_request_candidate"]
    from decimal import Decimal
    numerator, denominator = Decimal(
        pricing["observed_ask"]).as_integer_ratio()
    premium, remainder = divmod(numerator*quantity*100, denominator)
    need(remainder == 0, "EXACT_PAISE_PREMIUM_REQUIRED")
    cash = review_repeat_entry(
        captures["account"], captures["cash"], archives, pin,
        signal_at=event["event_at"], premium_paise=premium,
        fee_buffer_paise=candidate["fee_buffer_cents"], as_of=as_of)
    need(cash["status"] == "REENTRY_REFERENCE_CHECKS_PASS",
         "CURRENT_REPEAT_CASH_BLOCKED")
    need(premium == candidate["premium_cents"]
         and premium+candidate["fee_buffer_cents"]
             == candidate["budget_cents"]
             == reservation["held_cents"]
             == source["holds"][key]["held_cents"]
         and reservation["held_cents"] <= cash["half_cash_budget_paise"],
         "REPEAT_BUDGET_CHANGED_OR_EXCEEDS_CURRENT_CASH")
    body = request["draft"]["body"]
    need(body["transaction_type"] == "BUY"
         and body["order_type"] == "LIMIT"
         and body["instrument_token"] == contract["instrument_key"]
         and body["quantity"] == quantity
         and Decimal(str(body["price"])) == Decimal(pricing["observed_ask"]),
         "CURRENT_REPEAT_WIRE_MISMATCH")
    validated, validated_fp = validated_request(
        request["draft"], signal_id=key, signal_at=request["signal_at"],
        direction=request["direction"], reservation_reference=key, as_of=as_of)
    need(validated_fp == fp, "REPEAT_REQUEST_FINGERPRINT_CHANGED")
    from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import day
    need(entry_clock_open(now)
         and entry_clock_open(aware(event["event_at"]))
         and source["control"]["session_date"] == day(now),
         "REPEAT_ENTRY_CLOCK_OR_SESSION_CLOSED")
    wire = dict(
        method="POST", host="api-hft.upstox.com",
        path="/v3/order/place", body=body)
    return dict(
        context_fingerprint=sha(dict(source=source, captures=captures)),
        request_fingerprint=fp, wire=wire,
        budget_paise=reservation["held_cents"],
        fee_buffer_paise=candidate["fee_buffer_cents"])



def execute_third_fixture(
    application_store, execution_store, pin, *,
    adapter_module, request_id, capture_provider, clock,
    timeout_after=False, checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_THIRD_EXECUTION_ONLY")
    path = Path(adapter_module.__file__)
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest() == ADAPTER_SHA,
         "PINNED_FIXTURE_ADAPTER_REQUIRED")
    need(type(execution_store) is adapter_module.Store
         and execution_store.mode == "OFFLINE_FIXTURE"
         and execution_store.scope == pin["scope"],
         "EXACT_FIXTURE_EXECUTION_STORE_REQUIRED")
    app_path = rollback_database(application_store.path)
    broker_path = rollback_database(execution_store.path)
    need(not app_path.samefile(broker_path), "DISTINCT_DATABASES_REQUIRED")
    transport = adapter_module.FixtureTransport(execution_store)
    adapter = adapter_module.Adapter(execution_store, transport)
    with application_store.lock():
        with closing(sqlite3.connect(
            app_path.as_uri()+"?mode=ro", uri=True, timeout=10,
        )) as app:
            app.execute("PRAGMA query_only=ON")
            app.execute("BEGIN")
            try:
                with execution_store.tx() as db:
                    source = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="OFFLINE_FIXTURE")
                    found = db.execute(
                        "SELECT fingerprint,data FROM requests WHERE id=?",
                        (request_id,),
                    ).fetchone()
                    attempts = db.execute(
                        "SELECT id,request_id,operation,data FROM attempts "
                        "WHERE request_id=?", (request_id,),
                    ).fetchall()
                preparation_proof(app, source, pin, request_id)
                need(found is not None, "REPEAT_REQUEST_REQUIRED")
                fp, raw = found
                row = json.loads(raw)
                stable = {key: row[key] for key in (
                    "request_id", "draft", "signal_id", "signal_at",
                    "direction", "reservation_reference",
                )}
                need(sha(stable) == fp
                     == source["bindings"][request_id]["request_fingerprint"],
                     "REPEAT_REQUEST_FINGERPRINT_CHANGED")
                wire = adapter._wire(row, "PLACE")
                if attempts:
                    need(len(attempts) == 1, "SINGLE_REPEAT_ATTEMPT_REQUIRED")
                    aid, rid, operation, raw_attempt = attempts[0]
                    saved = json.loads(raw_attempt)
                    need(saved["attempt_id"] == aid
                         and saved["request_id"] == rid == request_id
                         and saved["operation"] == operation == "PLACE"
                         and saved["wire"] == wire,
                         "REPEAT_RECOVERY_BINDING_MISMATCH")
                    adapter.recover()
                    return dict(
                        status="EXISTING_THIRD_ENTRY_RECOVERED_NO_SUBMISSION",
                        recovery_only=True, new_attempt_created=False,
                        production_execution_enabled=False)


                captures = capture_provider()
                need(isinstance(captures, dict)
                     and set(captures) == {"account", "cash", "market"},
                     "EXACT_REPEAT_CAPTURE_SET_REQUIRED")
                at = clock()
                checked = repeat_context(
                    app, source, pin, request_id, captures, at.isoformat())
                need(checked["wire"] == wire,
                     "REPEAT_WIRE_CHANGED_BEFORE_AUTHORIZATION")
                grant = issue(
                    pin, request_id=request_id, wire=wire,
                    budget_paise=checked["budget_paise"],
                    fee_buffer_paise=checked["fee_buffer_paise"],
                    at=at.isoformat())

                def authorize(db, attempt):
                    current = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="OFFLINE_FIXTURE")
                    final_at = clock()
                    final = repeat_context(
                        app, current, pin, request_id,
                        captures, final_at.isoformat())
                    need(final["context_fingerprint"]
                         == checked["context_fingerprint"]
                         and attempt["operation"] == "PLACE"
                         and attempt["wire"] == final["wire"],
                         "REPEAT_CONTEXT_CHANGED_BEFORE_ATTEMPT")
                    claim(
                        db, grant, pin, request_id=request_id,
                        wire=attempt["wire"], at=final_at.isoformat(),
                        attempt_id=attempt["attempt_id"])
                    checkpoint("AFTER_THIRD_AUTHORIZATION_CLAIM")

                adapter.fixture_authorization_claim = authorize
                transport.timeout_after = timeout_after
                result = adapter.submit(request_id)
                return dict(
                    status="THIRD_ENTRY_ATTEMPT_RECORDED",
                    adapter_result=result,
                    recovery_only=False,
                    new_attempt_created=not result.get("idempotent_replay", False),
                    orders_sent_to_upstox=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False)
            finally:
                app.rollback()

