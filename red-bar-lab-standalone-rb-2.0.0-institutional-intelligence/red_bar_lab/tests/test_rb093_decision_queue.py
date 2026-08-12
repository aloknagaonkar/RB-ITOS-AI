from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.tests.test_execution_foundation import (
    AutoFakeZerodha,
    _insert_confirmed_signal,
    _setup,
)


def _service(tmp_path):
    settings, db = _setup(tmp_path)
    _insert_confirmed_signal(db)
    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        allow_outside_market_hours=True,
        allow_stale_signals=True,
        maximum_portfolio_risk_pct=5.0,
    )
    return service, db


def test_rb093_foreground_committee_queues_without_opening(tmp_path):
    service, db = _service(tmp_path)

    opened, skipped, scored, errors = service.process_new_signals(
        trading_date="2026-08-10", lots=1, queue_only=True
    )

    assert opened == 0
    assert errors == []
    assert scored == 2
    assert db.read_paper_execution_orders("PAPER-STD") == []

    queue = db.read_execution_queue(signal_id="SIG-AUTO-1")
    assert len(queue) == 2
    assert all(row["status"] == "APPROVED" for row in queue)
    assert all(float(row["execution_probability_pct"]) >= 70.0 for row in queue)

    events = db.read_execution_state_events(signal_id="SIG-AUTO-1", limit=100)
    states = {row["state"] for row in events}
    assert "EXECUTION_COMMITTEE" in states
    assert "QUEUED" in states


def test_rb093_queue_consumer_opens_only_after_approval(tmp_path):
    service, db = _service(tmp_path)
    service.process_new_signals(
        trading_date="2026-08-10", lots=1, queue_only=True
    )

    opened, errors = service.execute_approved_queue(
        trading_date="2026-08-10", lots=1
    )

    assert opened == 2
    assert errors == []
    orders = db.read_paper_execution_orders("PAPER-STD")
    assert len(orders) == 2
    queue = db.read_execution_queue(signal_id="SIG-AUTO-1")
    assert all(row["status"] == "ACTIVE" for row in queue)
    assert all(row["order_id"] for row in queue)


def test_rb093_queue_consumer_is_idempotent(tmp_path):
    service, db = _service(tmp_path)
    service.process_new_signals(
        trading_date="2026-08-10", lots=1, queue_only=True
    )
    first_opened, first_errors = service.execute_approved_queue(
        trading_date="2026-08-10", lots=1
    )
    second_opened, second_errors = service.execute_approved_queue(
        trading_date="2026-08-10", lots=1
    )

    assert first_opened == 2
    assert first_errors == []
    assert second_opened == 0
    assert second_errors == []
    assert len(db.read_paper_execution_orders("PAPER-STD")) == 2
