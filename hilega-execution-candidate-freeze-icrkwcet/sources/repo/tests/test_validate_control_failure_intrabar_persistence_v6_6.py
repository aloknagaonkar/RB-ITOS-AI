from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

P = Path(__file__).resolve().parents[1] / "scripts" / "validate_control_failure_intrabar_persistence_v6_6.py"
spec = importlib.util.spec_from_file_location("v66", P)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_directional_value_is_symmetric():
    assert m.directional_value("BULLISH", 7.5) == 7.5
    assert m.directional_value("BEARISH", 7.5) == -7.5
    assert m.directional_value("BEARISH", -7.5) == 7.5


def test_max_consecutive_true_counts_adjacent_failures_only():
    assert m.max_consecutive_true([True, True, False, True, False]) == 2
    assert m.max_consecutive_true([False, False]) == 0
    assert m.max_consecutive_true([True, True, True]) == 3


def test_breadth_support_is_directional_and_strict():
    assert m.breadth_supportive("BULLISH", 4, 2) is True
    assert m.breadth_supportive("BULLISH", 2, 2) is False
    assert m.breadth_supportive("BEARISH", 2, 4) is True
    assert m.breadth_supportive("BEARISH", 4, 2) is False


def test_outcome_group_uses_sign_only_not_optimized_thresholds():
    assert m.outcome_group(1.0, 2.0) == "POSITIVE_15_AND_30"
    assert m.outcome_group(-1.0, 2.0) == "MIXED_15_30"
    assert m.outcome_group(1.0, -2.0) == "MIXED_15_30"
    assert m.outcome_group(-1.0, -2.0) == "NON_POSITIVE_15_AND_30"
