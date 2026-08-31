from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.paper_monitor import (
    _STALE_DIAGNOSTIC_MAX_AGE_SECONDS,
    _diagnostic_recorded_recently,
)


IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 31, 13, 34, 0, tzinfo=IST)


def _row(timestamp):
    return {"final_decision": "BLOCK", "reason": "OUTSIDE_AUTOMATIC_ENTRY_HOURS", "timestamp": timestamp}


def test_recent_diagnostic_is_echoed():
    row = _row((NOW - timedelta(minutes=5)).isoformat())
    assert _diagnostic_recorded_recently(row, now=NOW) is True


def test_stale_pre_open_diagnostic_is_not_echoed():
    row = _row((NOW - timedelta(hours=5)).isoformat())
    assert _diagnostic_recorded_recently(row, now=NOW) is False


def test_boundary_age_is_still_recent():
    row = _row((NOW - timedelta(seconds=_STALE_DIAGNOSTIC_MAX_AGE_SECONDS)).isoformat())
    assert _diagnostic_recorded_recently(row, now=NOW) is True


def test_missing_timestamp_fails_open():
    assert _diagnostic_recorded_recently({}, now=NOW) is True
    assert _diagnostic_recorded_recently({"timestamp": None}, now=NOW) is True


def test_unparseable_timestamp_fails_open():
    assert _diagnostic_recorded_recently(_row("not-a-timestamp"), now=NOW) is True


def test_naive_timestamp_is_treated_as_ist():
    naive_stale = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert _diagnostic_recorded_recently(_row(naive_stale), now=NOW) is False
