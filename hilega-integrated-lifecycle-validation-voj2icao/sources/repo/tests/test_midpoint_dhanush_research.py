import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT = Path("scripts/midpoint_dhanush_historical_scan.py")
SPEC = importlib.util.spec_from_file_location("midpoint_dhanush_test_module", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def bar(minute, *, high, low, close):
    start = datetime.fromisoformat("2026-08-25T10:00:00+05:30") + timedelta(
        minutes=minute
    )
    return MODULE.FiveMinuteBar(start, start + timedelta(minutes=4), close, high, low, close)


def test_third_distinct_attempt_close_cross_confirms_dhanush():
    detector = MODULE.DhanushDetector(100.0, "BEARISH", 10.0)
    sequence = [
        bar(0, high=95, low=80, close=85),
        bar(5, high=85, low=75, close=80),
        bar(10, high=92, low=80, close=88),
        bar(15, high=85, low=75, close=80),
        bar(20, high=98, low=85, close=95),
        bar(25, high=105, low=92, close=102),
    ]
    results = [detector.observe(value) for value in sequence]
    assert results == [False, False, False, False, False, True]
    assert len(detector.attempts) == 3


def test_adjacent_zone_bars_are_one_attempt_not_multiple_touches():
    detector = MODULE.DhanushDetector(100.0, "BEARISH", 10.0)
    detector.observe(bar(0, high=92, low=80, close=85))
    detector.observe(bar(5, high=97, low=82, close=88))
    detector.observe(bar(10, high=94, low=81, close=87))
    assert len(detector.attempts) == 1


def test_cross_before_third_attempt_disqualifies_pattern():
    detector = MODULE.DhanushDetector(100.0, "BEARISH", 10.0)
    assert detector.observe(bar(0, high=105, low=90, close=101)) is False
    assert detector.failed_early_cross is True
    assert detector.observe(bar(5, high=80, low=70, close=75)) is False


def test_bullish_origin_is_symmetric():
    detector = MODULE.DhanushDetector(100.0, "BULLISH", 10.0)
    sequence = [
        bar(0, high=120, low=105, close=115),
        bar(5, high=125, low=115, close=120),
        bar(10, high=120, low=108, close=112),
        bar(15, high=125, low=115, close=120),
        bar(20, high=115, low=102, close=105),
        bar(25, high=108, low=95, close=98),
    ]
    assert [detector.observe(value) for value in sequence][-1] is True
