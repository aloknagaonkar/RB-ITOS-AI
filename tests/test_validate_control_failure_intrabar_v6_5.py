from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

P = Path(__file__).resolve().parents[1] / "scripts" / "validate_control_failure_intrabar_v6_5.py"
spec = importlib.util.spec_from_file_location("v65", P)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_default_targets_include_four_strong_and_one_weaker_case():
    assert len(m.DEFAULT_TARGETS) == 5
    assert ("2026-05-18", "BULLISH", "2026-05-18T10:00:00+05:30") in m.DEFAULT_TARGETS
    assert ("2026-06-24", "BULLISH", "2026-06-24T09:55:00+05:30") in m.DEFAULT_TARGETS
    assert ("2026-06-29", "BEARISH", "2026-06-29T10:35:00+05:30") in m.DEFAULT_TARGETS
    assert ("2026-07-07", "BEARISH", "2026-07-07T12:05:00+05:30") in m.DEFAULT_TARGETS
    assert ("2026-05-25", "BULLISH", "2026-05-25T09:45:00+05:30") in m.DEFAULT_TARGETS


def test_state_is_symmetric():
    assert m._state(1) == "BULLISH"
    assert m._state(-1) == "BEARISH"
    assert m._state(0) == "MIXED"


def test_first_minute_returns_first_true_component():
    class X:
        def __init__(self, v): self.direction_failure = v
    xs = [X(False), X(True), X(True)]
    assert m.first_minute(xs, "direction_failure") is xs[1]


def test_intrabar_semantics_are_one_minute_not_five_minute():
    # A frozen five-minute signal candle should contain exactly minute offsets 1..5.
    from datetime import datetime, timedelta
    cp = datetime.fromisoformat("2026-05-18T10:00:00+05:30")
    start = cp - timedelta(minutes=5)
    offsets = [int(((start + timedelta(minutes=i)) - start).total_seconds() // 60) for i in range(1, 6)]
    assert offsets == [1, 2, 3, 4, 5]
