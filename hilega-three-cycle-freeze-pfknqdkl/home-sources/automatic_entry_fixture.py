"""Application preparation -> installed fixture execution. No live transport."""
import json

from dispatch_precondition_review import review
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)
from market_lab.hilega_execution_port_v1.adapter import (
    Store, Adapter, FixtureTransport,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def run_entry_fixture(
    application, closed_adapter, execution_store, pin, *,
    as_of, timeout_before=False, timeout_after=False,
    checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"),
         "SYNTHETIC_ACCOUNT_REQUIRED")
    need(type(execution_store) is Store
         and execution_store.mode == "OFFLINE_FIXTURE"
         and execution_store.scope == pin["scope"],
         "EXACT_SEPARATE_FIXTURE_STORE_REQUIRED")
    need(not execution_store.path.samefile(application)
         and not execution_store.path.samefile(closed_adapter),
         "SEPARATE_EXECUTION_DATABASE_REQUIRED")

    source = read_sources(application, closed_adapter, pin["scope"])
    checked = review(source, pin, as_of=as_of)
    need(checked["reference_checks_passed"],
         "ENTRY_PRECONDITIONS_NOT_MET")
    need(read_sources(application, closed_adapter, pin["scope"]) == source,
         "APPLICATION_CHANGED_BEFORE_FIXTURE_EXECUTION")

    key, _, raw = source["requests"][0]
    request = json.loads(raw)
    transport = FixtureTransport(execution_store)
    transport.timeout_before = timeout_before
    transport.timeout_after = timeout_after
    adapter = Adapter(execution_store, transport)
    adapter.prepare(
        request["draft"],
        signal_id=request["signal_id"],
        signal_at=request["signal_at"],
        direction=request["direction"],
        reservation_reference=request["reservation_reference"],
        as_of=as_of,
    )
    # Recover persisted attempts/receipts before considering submission.
    adapter.recover()
    adapter.checkpoint = checkpoint
    adapter.submit(key)
    status = adapter.status()
    saved = next(r for r in status["requests"] if r["request_id"] == key)

    return dict(
        request_state=saved["state"],
        acknowledged_order_reference_present=saved["order_id"] is not None,
        attempt_count=len(status["attempts"]),
        receipt_count=status["receipt_count"],
        fixture_order_count=len(transport.orders()),
        real_order_submission_supported=False,
        production_runtime_integrated=False,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
    )