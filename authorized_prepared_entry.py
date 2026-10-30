"""Validated application preparation -> authorized fixture attempt only."""
import hashlib
import json
from pathlib import Path

from dispatch_precondition_review import review
from fixture_execution_authorization import issue, claim
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)

ADAPTER_SHA = "82c7606a4c4aad8b540b59db35766a736982dac18e9501f26179d9e8fe24b4a4"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def execute_prepared_fixture(
    application_store, closed_adapter, execution_store, pin, *,
    adapter_module, clock,
):
    path = Path(adapter_module.__file__).resolve()
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest() == ADAPTER_SHA,
         "PINNED_STAGED_ADAPTER_REQUIRED")
    need(pin["scope"].startswith("FIXTURE:"), "SYNTHETIC_ACCOUNT_REQUIRED")
    need(type(execution_store) is adapter_module.Store
         and execution_store.mode == "OFFLINE_FIXTURE"
         and execution_store.scope == pin["scope"],
         "EXACT_FIXTURE_STORE_REQUIRED")
    need(not execution_store.path.samefile(application_store.path)
         and not execution_store.path.samefile(closed_adapter),
         "SEPARATE_EXECUTION_DATABASE_REQUIRED")

    with application_store.lock():
        source = read_sources(
            application_store.path, closed_adapter, pin["scope"])
        need(len(source["requests"]) == 1, "SINGLE_PREPARED_ENTRY_REQUIRED")
        key, fingerprint, raw = source["requests"][0]
        request = json.loads(raw)
        adapter = adapter_module.Adapter(
            execution_store, adapter_module.FixtureTransport(execution_store))

        with execution_store.tx() as db:
            attempts = db.execute(
                "SELECT data FROM attempts WHERE request_id=?", (key,)
            ).fetchall()
            saved = db.execute(
                "SELECT fingerprint,data FROM requests WHERE id=?", (key,)
            ).fetchone()

        if attempts:
            need(len(attempts) == 1 and saved is not None
                 and saved[0] == fingerprint,
                 "EXISTING_ATTEMPT_REQUIRES_REVIEW")
            persisted = json.loads(saved[1])
            stable = {
                k: persisted[k] for k in (
                    "request_id", "draft", "signal_id", "signal_at",
                    "direction", "reservation_reference",
                )
            }
            attempt = json.loads(attempts[0][0])
            need(adapter_module.sha(stable) == fingerprint
                 and attempt["request_id"] == key
                 and attempt["operation"] == "PLACE"
                 and attempt["wire"] == adapter._wire(persisted, "PLACE"),
                 "RECOVERY_REQUEST_OR_WIRE_MISMATCH")
            status = adapter.recover()
            return dict(
                status="EXISTING_ATTEMPT_RECOVERED_NO_SUBMISSION",
                recovery_only=True, new_attempt_created=False,
                orders_sent_to_upstox=False,
                production_execution_enabled=False,
            )

        now = clock()
        checked = review(source, pin, as_of=now.isoformat())
        need(checked["reference_checks_passed"],
             "FRESH_ENTRY_PRECONDITIONS_REQUIRED")
        reservation = source["cash_reservations"][key]
        adapter.prepare(
            request["draft"], signal_id=request["signal_id"],
            signal_at=request["signal_at"], direction=request["direction"],
            reservation_reference=request["reservation_reference"],
            as_of=now.isoformat(),
        )
        wire = adapter._wire(request, "PLACE")
        authorization = issue(
            pin, request_id=key, wire=wire,
            budget_paise=reservation["held_cents"],
            fee_buffer_paise=reservation["fee_buffer_cents"],
            at=now.isoformat(),
        )

        def authorize(db, attempt):
            current = read_sources(
                application_store.path, closed_adapter, pin["scope"])
            need(current == source, "APPLICATION_CHANGED_BEFORE_ATTEMPT")
            final_now = clock()
            final = review(current, pin, as_of=final_now.isoformat())
            need(final["reference_checks_passed"],
                 "ENTRY_EVIDENCE_EXPIRED_BEFORE_ATTEMPT")
            claim(
                db, authorization, pin, request_id=key,
                wire=attempt["wire"], at=final_now.isoformat(),
                attempt_id=attempt["attempt_id"],
            )

        adapter.fixture_authorization_claim = authorize
        adapter.submit(key)
        return dict(
            status="AUTHORIZED_FIXTURE_ATTEMPT_COMMITTED",
            recovery_only=False, new_attempt_created=True,
            orders_sent_to_upstox=False,
            production_execution_enabled=False,
        )