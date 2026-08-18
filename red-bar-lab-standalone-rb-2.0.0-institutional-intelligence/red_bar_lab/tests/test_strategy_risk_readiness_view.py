from __future__ import annotations

from red_bar_lab.ui.strategy_risk_readiness_view import _display_value


def test_display_value_serializes_nested_values_for_arrow_tables():
    assert _display_value([]) == "[]"
    assert _display_value({"RSI": {"consumed": 10.0}}) == '{"RSI": {"consumed": 10.0}}'
    assert _display_value(("A", "B")) == '["A", "B"]'


def test_display_value_normalizes_scalars_to_one_text_column():
    assert _display_value(10000.0) == "10000.0"
    assert _display_value(False) == "False"
    assert _display_value(None) == ""
