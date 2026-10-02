from datetime import datetime

from market_lab.midpoint_arm_d_5m_close_comparison_v1 import (
    aligned,
    candle_minutes_for_checkpoint,
    next_5m_boundary_after,
)


def ts(s):
    return datetime.fromisoformat(s)


def test_next_5m_boundary_after_0922_is_0925():
    assert next_5m_boundary_after(
        ts("2026-09-15T09:22:00+05:30")
    ).isoformat() == "2026-09-15T09:25:00+05:30"


def test_break_exactly_at_0925_waits_for_next_completed_candle():
    assert next_5m_boundary_after(
        ts("2026-09-15T09:25:00+05:30")
    ).isoformat() == "2026-09-15T09:30:00+05:30"


def test_checkpoint_0925_uses_only_0920_through_0924():
    keys = candle_minutes_for_checkpoint(
        ts("2026-09-15T09:25:00+05:30")
    )
    assert keys[0] == "2026-09-15T09:20:00+05:30"
    assert keys[-1] == "2026-09-15T09:24:00+05:30"
    assert len(keys) == 5


def test_bearish_alignment():
    p = {"ce_state": "SHORT_BUILDUP", "pe_state": "LONG_BUILDUP"}
    f = {"futures_close": 23497.0, "futures_vwap": 23526.97}
    assert aligned("BEARISH", p, f) is True


def test_bullish_alignment():
    p = {"ce_state": "LONG_BUILDUP", "pe_state": "SHORT_BUILDUP"}
    f = {"futures_close": 23550.0, "futures_vwap": 23520.0}
    assert aligned("BULLISH", p, f) is True


def test_wrong_vwap_side_rejects():
    p = {"ce_state": "SHORT_BUILDUP", "pe_state": "LONG_BUILDUP"}
    f = {"futures_close": 23530.0, "futures_vwap": 23520.0}
    assert aligned("BEARISH", p, f) is False
