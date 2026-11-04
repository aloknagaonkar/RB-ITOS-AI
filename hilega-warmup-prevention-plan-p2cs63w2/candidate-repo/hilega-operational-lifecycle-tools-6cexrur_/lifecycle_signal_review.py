"""Verified journal exit-parent references; no execution permission."""
import json

from lifecycle_quantity_review import review_lifecycle
from market_lab.hilega_production_simulator_bridge_v1 import (
    verified_records, accepted,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def bind_exit_events(source, *, entry_id, events):
    requests = {
        key: json.loads(raw) for key, fingerprint, raw in source["requests"]
    }
    need(len(requests) == len(source["requests"]),
         "DUPLICATE_REQUEST_ID")
    need(entry_id in requests, "ENTRY_REQUEST_REQUIRED")
    entry = requests[entry_id]
    by_signal = {}
    for event in events:
        need(event["id"] not in by_signal, "DUPLICATE_EXIT_SIGNAL")
        by_signal[event["id"]] = event

    references = []
    for key, request in requests.items():
        if key == entry_id:
            continue
        need(request["draft"]["body"]["transaction_type"] == "SELL",
             "NON_EXIT_LIFECYCLE_REQUEST")
        event = by_signal.get(request["signal_id"])
        need(event is not None, "CONFIRMED_EXIT_SIGNAL_MISSING")
        need(event["role"] == "EXIT"
             and event["direction"] == request["direction"] == entry["direction"]
             and aware(event["event_at"]) == aware(request["signal_at"])
             and event.get("entry_reference_at") is not None
             and aware(event["entry_reference_at"]) == aware(entry["signal_at"])
             and aware(entry["signal_at"]) <= aware(event["event_at"])
             and request["reservation_reference"]
                 == entry["reservation_reference"],
             "EXIT_SIGNAL_PARENT_MISMATCH")
        references.append(dict(
            exit_request_id=key,
            parent_request_id=entry_id,
            event_fingerprint=sha(event),
        ))
    return references


def review_journal_lifecycle(
    source, snapshot, pin, *, entry_id, as_of, journal, exit_sequences,
):
    records = verified_records(journal)
    need(isinstance(exit_sequences, (list, tuple))
         and all(type(n) is int and 1 <= n <= len(records)
                 for n in exit_sequences)
         and len(set(exit_sequences)) == len(exit_sequences),
         "EXIT_JOURNAL_SEQUENCES_INVALID")
    events = []
    for sequence in exit_sequences:
        record = records[sequence - 1]
        need(record["sequence"] == sequence, "JOURNAL_SEQUENCE_MISMATCH")
        boundary = accepted(record)
        # Reversal scheduling remains outside this candidate.
        need(len(boundary) == 1 and boundary[0]["role"] == "EXIT",
             "SINGLE_CONFIRMED_EXIT_BOUNDARY_REQUIRED")
        events.extend(boundary)

    references = bind_exit_events(source, entry_id=entry_id, events=events)
    result = review_lifecycle(
        source, snapshot, pin, entry_id=entry_id, as_of=as_of)
    current = verified_records(journal)
    need(len(current) >= len(records)
         and all(current[i]["record_hash"] == row["record_hash"]
                 for i, row in enumerate(records)),
         "JOURNAL_CHANGED_DURING_REVIEW")
    return dict(
        result,
        exit_signal_parent_assessed=True,
        exit_signal_reference_count=len(references),
        exit_signal_references=references,
        journal_prefix_sequence=len(records),
        journal_prefix_hash=records[-1]["record_hash"] if records else None,
        strategy_ownership_verified=False,
        exit_submission_permission=False,
        reservation_release_permission=False,
        production_execution_enabled=False,
    )
