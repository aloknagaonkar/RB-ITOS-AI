import json
from pathlib import Path

from market_lab.pcr_option_candidate_policy import analyze


def _trade(direction, tier, timing, result, ret15=0.0):
    return {
        "direction": direction,
        "confidence_tier": tier,
        "confirmation_offset_group": timing,
        "returns_pct": {"15m": ret15},
        "target_stop": {"TARGET_5_STOP_10": {"result": result}},
    }


def test_frozen_timing_and_cost_sensitivity(tmp_path: Path):
    src = {
        "status": "AVAILABLE",
        "entry_rule": "NEXT_MINUTE_OPEN",
        "trades": [
            _trade("BEARISH", "HIGH", "T0", "TARGET_FIRST"),
            _trade("BEARISH", "VERY_HIGH", "T_PLUS_2", "STOP_FIRST"),
            _trade("BEARISH", "HIGH", "T_PLUS_3", "TARGET_FIRST"),  # excluded
            _trade("BULLISH", "VERY_HIGH", "T_PLUS_4_5", "TARGET_FIRST"),
            _trade("BULLISH", "HIGH", "T_PLUS_1", "TARGET_FIRST"),  # excluded
            _trade("BULLISH", "VERY_HIGH", "T_PLUS_4_5", "NEITHER_WITHIN_15M", 2.0),
        ],
    }
    p = tmp_path / "bt.json"
    p.write_text(json.dumps(src), encoding="utf-8")

    out = analyze(p, (0.0, 1.0))
    bear = out["directions"]["bearish"]
    bull = out["directions"]["bullish"]

    assert bear["candidate_count"] == 2
    assert bear["gross"]["sum_return_pct_points"] == -5.0
    assert bull["candidate_count"] == 2
    assert bull["gross"]["sum_return_pct_points"] == 7.0
    assert bull["cost_sensitivity"]["ROUND_TRIP_COST_1.00_PCT_POINTS"]["sum_return_pct_points"] == 5.0
    assert out["validation_status"] == "REQUIRES_UNTOUCHED_FRESH_OOS"


def test_ambiguous_is_conservative_stop(tmp_path: Path):
    src = {
        "status": "AVAILABLE",
        "entry_rule": "NEXT_MINUTE_OPEN",
        "trades": [_trade("BEARISH", "HIGH", "T_PLUS_1", "AMBIGUOUS_SAME_BAR")],
    }
    p = tmp_path / "bt.json"
    p.write_text(json.dumps(src), encoding="utf-8")
    out = analyze(p, (0.0,))
    bear = out["directions"]["bearish"]
    assert bear["gross"]["mean_return_pct"] == -10.0
    assert bear["exit_counts"]["AMBIGUOUS_ASSUMED_STOP"] == 1
