from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.live_admission_automation import (
    _AdmissionDatabaseProxy,
)


IST = ZoneInfo("Asia/Kolkata")


class _Database:
    def __init__(self, rows):
        self.rows = list(rows)
        self.diagnostics = []
        self.events = []

    def read_signal_attempts(self, instrument_key, trading_date):
        return list(self.rows)

    def insert_paper_signal_diagnostic(self, row):
        self.diagnostics.append(dict(row))

    def insert_execution_state_event(self, row):
        self.events.append(dict(row))


def _proxy(database, now):
    return _AdmissionDatabaseProxy(
        database,
        now=now,
        max_signal_age_seconds=180,
        allow_outside_market_hours=False,
        allow_stale_signals=False,
        enable_opportunity_extension=True,
    )


def test_terminal_live_block_is_filtered_before_legacy_engine():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-MISSING",
                "confirmation_timestamp": None,
                "direction": "BULLISH",
                "state": "CONFIRMED",
            },
            {
                "signal_id": "SIG-FRESH",
                "confirmation_timestamp": now - timedelta(seconds=30),
                "direction": "BEARISH",
                "state": "CONFIRMED",
            },
        ]
    )

    rows = _proxy(database, now).read_signal_attempts("NIFTY", "2026-08-21")

    assert [row["signal_id"] for row in rows] == ["SIG-FRESH"]
    assert database.diagnostics[0]["reason"] == (
        "SIGNAL_CONFIRMATION_TIMESTAMP_MISSING"
    )
    assert database.events[0]["state"] == "LIVE_ADMISSION_BLOCKED"
    assert "historical_override=PROHIBITED" in database.events[0]["detail"]


def test_stale_signal_reaches_existing_opportunity_extension_path():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    database = _Database(
        [
            {
                "signal_id": "SIG-STALE",
                "confirmation_timestamp": now - timedelta(minutes=6),
                "direction": "BULLISH",
                "state": "CONFIRMED",
            }
        ]
    )

    proxy = _proxy(database, now)
    rows = proxy.read_signal_attempts("NIFTY", "2026-08-21")

    assert [row["signal_id"] for row in rows] == ["SIG-STALE"]
    assert proxy.decisions["SIG-STALE"].requires_opportunity_extension is True
    assert database.diagnostics == []
    assert database.events == []


def test_workspace_installs_additive_live_admission_service():
    from red_bar_lab.ui import workspace
    from red_bar_lab.ui import _shared
    from red_bar_lab.execution.live_admission_automation import (
        LiveAdmissionRedBarPaperAutomationService,
    )

    assert workspace.shared_ui.RedBarPaperAutomationService is (
        LiveAdmissionRedBarPaperAutomationService
    )
    assert _shared.RedBarPaperAutomationService is (
        LiveAdmissionRedBarPaperAutomationService
    )
