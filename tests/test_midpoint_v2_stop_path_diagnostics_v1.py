from datetime import datetime, timedelta

from market_lab.midpoint_v2_stop_path_diagnostics_v1 import diagnose_trade


def _trade():
    return {
        "block": "TRAIN",
        "session_date": "2026-01-01",
        "entry_arm": "FAILED_BREAK_RECLAIM",
        "entry_direction": "BULLISH",
        "instrument_key": "X",
        "entry_timestamp": "2026-01-01T09:30:00+05:30",
        "entry_price": 100.0,
    }


def _series(bars):
    start = datetime.fromisoformat("2026-01-01T09:30:00+05:30")
    out = {}
    for i, (o, h, l, c) in enumerate(bars):
        ts = (start + timedelta(minutes=i)).isoformat()
        out[ts] = {"timestamp": ts, "open": o, "high": h, "low": l, "close": c}
    return out


def test_stop_then_recovery_is_detected_without_intrabar_order_guess():
    bars = [(100, 101, 99, 100), (100, 101, 94, 95), (96, 106, 96, 104)] + [(104, 104, 100, 103)] * 13
    r = diagnose_trade(_trade(), _series(bars))
    assert r["stop5_hit"] is True
    assert r["stop5_hit_minute"] == 1
    assert r["recovered_to_entry_after_stop"] is True
    assert r["reached_plus5_after_stop"] is True


def test_same_stop_bar_plus5_is_marked_ambiguous_not_counted_as_after_stop():
    bars = [(100, 106, 94, 100)] + [(99, 99, 98, 98)] * 15
    r = diagnose_trade(_trade(), _series(bars))
    assert r["stop5_hit"] is True
    assert r["same_stop_bar_order_ambiguous_for_plus5"] is True
    assert r["reached_plus5_after_stop"] is False


def test_no_stop_has_null_post_stop_fields():
    bars = [(100, 104, 98, 102)] * 16
    r = diagnose_trade(_trade(), _series(bars))
    assert r["stop5_hit"] is False
    assert r["recovered_to_entry_after_stop"] is None
