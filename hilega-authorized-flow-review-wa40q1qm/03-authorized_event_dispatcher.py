"""Verified synthetic journal -> authorized staged adapter."""
import json

from authorized_prepared_entry import execute_prepared_fixture
from authorized_exit_fixture import execute_authorized_exit
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def dispatch_journal_record(
    application, closed_adapter, execution_store, pin, journal, *,
    sequence, as_of, adapter_module, clock,
):
    need(pin["scope"].startswith("FIXTURE:"), "SYNTHETIC_ACCOUNT_REQUIRED")
    records = verified_records(journal)
    need(type(sequence) is int and 1 <= sequence <= len(records),
         "JOURNAL_SEQUENCE_INVALID")
    record = records[sequence - 1]
    need(record["sequence"] == sequence, "JOURNAL_SEQUENCE_MISMATCH")
    events = accepted(record)
    if not events:
        return dict(
            status="NO_CONFIRMED_EXECUTION_EVENT",
            orders_sent_to_upstox=False,
            production_execution_enabled=False,
        )
    need(len(events) == 1, "SINGLE_EVENT_REQUIRED_NO_REVERSAL")
    event = events[0]
    source = read_sources(
        application.path, closed_adapter, pin["scope"])
    need(len(source["requests"]) == 1, "SINGLE_APPLICATION_ENTRY_REQUIRED")
    key, _, raw = source["requests"][0]
    request = json.loads(raw)
    need(event["direction"] == request["direction"],
         "EVENT_ENTRY_DIRECTION_MISMATCH")
    if event["role"] == "ENTRY":
        need(event["id"] == request["signal_id"]
             and event["event_at"] == request["signal_at"],
             "EVENT_PREPARED_SIGNAL_MISMATCH")
        result = execute_prepared_fixture(
            application, closed_adapter, execution_store, pin,
            adapter_module=adapter_module, clock=clock,
        )
    else:
        need(event["role"] == "EXIT", "EXECUTION_EVENT_ROLE_INVALID")
        result = execute_authorized_exit(
            execution_store, pin, adapter_module=adapter_module,
            entry_id=key, exit_event=event,
            contract=source["plans"][key]["evidence"]["contract"],
            clock=clock,
        )
    return dict(
        result, dispatched_event_role=event["role"],
        journal_sequence=sequence, production_runtime_integrated=False,
    )
