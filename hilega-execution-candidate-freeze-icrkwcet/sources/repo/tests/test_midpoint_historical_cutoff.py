import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts/midpoint_append_live_dates_to_replay.py"
    spec = importlib.util.spec_from_file_location("midpoint_append_cutoff", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _row(timestamp: str, **updates):
    row = {
        "session_date": "2026-10-01",
        "event_timestamp": timestamp,
        "event_type": "E_ENTRY",
        "underlying_price": 22500.0,
        "futures_price": 22520.0,
        "futures_vwap": 22515.0,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
    }
    row.update(updates)
    return row


def test_1515_session_bookkeeping_is_outside_exact_360_minute_replay():
    module = _load_script()
    minute = datetime(2026, 10, 1, 12, 10, tzinfo=IST)
    index = {minute: {"close": 22500.0}}
    futures = {minute: {"close": 22520.0, "vwap": 22515.0}}
    rows, differences = module.audit_parity(
        date(2026, 10, 1),
        [
            _row("2026-10-01T12:10:00+05:30"),
            _row(
                "2026-10-01T15:15:00+05:30",
                event_type="SESSION_END_UNRESOLVED",
                underlying_price=None,
                futures_price=None,
                futures_vwap=None,
            ),
        ],
        index,
        futures,
    )
    assert [row["event_timestamp"] for row in rows] == [
        "2026-10-01T12:10:00+05:30"
    ]
    assert differences == []


def test_in_window_event_still_requires_exact_candle_parity():
    module = _load_script()
    with pytest.raises(ValueError, match="AUDIT_EVENT_MINUTE_UNAVAILABLE"):
        module.audit_parity(
            date(2026, 10, 1),
            [_row("2026-10-01T12:10:00+05:30")],
            {},
            {},
        )


def test_post_cutoff_event_still_must_pass_observation_safety():
    module = _load_script()
    minute = datetime(2026, 10, 1, 12, 10, tzinfo=IST)
    with pytest.raises(ValueError, match="LIVE_AUDIT_SAFETY_MISMATCH"):
        module.audit_parity(
            date(2026, 10, 1),
            [
                _row("2026-10-01T12:10:00+05:30"),
                _row(
                    "2026-10-01T15:15:00+05:30",
                    event_type="SESSION_END_UNRESOLVED",
                    execution_enabled=True,
                ),
            ],
            {minute: {"close": 22500.0}},
            {minute: {"close": 22520.0, "vwap": 22515.0}},
        )
