"""Durable cancellation evidence + signed lifecycle quantity references."""
import json

from lifecycle_signal_review import review_journal_lifecycle
from market_lab.hilega_execution_port_v1.adapter import cancel_draft, cancel_ack
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import (
    _check, sha,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def review_cancellations(source, snapshot, *, entry_id):
    requests = {key: json.loads(raw)
                for key, fingerprint, raw in source["requests"]}
    need(len(requests) == len(source["requests"]), "DUPLICATE_REQUEST_ID")
    # Retain existing PLACE provenance and orphan checks.
    _check(source["mode"], source["requests"],
           source["attempts"], source["receipts"])
    cancels = [r for r in source["attempts"] if r[2] == "CANCEL"]
    need(all(r[2] in {"PLACE", "CANCEL"} for r in source["attempts"]),
         "UNSUPPORTED_TRANSPORT_OPERATION")
    need(len(cancels) <= 1, "MULTIPLE_CANCELLATIONS_REQUIRE_REVIEW")
    ids = [r[0] for r in source["attempts"]]
    need(len(set(ids)) == len(ids), "DUPLICATE_ATTEMPT_ID")
    references = []
    for attempt_id, request_id, operation, raw in cancels:
        need(request_id == entry_id, "EXIT_CANCEL_POLICY_NOT_IMPLEMENTED")
        request = requests[request_id]
        need(request["draft"]["body"]["transaction_type"] == "BUY",
             "CANCEL_ENTRY_BUY_REQUIRED")
        order_id = request.get("order_id")
        need(order_id is not None, "CANCEL_ACKNOWLEDGED_ENTRY_REQUIRED")
        draft = cancel_draft(order_id)
        wire = dict(
            method="DELETE", host=draft["documented_host"],
            path=draft["documented_path"], query=draft["query"],
        )
        attempt = json.loads(raw)
        need(attempt["attempt_id"] == attempt_id
             and attempt["request_id"] == request_id
             and attempt["operation"] == operation == "CANCEL"
             and attempt["wire"] == wire,
             "CANCEL_ATTEMPT_BINDING_MISMATCH")
        receipt_raw = source["receipts"].get(attempt_id)
        need(receipt_raw is not None, "DURABLE_CANCEL_RECEIPT_REQUIRED")
        receipt = json.loads(receipt_raw)
        origin = (
            "EXPLICIT_FIXTURE_TRANSPORT"
            if source["mode"] == "OFFLINE_FIXTURE"
            else "LOCAL_HTTP_TRANSPORT"
        )
        need(receipt.get("origin") == origin
             and receipt.get("attempt_id") == attempt_id
             and receipt.get("wire_fingerprint") == sha(wire),
             "CANCEL_RECEIPT_PROVENANCE_MISMATCH")
        need(type(receipt.get("http_status")) is int
             and receipt["http_status"] == 200,
             "SUCCESSFUL_CANCEL_RECEIPT_REQUIRED")
        need(cancel_ack(receipt["body"], order_id)["status"]
             == "CANCEL_ACKNOWLEDGED_RECONCILE_REQUIRED",
             "CANCEL_ACK_ORDER_MISMATCH")
        need(request["state"] not in {
            "UNKNOWN", "IN_FLIGHT", "CANCEL_IN_FLIGHT",
            "CANCEL_OUTCOME_UNKNOWN",
        }, "CANCEL_LOCAL_OUTCOME_UNRESOLVED")
        matching = [o for o in snapshot["orders"]
                    if o["order_id"] == order_id]
        need(len(matching) == 1
             and matching[0]["status"] in {"CANCELLED", "FILLED"}
             and matching[0]["pending"] == 0,
             "CANCEL_SIGNED_TERMINAL_ORDER_REQUIRED")
        references.append(dict(
            attempt_id=attempt_id, request_id=request_id,
            order_id=order_id, receipt_fingerprint=sha(receipt),
            terminal_status=matching[0]["status"],
        ))
    return references


def review_with_cancellations(
    source, snapshot, pin, *, entry_id, as_of, journal, exit_sequences,
):
    references = review_cancellations(source, snapshot, entry_id=entry_id)
    # Reuse the entry/exit quantity reviewer with the independently checked
    # CANCEL evidence separated from its PLACE-only input contract.
    place_attempts = [r for r in source["attempts"] if r[2] == "PLACE"]
    place_ids = {r[0] for r in place_attempts}
    projected = dict(
        source, attempts=place_attempts,
        receipts={key: raw for key, raw in source["receipts"].items()
                  if key in place_ids},
    )
    result = review_journal_lifecycle(
        projected, snapshot, pin, entry_id=entry_id, as_of=as_of,
        journal=journal, exit_sequences=exit_sequences,
    )
    return dict(
        result,
        source_fingerprint=sha(source),
        cancellation_reference_count=len(references),
        cancellation_references=references,
        cancellation_ack_is_flat_proof=False,
        cancellation_submission_authorization_assessed=False,
        strategy_ownership_verified=False,
        exit_submission_permission=False,
        reservation_release_permission=False,
        production_execution_enabled=False,
    )
