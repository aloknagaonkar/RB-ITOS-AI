from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_hilega_alignment_points_490.py"
SPEC = importlib.util.spec_from_file_location("hilega_alignment_points", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def feature(**updates):
    row = {
        "rsi9": 60.0,
        "ema_minus_wma": 4.0,
        "rsi9_slope_3": 1.0,
        "ema3_rsi_slope_3": 0.8,
        "wma21_rsi_slope_3": 0.4,
        "ema_minus_wma_slope_3": 0.3,
    }
    row.update(updates)
    return row


def test_fully_aligned_bullish_is_healthy():
    result = m.health_components(feature(), "BULLISH", epsilon=0.10)
    assert result["health"] == "HEALTHY_ALIGNED"
    assert result["support_count"] == 5
    assert result["wma_state"] == "UP"
    assert result["gap_state"] == "DIRECTIONAL_WIDENING"


def test_fully_aligned_bearish_is_healthy():
    result = m.health_components(
        feature(
            rsi9=38.0,
            ema_minus_wma=-5.0,
            rsi9_slope_3=-1.0,
            ema3_rsi_slope_3=-0.8,
            wma21_rsi_slope_3=-0.4,
            ema_minus_wma_slope_3=-0.3,
        ),
        "BEARISH",
        epsilon=0.10,
    )
    assert result["health"] == "HEALTHY_ALIGNED"
    assert result["support_count"] == 5
    assert result["wma_state"] == "DOWN"


def test_flat_wma_is_wait_not_reversal_by_itself():
    result = m.health_components(
        feature(wma21_rsi_slope_3=0.02), "BULLISH", epsilon=0.10
    )
    assert result["health"] == "WMA_FLAT_WAIT"
    assert result["reversal_risk"] is False


def test_reversal_risk_requires_joint_adverse_evidence():
    result = m.health_components(
        feature(
            rsi9=54.0,
            rsi9_slope_3=-0.8,
            ema3_rsi_slope_3=-0.5,
            wma21_rsi_slope_3=0.02,
            ema_minus_wma_slope_3=-0.4,
        ),
        "BULLISH",
        epsilon=0.10,
    )
    assert result["health"] == "REVERSAL_RISK"
    assert result["reversal_risk"] is True


def test_directional_points_are_normalized():
    assert m.directional_points("BULLISH", 100.0, 112.0) == 12.0
    assert m.directional_points("BEARISH", 100.0, 88.0) == 12.0


def test_excursion_ignores_pre_entry_candle_by_call_contract():
    active = m.ActiveTrade(
        trade_id="x",
        session_date="2026-01-01",
        direction="BEARISH",
        route="ROUTE_A",
        entry_event="ENTRY",
        entry_timestamp=__import__("datetime").datetime.fromisoformat(
            "2026-01-01T10:00:00+05:30"
        ),
        entry_price=100.0,
        entry_features={},
    )
    m.update_excursion(active, 104.0, 88.0)
    assert active.mfe_points == 12.0
    assert active.mae_points == -4.0


def test_metrics_include_point_and_risk_outputs():
    rows = [
        {
            "captured_points": 20.0,
            "mfe_points": 30.0,
            "mae_points": -5.0,
            "giveback_points": 10.0,
            "reached_plus10": True,
            "reached_plus20": True,
        },
        {
            "captured_points": -10.0,
            "mfe_points": 4.0,
            "mae_points": -15.0,
            "giveback_points": 14.0,
            "reached_plus10": False,
            "reached_plus20": False,
        },
    ]
    result = m.metrics(rows)
    assert result["total_points"] == 10.0
    assert result["mean_points"] == 5.0
    assert result["profit_factor"] == 2.0
    assert result["plus20_rate_pct"] == 50.0
    assert result["max_drawdown_points"] == 10.0
