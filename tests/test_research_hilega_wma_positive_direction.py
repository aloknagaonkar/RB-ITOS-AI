from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/research_hilega_wma_positive_direction.py"
)
SPEC = importlib.util.spec_from_file_location("hilega_wma_direction", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def trade(**updates):
    row = {
        "session_date": "2026-01-01",
        "direction": "BULLISH",
        "route": "ROUTE_B",
        "captured_points": 10.0,
        "mfe_points": 30.0,
        "mae_points": -5.0,
        "giveback_points": 20.0,
        "entry_rsi9": 60.0,
        "entry_ema_minus_wma": 3.0,
        "entry_rsi9_slope_3": 1.0,
        "entry_ema3_rsi_slope_3": 0.8,
        "entry_wma21_rsi_slope_3": 0.4,
        "entry_ema_minus_wma_slope_3": 0.3,
    }
    row.update(updates)
    return m.enrich(row)


def test_bearish_features_are_normalized_to_positive_support():
    row = trade(
        direction="BEARISH",
        entry_rsi9=40.0,
        entry_ema_minus_wma=-3.0,
        entry_rsi9_slope_3=-1.0,
        entry_ema3_rsi_slope_3=-0.8,
        entry_wma21_rsi_slope_3=-0.4,
        entry_ema_minus_wma_slope_3=-0.3,
    )
    assert row["rsi_directional_level"] == 10.0
    assert row["gap_directional_level"] == 3.0
    assert row["wma_directional_slope"] == 0.4
    assert row["gap_directional_slope"] == 0.3


def test_slope_bands_have_deterministic_boundaries():
    assert m.slope_band(-0.1) == "ADVERSE_OR_ZERO"
    assert m.slope_band(0.0) == "ADVERSE_OR_ZERO"
    assert m.slope_band(0.10) == "WEAK_0_TO_010"
    assert m.slope_band(0.25) == "MILD_010_TO_025"
    assert m.slope_band(0.50) == "MODERATE_025_TO_050"
    assert m.slope_band(0.75) == "STRONG_050_TO_075"
    assert m.slope_band(1.00) == "VERY_STRONG_075_TO_100"
    assert m.slope_band(1.01) == "EXTREME_GT_100"


def test_wma_rising_is_not_sufficient_for_confirmed_profile():
    losing_example = trade(
        entry_rsi9=44.94,
        entry_ema_minus_wma=0.39,
        entry_wma21_rsi_slope_3=0.57,
        entry_ema_minus_wma_slope_3=-0.31,
    )
    assert m.profile_keep(losing_example, "WMA_ONLY", 0.50) is True
    assert m.profile_keep(
        losing_example, "WMA_RSI50_GAP_EXPANDING", 0.10
    ) is False


def test_full_alignment_requires_rsi_and_ema_slopes_too():
    assert m.profile_keep(trade(), "FULL_DIRECTIONAL_ALIGNMENT", 0.10)
    assert not m.profile_keep(
        trade(entry_ema3_rsi_slope_3=-0.1),
        "FULL_DIRECTIONAL_ALIGNMENT",
        0.10,
    )


def test_chronological_split_is_recomputed_without_source_split():
    rows = []
    for index in range(10):
        rows.append(trade(session_date=f"2026-01-{index + 1:02d}"))
    universe = m.assign_chronological_splits(
        rows, forward_sessions=2, is_ratio=0.75
    )
    assert universe["frozen"] == 8
    assert universe["is"] == 6
    assert universe["oos"] == 2
    assert universe["forward"] == 2
    assert [row["research_split"] for row in rows] == (
        ["IS"] * 6 + ["OOS"] * 2 + ["FORWARD"] * 2
    )


def test_metrics_measure_plus20_and_immediate_failure():
    rows = [
        trade(captured_points=10.0, mfe_points=25.0),
        trade(captured_points=-8.0, mfe_points=2.0),
    ]
    result = m.metrics(rows)
    assert result["total_points"] == 2.0
    assert result["plus20_rate_pct"] == 50.0
    assert result["immediate_failure_rate_pct"] == 50.0


def test_is_ranking_does_not_use_oos_to_select():
    scan = []
    for split, points in (("IS", 100.0), ("OOS", -1000.0), ("FORWARD", -500.0)):
        scan.append({
            "split": split,
            "direction": "BULLISH",
            "profile": "WMA_ONLY",
            "wma_directional_slope_gt": 0.10,
            "trades": 60,
            "total_points": points,
            "mean_points": points / 60,
            "win_rate_pct": 50.0,
            "profit_factor": 1.2 if split == "IS" else 0.5,
            "plus20_rate_pct": 40.0,
            "selection_rate_pct": 20.0,
        })
    ranked = m.rank_is_profiles(scan)
    assert len(ranked) == 1
    assert ranked[0]["is_rank_within_direction"] == 1
    assert ranked[0]["selection_basis"] == "IS_ONLY"
    assert ranked[0]["oos_total_points"] == -1000.0

