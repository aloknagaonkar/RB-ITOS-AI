"""Synthetic full/partial exit lifecycle demonstration; no live account access."""
import json
import test_exit_fills as fixtures


def main():
    full=fixtures.ExitFillTests()
    full.setUp()
    folder=full.a.path.parent
    try:
        result=full.review()
        replay=full.review()
        assert result["fixture_flat_reference_verified"] is True
        assert replay["remaining_quantity"]==0
        assert replay["reservation_release_permission"] is False
    finally:
        full.doCleanups()
    assert not folder.exists()
    partial=fixtures.ExitFillTests()
    partial.setUp()
    second=partial.a.path.parent
    try:
        partial.test_partial_cancel_is_not_flat()
        partial.test_sell_cannot_borrow_future_buy_fill()
    finally:
        partial.doCleanups()
    assert not second.exists()
    print(json.dumps(dict(
        status="EXIT_FILL_LIFECYCLE_FIXTURE_PASS",
        scope="SYNTHETIC_FIXTURE_ONLY",
        chronological_fill_quantities_verified=True,
        full_exit_explicit_zero_position_verified=True,
        partial_cancel_retains_exposure=True,
        exit_cannot_borrow_future_entry_fills=True,
        replay_does_not_duplicate_snapshot=True,
        flat_reference_is_fixture_only=True,
        temporary_databases_removed=True,
        runtime_integration=False,
        live_evidence_assessed=False,
        orders_sent_to_upstox=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False),indent=2))


if __name__=="__main__":
    main()
