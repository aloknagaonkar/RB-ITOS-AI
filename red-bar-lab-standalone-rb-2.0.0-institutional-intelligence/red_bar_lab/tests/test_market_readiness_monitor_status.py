from pathlib import Path

from red_bar_lab.ui.pages.market_readiness import (
    _decision_age_caption,
    _entry_gate_message,
    _format_age,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "pages" / "market_readiness.py"


def test_trade_evidence_page_exposes_monitor_safety_state():
    source = PAGE.read_text(encoding="utf-8")

    assert "Paper monitor safety state" in source
    assert "POSITION_MANAGEMENT_ONLY" in source
    assert "New paper entries are suspended" in source
    assert "confirmed reversal exits remain active" in source
    assert "read_paper_monitor_status" in source


def test_hours_gate_reports_entries_on_hold():
    status = {
        "status": "RUNNING",
        "current_state": "WAITING_FOR_V2_SIGNAL",
        "last_decision": "SKIP",
        "last_reason": "OUTSIDE_AUTOMATIC_ENTRY_HOURS",
    }

    message = _entry_gate_message(status)

    assert message is not None
    assert "on hold" in message
    assert "09:15–15:25 IST" in message


def test_market_closed_decision_reports_entries_on_hold():
    status = {
        "status": "RUNNING",
        "current_state": "WAITING_FOR_V2_SIGNAL",
        "last_decision": "MARKET_CLOSED",
        "last_reason": None,
    }

    message = _entry_gate_message(status)

    assert message is not None
    assert "market is closed" in message


def test_running_state_without_gate_is_not_flagged():
    status = {
        "status": "RUNNING",
        "current_state": "WAITING_FOR_V2_SIGNAL",
        "last_decision": "MONITORING",
        "last_reason": "RED_BAR_V2_SNAPSHOT_FRESH",
    }

    assert _entry_gate_message(status) is None


def test_format_age_buckets():
    assert _format_age(45) == "45s"
    assert _format_age(300) == "5m"
    assert _format_age(7200) == "2.0h"


class _FakeDatabaseWithDiagnostics:
    def __init__(self, rows):
        self._rows = rows

    def read_paper_signal_diagnostics(self, limit=1):
        return self._rows[:limit]


def test_decision_age_caption_reports_recorded_time():
    stamp = "2026-08-31T08:05:00+05:30"
    caption = _decision_age_caption(
        _FakeDatabaseWithDiagnostics([{"timestamp": stamp}])
    )
    assert caption is not None
    assert stamp in caption
    assert "ago" in caption


def test_decision_age_caption_absent_without_rows():
    assert _decision_age_caption(_FakeDatabaseWithDiagnostics([])) is None
