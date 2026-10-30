"""Temporary allocation fixture demonstration; no broker or application access."""
import json
import test_allocation as fixtures


def main():
    f=fixtures.AllocationTests();f.setUp()
    folder=f.path.parent
    try:
        preview=f.sized()
        book=f.book()
        hold=f.reserve(book)
        retained=book.mark_unknown("plan")
        assert preview["half_cash_cap_paise"]==50000
        assert hold["held_paise"]==11000==retained["held_paise"]
        assert preview["daily_loss_limit_required"] is False
        assert preview["policy"]["daily_loss_limit_paise"] is None
    finally:
        f.doCleanups()
    assert not folder.exists()
    print(json.dumps(dict(
        status="HALF_CASH_ALLOCATION_FIXTURE_PASS",
        scope="SYNTHETIC_FIXTURE_ONLY",
        entry_allocation_fraction="0.50",
        daily_loss_limit_paise=None,
        daily_loss_limit_required=False,
        fixed_max_entry_cost_paise=None,
        initial_maximum_lots=1,
        example_cash_paise=100000,
        example_half_cash_cap_paise=50000,
        example_reserved_cost_with_buffer_paise=11000,
        unknown_outcome_retains_reservation=True,
        temporary_database_removed=True,
        broker_cash_locked=False,
        runtime_integration=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False),indent=2))


if __name__=="__main__":
    main()
