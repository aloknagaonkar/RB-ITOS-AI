"""Priced EXIT sequencing candidate. No production gate override."""
import json

from production_execution_coordinator_candidate import ExecutionCoordinatorCandidate
from priced_exit_transaction_candidate import submit_priced_exit_candidate
from owned_exit_pricing_candidate import prepare_exit_at_bid
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import verify
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


class PricedExecutionCoordinatorCandidate(ExecutionCoordinatorCandidate):
    def __init__(self, *args, market_capture_provider, **kwargs):
        super().__init__(*args, **kwargs)
        self.market_capture = market_capture_provider

    def blocked(self, status):
        return dict(
            status=status, orders_sent=False,
            production_execution_enabled=False,
            reservation_release_permission=False,
        )

    def current_source(self):
        return read_sources(
            self.app.path, self.adapter.store.path, self.pin["scope"])

    def signed_order(self, snapshot, parent):
        verify(snapshot, self.pin, as_of=self.clock().isoformat())
        need(snapshot.get("profile_verified_before_and_after") is True
             and snapshot.get("account_position_rows_complete") is True,
             "COMPLETE_PINNED_CAPTURE_REQUIRED")
        orders, positions = validate_account_rows(snapshot)
        order = orders.get(parent.get("order_id"))
        need(order is not None, "ACKNOWLEDGED_ENTRY_ORDER_REQUIRED")
        body = parent["draft"]["body"]
        need(order["side"] == "BUY"
             and order["instrument"] == body["instrument_token"]
             and order["product"] == body["product"]
             and order["quantity"] == body["quantity"],
             "ENTRY_ORDER_IDENTITY_MISMATCH")
        return order

    def submit_priced(self, entry_id, request_id, sequence):
        return submit_priced_exit_candidate(
            self.app, self.adapter, self.pin, self.authority,
            adapter_module=self.module, entry_id=entry_id,
            request_id=request_id, journal=self.journal,
            exit_sequence=sequence,
            capture_provider=self.capture,
            market_capture_provider=self.market_capture,
            clock=self.clock,
        )

    def dispatch(self, sequence):
        event = self.event(sequence)
        if event is None or event["role"] == "ENTRY":
            return super().dispatch(sequence)
        need(event["role"] == "EXIT", "EXECUTION_EVENT_ROLE_INVALID")
        source, entry_id, parent = self.context(event)
        exits = [
            json.loads(raw) for key, fp, raw in source["requests"]
            if json.loads(raw)["draft"]["body"]["transaction_type"] == "SELL"
            and json.loads(raw)["signal_id"] == event["id"]
        ]
        need(len(exits) <= 1, "MULTIPLE_EXIT_REQUESTS")
        if exits:
            # Existing attempts recover without fresh capture or pricing.
            # An unsubmitted request still faces all pricing/ownership checks.
            return self.submit_priced(entry_id, exits[0]["request_id"], sequence)

        try:
            self.adapter.transport.check()
        except self.module.GateClosed:
            return self.closed_result()

        # Never create a new cancellation from an old exit event.
        from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware
        need(0 <= (self.clock()-aware(event["event_at"])).total_seconds() <= 60,
             "FRESH_EXIT_EVENT_REQUIRED")
        snapshot = self.capture()
        order = self.signed_order(snapshot, parent)

        with self.adapter.store.tx() as db:
            cancel_exists = db.execute(
                "SELECT 1 FROM attempts WHERE request_id=? AND operation='CANCEL'",
                (entry_id,),
            ).fetchone()
        if cancel_exists or order["status"] in {"OPEN", "PARTIAL"}:
            self.cancel_entry_remainder(sequence)
            current = next(
                r for r in self.adapter.store.requests()
                if r["request_id"] == entry_id)
            if current["state"] in {
                "UNKNOWN", "CANCEL_OUTCOME_UNKNOWN", "CANCEL_IN_FLIGHT",
            }:
                return self.blocked("CANCEL_RECONCILIATION_REQUIRED")
            # ACK is not terminal-order or fill proof.
            snapshot = self.capture()
            order = self.signed_order(snapshot, current)

        if order["status"] not in {"FILLED", "CANCELLED"} or order["pending"]:
            return self.blocked("ENTRY_TERMINAL_RECONCILIATION_REQUIRED")
        if order["filled"] == 0:
            return self.blocked("ENTRY_CANCELLED_WITHOUT_FILL")
        requested = parent["draft"]["body"]["quantity"]
        if order["filled"] != requested:
            return self.blocked("PRODUCTION_PARTIAL_QUANTITY_POLICY_PENDING")

        # Current market evidence for the owned instrument, not current ATM.
        bundle = self.market_capture()
        current_source = self.current_source()
        saved = prepare_exit_at_bid(
            self.adapter, current_source, event, bundle, self.pin,
            entry_id=entry_id, clock=self.clock,
        )
        # A further account/market recheck occurs inside the transaction path.
        return self.submit_priced(entry_id, saved["request_id"], sequence)
