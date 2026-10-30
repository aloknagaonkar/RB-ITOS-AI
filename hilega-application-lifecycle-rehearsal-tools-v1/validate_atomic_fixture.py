"""Demonstrate fixture-only atomic exit binding; no live reads or writes."""
import json
import test_atomic_exit as fixtures


def main():
    trial=fixtures.AtomicExitTests()
    trial.setUp()
    folder=trial.path.parent
    try:
        before=trial.counts()
        first=trial.bind()
        second=trial.bind()
        after=trial.counts()
        assert first["orders_sent"] is False
        assert second["idempotent_replay"] is True
        assert after[0]==1 and after[1]==before[1]+1
        assert after[3:]==before[3:]
    finally:
        trial.doCleanups()
    assert not folder.exists()
    failure=fixtures.AtomicExitTests()
    failure.setUp()
    rollback_folder=failure.path.parent
    try:
        failure.test_rollback_after_adapter_insert()
    finally:
        failure.doCleanups()
    assert not rollback_folder.exists()
    print(json.dumps(dict(
        status="ATOMIC_EXIT_BINDING_FIXTURE_PASS",
        scope="SYNTHETIC_FIXTURE_ONLY",
        reference_and_disabled_request_committed_together=True,
        replay_does_not_duplicate=True,
        rollback_after_adapter_insert_verified=True,
        exit_transport_attempts_created=0,
        temporary_databases_removed=True,
        runtime_integration=False,
        live_evidence_assessed=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False),indent=2))


if __name__=="__main__":
    main()
