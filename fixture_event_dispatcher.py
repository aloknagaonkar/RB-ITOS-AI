"""Verified journal event -> fixture execution only. No live service hook."""
from automatic_entry_fixture import run_entry_fixture
from automatic_exit_fixture import run_exit_fixture
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)
from market_lab.hilega_production_simulator_bridge_v1 import (
    verified_records, accepted,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def dispatch_journal_record(
    application, closed_adapter, execution_store, pin, journal, *,
    sequence, as_of,
):
    need(pin["scope"].startswith("FIXTURE:"), "SYNTHETIC_ACCOUNT_REQUIRED")
    records = verified_records(journal)
    need(type(sequence) is int and 1 <= sequence <= len(records),
         "JOURNAL_SEQUENCE_INVALID")
    events = accepted(records[sequence - 1])
    if not events:
        return dict(
            status="NO_CONFIRMED_EXECUTION_EVENT",
            orders_sent_to_upstox=False,
            production_execution_enabled=False,
        )
    # Reversal handling requires its own lifecycle policy.
    need(len(events) == 1, "SINGLE_EVENT_REQUIRED_NO_REVERSAL")

    event = events[0]
    source = read_sources(application, closed_adapter, pin["scope"])
    need(len(source["requests"]) == 1, "SINGLE_APPLICATION_ENTRY_REQUIRED")
    import json
    key, _, raw = source["requests"][0]
    request = json.loads(raw)
    need(event["direction"] == request["direction"],
         "EVENT_ENTRY_DIRECTION_MISMATCH")

    if event["role"] == "ENTRY":
        need(event["id"] == request["signal_id"],
             "EVENT_PREPARED_SIGNAL_MISMATCH")
        result = run_entry_fixture(
            application, closed_adapter, execution_store, pin, as_of=as_of)
    else:
        need(event["role"] == "EXIT", "EXECUTION_EVENT_ROLE_INVALID")
        result = run_exit_fixture(
            execution_store, pin, entry_id=key, exit_event=event,
            contract=source["plans"][key]["evidence"]["contract"],
            as_of=as_of,
        )
    return dict(result, dispatched_event_role=event["role"],
                journal_sequence=sequence,
                production_runtime_integrated=False)