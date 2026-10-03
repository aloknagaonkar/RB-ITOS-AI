from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_hilega_large_gain_signatures.py"
SPEC = importlib.util.spec_from_file_location("hilega_large_gain", SCRIPT)
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
        "mfe_points": 25.0,
        "mae_points": -5.0,
        "giveback_points": 15.0,
        "entry_rsi9": 60.0,
        "entry_ema3_rsi": 57.0,
        "entry_wma21_rsi": 53.0,
        "entry_ema_minus_wma": 4.0,
        "entry_rsi9_slope_3": 1.0,
        "entry_ema3_rsi_slope_3": 0.8,
        "entry_wma21_rsi_slope_3": 0.4,
        "entry_ema_minus_wma_slope_3": 0.3,
    }
    row.update(updates)
    return m.enrich(row)


def test_percentile_interpolates():
    assert m.percentile([0, 10], 0.5) == 5
    assert m.percentile([1], 0.9) == 1


def test_bearish_features_are_direction_normalized():
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


def test_unavailable_feature_can_be_enriched_before_exclusion():
    row = trade(entry_wma21_rsi_slope_3="")
    assert row["entry_wma21_rsi_slope_3"] is None
    assert row["wma_directional_slope"] is None


def test_primary_flat_filter_rejects_absolute_slope_at_boundary():
    rows = [
        trade(entry_wma21_rsi_slope_3=0.10, captured_points=-8.0),
        trade(entry_wma21_rsi_slope_3=0.11, captured_points=12.0),
    ]
    output = m.flat_sensitivity(rows, {"BULLISH": 20.0, "BEARISH": 20.0})
    primary = next(
        row for row in output
        if row["epsilon"] == 0.10
        and row["split"] == "IS"
        and row["direction"] == "BULLISH"
    )
    assert primary["rejected_trades"] == 1
    assert primary["kept_trades"] == 1
    assert primary["counterfactual_point_delta"] == 8.0


def test_flat_oos_large_move_uses_frozen_is_threshold():
    rows = [
        trade(split="OOS", mfe_points=30.0, entry_wma21_rsi_slope_3=0.05),
        trade(split="OOS", mfe_points=1000.0, entry_wma21_rsi_slope_3=0.50),
    ]
    output = m.flat_sensitivity(
        rows, {"BULLISH": 20.0, "BEARISH": 20.0}
    )
    primary = next(
        row for row in output
        if row["epsilon"] == 0.10
        and row["split"] == "OOS"
        and row["direction"] == "BULLISH"
    )
    assert primary["large_mfe_threshold"] == 20.0
    assert primary["large_moves"] == 2
    assert primary["large_moves_rejected"] == 1


def test_large_threshold_is_learned_only_from_is():
    rows = [
        trade(mfe_points=float(value)) for value in range(1, 11)
    ] + [
        trade(
            split="OOS", direction="BULLISH", mfe_points=10_000.0
        )
    ] + [
        trade(
            direction="BEARISH",
            entry_rsi9=40.0,
            entry_ema_minus_wma=-4.0,
            entry_rsi9_slope_3=-1.0,
            entry_ema3_rsi_slope_3=-0.8,
            entry_wma21_rsi_slope_3=-0.4,
            entry_ema_minus_wma_slope_3=-0.3,
            mfe_points=float(value),
        ) for value in range(1, 11)
    ]
    thresholds = m.large_thresholds(rows)
    assert thresholds["BULLISH"] == 9.1
    assert thresholds["BEARISH"] == 9.1


def test_sweet_spot_requires_directional_wma_and_four_ranges():
    profile = {
        feature: {"minimum": 0.0, "maximum": 20.0, "median": 5.0}
        for feature in m.DIRECTIONAL_FEATURES
    }
    rows = [trade()]
    validation = m.validate_sweet_spots(
        rows, {"BULLISH": profile, "BEARISH": profile}, {"BULLISH": 20, "BEARISH": 20}
    )
    assert rows[0]["sweet_spot_selected"] is True
    assert validation[0]["trades"] == 1


def test_metrics_include_profit_factor_and_drawdown():
    result = m.metrics([
        trade(captured_points=20.0),
        trade(captured_points=-10.0),
    ])
    assert result["total_points"] == 10.0
    assert result["profit_factor"] == 2.0
    assert result["max_drawdown_points"] == 10.0
