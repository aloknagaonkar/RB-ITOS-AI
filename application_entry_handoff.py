"""Application preparation -> installed LIVE_CLOSED adapter."""
from pathlib import Path

from dispatch_precondition_review import review
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)
from market_lab.hilega_execution_port_v1.adapter import (
    Store, Adapter, HttpTransport,
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def handoff_entry(application_store, adapter_store, pin, *, clock, token_provider):
    need(type(adapter_store) is Store
         and adapter_store.mode == "LIVE_CLOSED"
         and adapter_store.scope == pin["scope"],
         "EXACT_PINNED_CLOSED_ADAPTER_REQUIRED")
    need(Path(application_store.path).resolve() != adapter_store.path.resolve(),
         "DISTINCT_DATABASES_REQUIRED")

    with application_store.lock():
        source = read_sources(
            application_store.path, adapter_store.path, pin["scope"])
        checked = review(source, pin, as_of=clock().isoformat())
        need(checked["reference_checks_passed"],
             "ENTRY_PRECONDITIONS_NOT_MET")
        need(read_sources(
            application_store.path, adapter_store.path, pin["scope"]
        ) == source, "APPLICATION_CHANGED_BEFORE_HANDOFF")
        # Recheck freshness after local database waits.
        final = review(source, pin, as_of=clock().isoformat())
        need(final["reference_checks_passed"],
             "ENTRY_EVIDENCE_EXPIRED_BEFORE_HANDOFF")

        key = source["requests"][0][0]
        adapter = Adapter(adapter_store, HttpTransport(token_provider))
        result = adapter.submit(key)
        need(result.get("status") == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
             and result.get("orders_sent") is False
             and result.get("production_execution_enabled") is False,
             "UNEXPECTED_ADAPTER_HANDOFF_RESULT")
        return dict(
            status="APPLICATION_ENTRY_REACHED_CLOSED_ADAPTER",
            application_adapter_connection_exercised=True,
            live_submission_authorized=False,
            orders_sent=False,
            production_execution_enabled=False,
            reservation_release_permission=False,
        )