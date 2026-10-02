from __future__ import annotations

import importlib.util
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "scripts" / "validate_control_failure_component_timestamp_v6_4.py"
spec = importlib.util.spec_from_file_location("v64", P)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_lead_lag_is_component_minus_move_start():
    assert mod.lead_lag_minutes("2026-09-21T10:35:00+05:30", "10:40") == -5.0
    assert mod.lead_lag_minutes("2026-09-21T10:45:00+05:30", "10:40") == 5.0


def test_move_inside_signal_candle_is_explicit():
    assert mod.candle_relation(
        "2026-09-21T10:35:00+05:30",
        "2026-09-21T10:40:00+05:30",
        "10:35",
    ) == "MOVE_INSIDE_SIGNAL_CANDLE"


def test_earliest_component_uses_timestamp_not_label():
    name, ll = mod.earliest_component(
        "2026-09-21T10:35:00+05:30",
        "2026-09-21T10:40:00+05:30",
        "10:40",
    )
    assert name == "FAILURE"
    assert ll == -5.0


def test_same_candle_components_have_same_timing():
    assert mod.component_order_timing(5.0, 5.0) == "SAME_CANDLE"
