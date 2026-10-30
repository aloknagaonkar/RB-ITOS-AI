"""Temporary fixture demonstration. No live account or application access."""
import json
from pathlib import Path
import test_bridge as fixtures
from signature_checks import sign
from exit_intent import create_reference, ReferenceStore


def main():
    f=fixtures.BridgeTests()
    f.setUp()
    folder=f.f.app.parent
    try:
        snapshot=dict(f.snapshot)
        snapshot["signature"]=sign(snapshot,f.pin)
        reference=create_reference(f.source(),snapshot,f.pin,
            entry_request_id="p1",exit_key="fixture-exit",quantity=65,
            reason="FIXTURE_STRATEGY_EXIT",as_of=f.at)
        path=folder/"isolated-exit.sqlite"
        store=ReferenceStore.create(path,f.pin)
        first=store.record(reference,as_of=f.at)
        second=ReferenceStore(path,f.pin).record(reference,as_of=f.at)
        assert first["idempotent_replay"] is False
        assert second["idempotent_replay"] is True
        assert second["orders_sent"] is False
    finally:
        f.doCleanups()
    assert not folder.exists()
    print(json.dumps(dict(
        status="STAGED_EXIT_REFERENCE_FIXTURE_PASS",
        scope="SYNTHETIC_FIXTURE_ONLY",
        reference_survives_reopen=True,
        idempotent_replay_verified=True,
        temporary_databases_removed=True,
        live_evidence_assessed=False,
        runtime_integration=False,
        executable_exit_request_created=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False),indent=2))


if __name__=="__main__":
    main()
