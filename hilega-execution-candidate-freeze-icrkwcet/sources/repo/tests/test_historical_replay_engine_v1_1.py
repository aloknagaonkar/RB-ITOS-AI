from datetime import datetime
from types import SimpleNamespace

from market_lab.domain import IST
from market_lab.historical_replay_day_v1_1 import _next_due_for_state


def dt(h, m):
    return datetime(2026, 9, 18, h, m, tzinfo=IST)


def state(**kwargs):
    defaults = dict(
        status="DETECTED",
        confirmation_timestamp=None,
        entry_timestamp=None,
        last_bar_timestamp=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_option_resolved_first_runtime_due_is_confirmation_plus_2m():
    s = state(
        status="OPTION_RESOLVED",
        confirmation_timestamp=dt(10, 0).isoformat(),
    )
    assert _next_due_for_state(s, dt(10, 0)) == dt(10, 2)


def test_option_resolved_retries_next_minute_if_still_unresolved():
    s = state(
        status="OPTION_RESOLVED",
        confirmation_timestamp=dt(10, 0).isoformat(),
    )
    assert _next_due_for_state(s, dt(10, 2)) == dt(10, 3)


def test_open_first_option_bar_due_two_minutes_after_entry_label():
    s = state(
        status="OPEN",
        entry_timestamp=dt(10, 1).isoformat(),
    )
    assert _next_due_for_state(s, dt(10, 1)) == dt(10, 3)


def test_open_next_bar_due_from_last_processed_bar():
    s = state(
        status="OPEN",
        entry_timestamp=dt(10, 1).isoformat(),
        last_bar_timestamp=dt(10, 2).isoformat(),
    )
    assert _next_due_for_state(s, dt(10, 2)) == dt(10, 4)


def test_final_state_has_no_runtime_due():
    s = state(status="CLOSED")
    assert _next_due_for_state(s, dt(10, 5)) is None
