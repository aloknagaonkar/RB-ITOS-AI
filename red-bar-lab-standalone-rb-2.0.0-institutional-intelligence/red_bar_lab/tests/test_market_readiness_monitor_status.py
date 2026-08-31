from pathlib import Path

from red_bar_lab.ui.pages.market_readiness import _entry_gate_message


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
