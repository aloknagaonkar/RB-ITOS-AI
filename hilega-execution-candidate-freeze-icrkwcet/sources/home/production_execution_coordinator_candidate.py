"""Verified journal routing for staged execution candidates. No gate override."""
import json

from production_entry_transaction_candidate import submit_entry_candidate
from production_exit_transaction_candidate import submit_exit_candidate
from production_cancel_transaction_candidate import submit_cancel_candidate
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


class ExecutionCoordinatorCandidate:
    def __init__(
        self, application_store, adapter, pin, authority, *,
        adapter_module, journal, capture_provider, clock, exit_preparer=None,
    ):
        self.app = application_store
        self.adapter = adapter
        self.pin = pin
        self.authority = authority
        self.module = adapter_module
        self.journal = journal
        self.capture = capture_provider
        self.clock = clock
        self.exit_preparer = exit_preparer

    def event(self, sequence):
        records = verified_records(self.journal)
        need(type(sequence) is int and 1 <= sequence <= len(records),
             "JOURNAL_SEQUENCE_INVALID")
        record = records[sequence-1]
        need(record["sequence"] == sequence, "JOURNAL_SEQUENCE_MISMATCH")
        events = accepted(record)
        need(len(events) <= 1, "REVERSAL_COORDINATION_NOT_IMPLEMENTED")
        return events[0] if events else None

    def context(self, event):
        source = read_sources(
            self.app.path, self.adapter.store.path, self.pin["scope"])
        need(len(source["bindings"]) == 1, "SINGLE_BOUND_ENTRY_REQUIRED")
        entry_id = next(iter(source["bindings"]))
        parents = [json.loads(raw) for key, fp, raw in source["requests"]
                   if key == entry_id]
        need(len(parents) == 1, "ENTRY_REQUEST_REQUIRED")
        parent = parents[0]
        need(parent["direction"] == event["direction"],
             "EVENT_ENTRY_DIRECTION_MISMATCH")
        if event["role"] == "EXIT":
            need(event.get("entry_reference_at") is not None
                 and aware(event["entry_reference_at"])
                     == aware(parent["signal_at"]),
                 "EXIT_SIGNAL_PARENT_MISMATCH")
        return source, entry_id, parent

    def closed_result(self):
        return dict(
            status="PRODUCTION_MUTATIONS_CLOSED_IN_CODE",
            orders_sent=False, production_execution_enabled=False,
        )

    def dispatch(self, sequence):
        event = self.event(sequence)
        if event is None:
            return dict(
                status="NO_CONFIRMED_EXECUTION_EVENT",
                orders_sent=False, production_execution_enabled=False,
            )
        source, entry_id, parent = self.context(event)
        if event["role"] == "ENTRY":
            need(event["id"] == parent["signal_id"]
                 and aware(event["event_at"]) == aware(parent["signal_at"]),
                 "ENTRY_SIGNAL_BINDING_MISMATCH")
            return submit_entry_candidate(
                self.app, self.adapter, self.pin, self.authority,
                adapter_module=self.module, request_id=entry_id,
                capture_provider=self.capture, clock=self.clock,
            )

        need(event["role"] == "EXIT", "EXECUTION_EVENT_ROLE_INVALID")

        def prepared_exits(current):
            return [json.loads(raw) for key, fp, raw in current["requests"]
                    if json.loads(raw)["draft"]["body"]["transaction_type"] == "SELL"
                    and json.loads(raw)["signal_id"] == event["id"]]

        exits = prepared_exits(source)
        need(len(exits) <= 1, "MULTIPLE_EXIT_REQUESTS")
        if not exits:
            try:
                self.adapter.transport.check()
            except self.module.GateClosed:
                return self.closed_result()
            if not callable(self.exit_preparer):
                return dict(
                    status="EXIT_PREPARATION_REQUIRED",
                    orders_sent=False, production_execution_enabled=False,
                )
            self.exit_preparer(source, event)
            current = read_sources(
                self.app.path, self.adapter.store.path, self.pin["scope"])
            exits = prepared_exits(current)
            need(len(exits) == 1, "EXACT_PREPARED_EXIT_REQUIRED")

        return submit_exit_candidate(
            self.app, self.adapter, self.pin, self.authority,
            adapter_module=self.module, entry_id=entry_id,
            request_id=exits[0]["request_id"], journal=self.journal,
            exit_sequence=sequence,
            capture_provider=self.capture, clock=self.clock,
        )

    def cancel_entry_remainder(self, sequence):
        event = self.event(sequence)
        need(event is not None and event["role"] == "EXIT",
             "CONFIRMED_EXIT_REQUIRED_FOR_CANCEL")
        source, entry_id, parent = self.context(event)
        return submit_cancel_candidate(
            self.app, self.adapter, self.pin, self.authority,
            adapter_module=self.module, request_id=entry_id,
            journal=self.journal, exit_sequence=sequence,
            capture_provider=self.capture, clock=self.clock,
        )
