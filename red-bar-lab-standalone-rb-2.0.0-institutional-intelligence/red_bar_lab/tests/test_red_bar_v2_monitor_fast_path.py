from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.attribution_automation import (
    AttributionAwarePaperAutomationService,
)
from red_bar_lab.execution.automation import _count_signal_entries
from red_bar_lab.execution.live_admission_automation import (
    LiveAdmissionRedBarPaperAutomationService,
    _AdmissionDatabaseProxy,
)


IST = ZoneInfo("Asia/Kolkata")


class _Database:
    def __init__(self, rows):
        self.rows = rows
        self.diagnostics = []
        self.events = []

    def read_signal_attempts(self, instrument_key, trading_date):
        return list(self.rows)

    def insert_paper_signal_diagnostic(self, row):
        self.diagnostics.append(dict(row))

    def insert_execution_state_event(self, row):
        self.events.append(dict(row))


def test_runtime_automation_includes_live_admission_boundary():
    assert issubclass(
        AttributionAwarePaperAutomationService,
        LiveAdmissionRedBarPaperAutomationService,
    )


def test_strict_monitor_admission_filters_stale_signal_before_scoring():
    now = datetime(2026, 8, 27, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "RBV2-STALE",
                "confirmation_timestamp": now - timedelta(seconds=181),
                "direction": "BEARISH",
                "state": "CONFIRMED",
            }
        ]
    )
    proxy = _AdmissionDatabaseProxy(
        database,
        now=now,
        max_signal_age_seconds=180,
        allow_outside_market_hours=False,
        allow_stale_signals=False,
        enable_opportunity_extension=False,
    )

    rows = proxy.read_signal_attempts("NIFTY", "2026-08-27")

    assert rows == []
    assert database.diagnostics[0]["reason"] == "MAX_SIGNAL_AGE_EXCEEDED"
    assert database.events[0]["state"] == "LIVE_ADMISSION_BLOCKED"


def test_signal_entry_count_reuses_already_loaded_orders():
    orders = [
        {"signal_id": "RBV2-ONE", "order_id": "PAPER-1"},
        {"signal_id": "RBV2-ONE", "order_id": "PAPER-2"},
        {"signal_id": "RBV2-TWO", "order_id": "PAPER-3"},
    ]

    assert _count_signal_entries(orders, "RBV2-ONE") == 2
    assert _count_signal_entries(orders, "RBV2-TWO") == 1
