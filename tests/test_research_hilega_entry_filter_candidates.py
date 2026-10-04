from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/research_hilega_entry_filter_candidates.py"
)
SPEC = importlib.util.spec_from_file_location("hilega_entry_filters", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def trade(**updates):
    row = {
        "session_date": "2026-01-01",
        "split": "IS",
        "direction": "BULLISH",
        "route": "ROUTE_A",
        "captured_points": 10.0,
        "mfe_points": 30.0,
        "mae_points": -5.0,
        "giveback_points": 20.0,
        "entry_rsi9": 60.0,
        "entry_ema_minus_wma": 4.0,
        "entry_rsi9_slope_3": 1.0,
        "entry_ema3_rsi_slope_3": 0.8,
        "entry_wma21_rsi_slope_3": 0.4,
        "entry_ema_minus_wma_slope_3": 0.3,
    }
    row.update(updates)
    return m.enrich(row)


def test_bearish_values_are_direction_normalized():
    row = trade(
        direction="BEARISH",
        entry_rsi9=40.0,
        entry_ema_minus_wma=-4.0,
        entry_rsi9_slope_3=-1.0,
        entry_ema3_rsi_slope_3=-0.8,
        entry_wma21_rsi_slope_3=-0.4,
        entry_ema_minus_wma_slope_3=-0.3,
    )
    assert row["rsi_directional_level"] == 10.0
    assert row["ema_wma_directional_gap"] == 4.0
    assert row["wma_directional_slope"] == 0.4


def test_flat_warning_is_inclusive_at_boundary():
    decision = m.evaluate_entry(trade(entry_wma21_rsi_slope_3=0.10))
    assert decision["wma_flat_warning"] is True


def test_alignment_requires_all_five_support_checks():
    good = m.evaluate_entry(trade())
    weak = m.evaluate_entry(trade(entry_rsi9_slope_3=0.0))
    assert good["alignment_support_count"] == 5
    assert good["large_gain_alignment_keep"] is True
    assert weak["alignment_support_count"] == 4
    assert weak["large_gain_alignment_keep"] is False


def test_flat_confirmation_needs_flat_and_two_weak_components():
    one_weak = m.evaluate_entry(trade(
        entry_wma21_rsi_slope_3=0.05,
        entry_rsi9_slope_3=-0.1,
    ))
    two_weak = m.evaluate_entry(trade(
        entry_wma21_rsi_slope_3=0.05,
        entry_rsi9_slope_3=-0.1,
        entry_ema3_rsi_slope_3=-0.1,
    ))
    not_flat = m.evaluate_entry(trade(
        entry_wma21_rsi_slope_3=0.2,
        entry_rsi9_slope_3=-0.1,
        entry_ema3_rsi_slope_3=-0.1,
    ))
    assert one_weak["flat_confirmation_reject"] is False
    assert two_weak["flat_confirmation_reject"] is True
    assert not_flat["flat_confirmation_reject"] is False


def test_frozen_large_threshold_is_learned_from_is_only():
    rows = [trade(mfe_points=float(value)) for value in range(1, 11)]
    rows += [trade(split="OOS", mfe_points=10_000.0)]
    rows += [trade(
        direction="BEARISH",
        entry_rsi9=40.0,
        entry_ema_minus_wma=-4.0,
        entry_rsi9_slope_3=-1.0,
        entry_ema3_rsi_slope_3=-0.8,
        entry_wma21_rsi_slope_3=-0.4,
        entry_ema_minus_wma_slope_3=-0.3,
        mfe_points=float(value),
    ) for value in range(1, 11)]
    thresholds = m.learn_large_thresholds(rows)
    assert thresholds == {"BULLISH": 9.1, "BEARISH": 9.1}


def test_filtered_trade_contributes_zero_and_negative_rejection_improves_points():
    rows = [
        trade(captured_points=10.0),
        trade(
            captured_points=-8.0,
            entry_wma21_rsi_slope_3=0.05,
            entry_rsi9_slope_3=-0.1,
            entry_ema3_rsi_slope_3=-0.1,
        ),
    ]
    thresholds = {"BULLISH": 20.0, "BEARISH": 20.0}
    m.apply_rules(rows, thresholds)
    summary = m.candidate_summary(rows, thresholds)
    result = next(row for row in summary if (
        row["split"] == "IS"
        and row["direction"] == "BULLISH"
        and row["candidate"] == "FLAT_WMA_CONFIRMATION_FILTER"
    ))
    assert result["baseline_total_points"] == 2.0
    assert result["total_points"] == 10.0
    assert result["point_delta_vs_control"] == 8.0


def test_flat_warning_never_changes_candidate_selection():
    row = trade(entry_wma21_rsi_slope_3=0.05)
    row.update(m.evaluate_entry(row))
    assert row["wma_flat_warning"] is True
    assert m.candidate_keeps(row, "CONTROL_CURRENT_POLICY") is True


def test_maximum_drawdown_is_chronological():
    assert m.maximum_drawdown([10.0, -4.0, -8.0, 3.0]) == 12.0
