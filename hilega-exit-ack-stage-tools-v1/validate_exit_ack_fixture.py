"""Synthetic fixture acknowledgement demonstration, no broker/network access."""
import json
import test_exit_ack as fixtures


def main():
    trial=fixtures.ExitAckTests()
    trial.setUp()
    folder=trial.path.parent
    try:
        trial.submit_fixture()
        first=trial.bind()
        replay=trial.bind()
        assert first["fill_confirmed"] is False
        assert first["flat_confirmed"] is False
        assert replay["idempotent_replay"] is True
        assert trial.ack_count()==1
    finally:
        trial.doCleanups()
    assert not folder.exists()
    failure=fixtures.ExitAckTests()
    failure.setUp()
    other=failure.path.parent
    try:
        failure.test_timeout_without_receipt_not_retried()
    finally:
        failure.doCleanups()
    assert not other.exists()
    print(json.dumps(dict(
        status="EXIT_ACK_REFERENCE_FIXTURE_PASS",
        scope="SYNTHETIC_FIXTURE_ONLY",
        fake_transport_only=True,
        durable_ack_reference_bound=True,
        acknowledgement_does_not_confirm_fill=True,
        acknowledgement_does_not_confirm_flatness=True,
        replay_does_not_duplicate=True,
        lost_response_not_resubmitted=True,
        temporary_databases_removed=True,
        runtime_integration=False,
        live_evidence_assessed=False,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False),indent=2))


if __name__=="__main__":
    main()
