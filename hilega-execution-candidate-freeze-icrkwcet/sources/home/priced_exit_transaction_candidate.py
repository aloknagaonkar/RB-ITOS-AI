"""Application lock + current adapter transaction for candidate SELL authorization."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from priced_exit_authorization_candidate import (
    issue_exit_candidate as issue_candidate,
    claim_exit_candidate as claim_candidate,
)
from market_lab.hilega_preparation_runtime_v1.ownership_state import (
    SourceReader, rollback_database,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_connection

EXPECTED_ADAPTER = "a70cc00e9c1e4e8c315460cd3c46e06acdd8c7ebf666bf189ceccf027e11ac46"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def submit_priced_exit_candidate(
    application_store, adapter, pin, authority, *,
    adapter_module, entry_id, request_id, journal, exit_sequence,
    capture_provider, market_capture_provider, clock,
):
    path = Path(adapter_module.__file__)
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_ADAPTER,
         "PINNED_PRODUCTION_ADAPTER_CANDIDATE_REQUIRED")
    need(type(adapter) is adapter_module.Adapter
         and adapter.store.mode == "LIVE_CLOSED"
         and adapter.store.scope == pin["scope"],
         "EXACT_LIVE_CLOSED_ADAPTER_REQUIRED")
    app_path = rollback_database(application_store.path)
    need(not app_path.samefile(adapter.store.path), "DISTINCT_DATABASES_REQUIRED")

    with application_store.lock():
        with closing(sqlite3.connect(
            app_path.as_uri() + "?mode=ro", uri=True, timeout=10,
        )) as app:
            app.execute("PRAGMA query_only=ON")
            app.execute("BEGIN")
            try:
                with adapter.store.tx() as db:
                    source = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="LIVE_CLOSED",
                    )
                    found = db.execute(
                        "SELECT fingerprint,data FROM requests WHERE id=?",
                        (request_id,),
                    ).fetchone()
                    attempts = db.execute(
                        "SELECT id,request_id,operation,data FROM attempts "
                        "WHERE request_id=?", (request_id,),
                    ).fetchall()
                need(found is not None, "PREPARED_ENTRY_REQUIRED")
                need(entry_id in source["bindings"],
                     "APPLICATION_ENTRY_BINDING_REQUIRED")
                parents = [r for r in source["requests"] if r[0] == entry_id]
                need(len(parents) == 1
                     and parents[0][1]
                         == source["bindings"][entry_id]["request_fingerprint"],
                     "APPLICATION_ENTRY_BINDING_CHANGED")
                parent = json.loads(parents[0][2])
                parent_stable = {k: parent[k] for k in (
                    "request_id", "draft", "signal_id", "signal_at",
                    "direction", "reservation_reference",
                )}
                need(adapter_module.sha(parent_stable) == parents[0][1],
                     "PARENT_REQUEST_FINGERPRINT_CHANGED")
                request = json.loads(found[1])
                stable = {k: request[k] for k in (
                    "request_id", "draft", "signal_id", "signal_at",
                    "direction", "reservation_reference",
                )}
                need(adapter_module.sha(stable) == found[0],
                     "REQUEST_FINGERPRINT_CHANGED")
                need(request["draft"]["body"]["transaction_type"] == "SELL"
                     and parent["draft"]["body"]["transaction_type"] == "BUY"
                     and request["direction"] == parent["direction"]
                     and request["reservation_reference"]
                         == parent["reservation_reference"],
                     "EXIT_PARENT_REQUEST_MISMATCH")
                wire = adapter._wire(request, "PLACE")

                if attempts:
                    need(len(attempts) == 1, "SINGLE_ENTRY_ATTEMPT_REQUIRED")
                    aid, rid, operation, raw = attempts[0]
                    attempt = json.loads(raw)
                    need(attempt["attempt_id"] == aid
                         and attempt["request_id"] == rid == request_id
                         and attempt["operation"] == operation == "PLACE"
                         and attempt["wire"] == wire,
                         "RECOVERY_ATTEMPT_BINDING_MISMATCH")
                    adapter.recover()
                    return dict(
                        status="EXISTING_EXIT_RECOVERED_NO_SUBMISSION",
                        recovery_only=True, account_capture_requested=False,
                        new_attempt_created=False,
                        production_execution_enabled=False,
                    )

                try:
                    adapter.transport.check()
                except adapter_module.GateClosed:
                    # Preserve the adapter's normal gate-refusal audit.
                    result = adapter.submit(request_id)
                    return dict(
                        result, account_capture_requested=False,
                        recovery_only=False, new_attempt_created=False,
                    )

                snapshot = capture_provider()
                market_bundle = market_capture_provider()
                grant = issue_candidate(
                    authority, pin, source, snapshot,
                    market_bundle=market_bundle,
                    entry_id=entry_id, request_id=request_id, wire=wire,
                    journal=journal, exit_sequence=exit_sequence,
                    at=clock().isoformat(),
                )

                def authorize(db, attempt):
                    # App lock/read transaction remain held. Adapter SELECTs
                    # use the very transaction that will insert this attempt.
                    current = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="LIVE_CLOSED",
                    )
                    need(attempt["operation"] == "PLACE",
                         "SELL_PLACE_OPERATION_REQUIRED")
                    return claim_candidate(
                        db, grant, authority, pin, current, snapshot,
                        market_bundle=market_bundle,
                        entry_id=entry_id, request_id=attempt["request_id"],
                        wire=attempt["wire"], journal=journal,
                        exit_sequence=exit_sequence,
                        attempt_id=attempt["attempt_id"],
                        at=clock().isoformat(),
                    )

                previous = getattr(adapter, "production_attempt_authorizer", None)
                adapter.production_attempt_authorizer = authorize
                try:
                    result = adapter.submit(request_id)
                finally:
                    adapter.production_attempt_authorizer = previous
                return dict(
                    status="CANDIDATE_EXIT_ATTEMPT_RECORDED",
                    adapter_result=result,
                    account_capture_requested=True,
                    recovery_only=False,
                    production_execution_enabled=False,
                )
            finally:
                app.rollback()
