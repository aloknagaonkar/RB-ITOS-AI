from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_forward_outcome_v2_2 import (
    opening_status,
    outcome_for_signal,
)

IST = ZoneInfo("Asia/Kolkata")


def b(h, m, o, hi, lo, c):
    return {
        "start": datetime(2026, 9, 21, h, m, tzinfo=IST),
        "open": o,
        "high": hi,
        "low": lo,
        "close": c,
    }


def test_opening_confirmed():
    assert opening_status(70, 60, 55, 65, 56, 62, 57) == "OPENING_BULLISH_CONFIRMED"


def test_opening_rejected_0925():
    assert opening_status(70, 60, 55, 65, 56, 54, 56) == "OPENING_REJECTED_0925"


def test_forward_outcome_math():
    bars = [
        b(9,25,100,101,99,100),
        b(9,30,100,103,99,102),
        b(9,35,102,106,101,105),
        b(9,40,105,105,98,99),
    ]
    out = outcome_for_signal(bars, 0, end_index=3)
    assert out["move_5m_points"] == 2
    assert out["move_10m_points"] == 5
    assert out["mfe_points_to_end"] == 6
    assert out["mae_points_to_end"] == -2
    assert out["move_to_end_points"] == -1


def test_missing_long_horizon_is_blank():
    bars = [
        b(15,20,100,101,99,100),
        b(15,25,100,102,99,101),
    ]
    out = outcome_for_signal(bars, 0, end_index=None)
    assert out["close_10m"] == ""
    assert out["move_60m_points"] == ""
