from market_lab.midpoint_oi_vwap_intraday_validation_v1 import (
    confluence_direction, floor_5m, round_atm, state
)
from datetime import datetime


def test_round_atm():
    assert round_atm(23327.05) == 23350.0


def test_floor_5m_no_forward_peek():
    ts = datetime.fromisoformat("2026-09-15T09:28:00+05:30")
    assert floor_5m(ts).isoformat() == "2026-09-15T09:25:00+05:30"


def test_positioning_states():
    assert state(105, 100, 110, 100, 0.0, 0.0) == "LONG_BUILDUP"
    assert state(95, 100, 110, 100, 0.0, 0.0) == "SHORT_BUILDUP"
    assert state(95, 100, 90, 100, 0.0, 0.0) == "LONG_UNWINDING"
    assert state(105, 100, 90, 100, 0.0, 0.0) == "SHORT_COVERING"


def test_confluence():
    assert confluence_direction("LONG_BUILDUP", "SHORT_BUILDUP", 101, 100) == "BULLISH"
    assert confluence_direction("SHORT_BUILDUP", "LONG_BUILDUP", 99, 100) == "BEARISH"
    assert confluence_direction("LONG_BUILDUP", "SHORT_BUILDUP", 99, 100) == "NEUTRAL"
