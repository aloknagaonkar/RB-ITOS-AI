from datetime import datetime, timedelta

from market_lab.midpoint_v2_exit_duration_comparison_v1 import (
    POLICIES,
    replay_trade,
)


def _trade():
    return {
        "block": "TRAIN",
        "session_date": "2026-01-01",
        "entry_arm": "FAILED_BREAK_RECLAIM",
        "entry_direction": "BULLISH",
        "instrument_key": "X",
        "entry_timestamp": "2026-01-01T09:30:00+05:30",
        "entry_price": 100.0,
        "mfe_pct_15m": 20.0,
    }


def _series(values):
    out = {}
    start = datetime.fromisoformat("2026-01-01T09:30:00+05:30")
    for minute, (o, h, l, c) in enumerate(values):
        ts = (start + timedelta(minutes=minute)).isoformat()
        out[ts] = {
            "timestamp": ts,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        }
    return out


def test_frozen_initial_stop_touch():
    vals = [(100, 101, 94, 95)] + [(95, 95, 95, 95)] * 60
    r = replay_trade(_trade(), _series(vals), "E15")
    assert r["exit_reason"] == "STOP_TOUCH"
    assert r["exit_price"] == 95.0


def test_breakeven_activates_next_bar():
    vals = [(100, 106, 99, 105), (100, 101, 99, 100)] + [(100, 100, 100, 100)] * 59
    r = replay_trade(_trade(), _series(vals), "E15")
    assert r["exit_timestamp"] == "2026-01-01T09:31:00+05:30"
    assert r["exit_price"] == 100.0


def test_hybrid_continues_when_trail_already_active():
    vals = [(100, 112, 99, 111)]
    for i in range(1, 61):
        base = 112 + i
        vals.append((base, base + 1, base - 0.5, base + 0.5))
    r = replay_trade(_trade(), _series(vals), "HYBRID")
    assert r["duration_minutes"] > 15


def test_policy_set_is_predeclared():
    assert set(POLICIES) == {"E15", "HYBRID", "E20", "E30", "TRAIL_ONLY"}
