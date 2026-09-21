from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_oi_price_failure_transition_v4.py"
spec = spec_from_file_location("v4", SCRIPT)
mod = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

IST = timezone.utc  # timezone offset is irrelevant to these focused logic tests


def breadth(time, imbalance, velocity, bull, bear, atm="BEARISH", phase="PRE_HISTORY"):
    return {
        "time": time,
        "phase": phase,
        "fixed_atm": "23350",
        "bullish_count": str(bull),
        "bearish_count": str(bear),
        "atm_state": atm,
        "aggregate_imbalance": str(imbalance),
        "aggregate_imbalance_velocity": "" if velocity is None else str(velocity),
    }


def spot(time, value):
    dt = datetime.fromisoformat(f"2026-09-21T{time}:00+05:30")
    return {
        "checkpoint": dt.isoformat(),
        "checkpoint_dt": dt,
        "spot": value,
        "moving_atm": 23350,
        "all3_state": "BEARISH_ALL_3",
    }


def test_1035_fading_reversal_and_dated_candle_window():
    b = [
        breadth("10:30", -4_053_000, -2_397_000, 0, 5),
        breadth("10:35", -1_530_000, 2_523_000, 0, 5, phase="PRE_EVENT_BASELINE"),
    ]
    s = {"10:30": spot("10:30", 23372.75), "10:35": spot("10:35", 23363.35)}
    rows = mod.analyze(b, s, session_date="2026-09-21")
    r = rows[1]
    assert r["transition_phase"] == "BEARISH_FADING_REVERSAL"
    assert r["aggregate_imbalance_acceleration"] == 4_920_000
    assert r["candle_start"].startswith("2026-09-21T10:30:00")
    assert r["candle_end"].startswith("2026-09-21T10:35:00")


def test_1040_bearish_oi_with_up_price_is_failed_response():
    b = [
        breadth("10:35", -1_530_000, 2_523_000, 0, 5, phase="PRE_EVENT_BASELINE"),
        breadth("10:40", -3_231_000, -1_702_000, 0, 5, phase="EVENT"),
    ]
    s = {"10:35": spot("10:35", 23363.35), "10:40": spot("10:40", 23366.25)}
    rows = mod.analyze(b, s, session_date="2026-09-21")
    r = rows[1]
    assert r["price_direction"] == "UP"
    assert r["oi_direction"] == "BEARISH"
    assert r["oi_price_response"] == "FAILED_BEARISH_RESPONSE"
    assert r["transition_phase"] == "PRICE_OI_DIVERGENCE"
    assert r["candle_start"].startswith("2026-09-21T10:35:00")
    assert r["candle_end"].startswith("2026-09-21T10:40:00")


def test_1050_early_transition_requires_atm_and_breadth():
    b = [
        breadth("10:45", -3_070_000, 161_000, 0, 5, phase="POST_EVENT"),
        breadth("10:50", -232_000, 2_838_000, 2, 3, atm="BULLISH", phase="POST_EVENT"),
    ]
    s = {"10:45": spot("10:45", 23379.85), "10:50": spot("10:50", 23378.30)}
    rows = mod.analyze(b, s, session_date="2026-09-21")
    assert rows[1]["transition_phase"] == "EARLY_BULL_TRANSITION"
