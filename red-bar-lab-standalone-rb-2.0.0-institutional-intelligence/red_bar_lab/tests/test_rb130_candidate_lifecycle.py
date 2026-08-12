from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.candidate_lifecycle import CandidateLifecycleManager
from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.tests.test_execution_foundation import AutoFakeZerodha, _setup, _insert_opportunity_signal

IST = ZoneInfo("Asia/Kolkata")


def test_rb130_signal_moves_to_aging_before_hard_expiry():
    now = datetime(2026, 8, 11, 10, 0, tzinfo=IST)
    manager = CandidateLifecycleManager(freshness_seconds=180)
    row = manager.evaluate(
        signal_id="SIG-AGING",
        confirmation_timestamp=(now - timedelta(minutes=6)).isoformat(),
        now=now,
    )
    assert row.state == "AGING"
    assert row.replacement_required is False


def test_rb150_signal_age_is_informational_not_hard_expiry():
    now = datetime(2026, 8, 11, 14, 0, tzinfo=IST)
    manager = CandidateLifecycleManager(freshness_seconds=180)
    row = manager.evaluate(
        signal_id="SIG-OLD",
        confirmation_timestamp=(now - timedelta(hours=1)).isoformat(),
        now=now,
    )
    assert row.state == "AGING"
    assert row.replacement_required is False
    assert row.action == "EVALUATE"
    assert row.reason == "CURRENT_CANDIDATE"


def test_rb150_session_phase_change_does_not_expire_candidate():
    now = datetime(2026, 8, 11, 9, 32, tzinfo=IST)
    manager = CandidateLifecycleManager(freshness_seconds=180, hard_expiry_seconds=1800)
    row = manager.evaluate(
        signal_id="SIG-SESSION",
        confirmation_timestamp=datetime(2026, 8, 11, 9, 29, tzinfo=IST).isoformat(),
        now=now,
    )
    assert row.state == "AGING"
    assert row.reason == "CURRENT_CANDIDATE"


def test_rb150_automation_rechecks_very_old_signal_using_current_strength(tmp_path):
    now = datetime.now(IST)
    trading_date = now.date().isoformat()
    settings, db = _setup(tmp_path)
    _insert_opportunity_signal(
        db,
        signal_id="SIG-RB130-OLD",
        trading_date=trading_date,
        confirmation_timestamp=(now - timedelta(hours=1)).isoformat(),
        confirmation_close=25010.0,
        confirmation_high=25030.0,
        confirmation_low=24990.0,
    )
    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        allow_outside_market_hours=True,
        max_signal_age_seconds=180,
    )
    opened, skipped, scored, errors = service.process_new_signals(
        trading_date=trading_date, lots=1, queue_only=True
    )
    assert opened == 0
    assert errors == []
    assert scored > 0
    rows = db.read_candidate_lifecycle(signal_id="SIG-RB130-OLD")
    assert rows
    # Age alone cannot retire the idea; current candidate evidence decides.
    assert rows[0]["state"] in {"AGING", "VALID", "NEW", "EXPIRED"}
    if rows[0]["state"] == "EXPIRED":
        assert "MARKET_DRIFT_CONFIRMED" in str(rows[0]["reason"])
