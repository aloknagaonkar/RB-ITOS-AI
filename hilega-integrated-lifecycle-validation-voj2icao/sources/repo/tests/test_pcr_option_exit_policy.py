import json

from market_lab.pcr_option_exit_policy import analyze


def _trade(direction, timing, tier, result_5_10, return_15m):
    return {
        "direction": direction,
        "confirmation_offset_group": timing,
        "confidence_tier": tier,
        "returns_pct": {"15m": return_15m},
        "target_stop": {
            "TARGET_5_STOP_5": {"result": "NEITHER_WITHIN_15M"},
            "TARGET_5_STOP_10": {"result": result_5_10},
            "TARGET_10_STOP_5": {"result": "NEITHER_WITHIN_15M"},
            "TARGET_10_STOP_10": {"result": "NEITHER_WITHIN_15M"},
            "TARGET_15_STOP_5": {"result": "NEITHER_WITHIN_15M"},
            "TARGET_15_STOP_10": {"result": "NEITHER_WITHIN_15M"},
        },
    }


def test_exit_policy_uses_conservative_same_bar_and_time_exit(tmp_path):
    report = {
        "status": "AVAILABLE",
        "entry_rule": "NEXT_MINUTE_OPEN",
        "trades": [
            _trade("BEARISH", "T_PLUS_1", "VERY_HIGH", "TARGET_FIRST", -1.0),
            _trade("BEARISH", "T_PLUS_1", "VERY_HIGH", "STOP_FIRST", 2.0),
            _trade("BEARISH", "T_PLUS_1", "VERY_HIGH", "AMBIGUOUS_SAME_BAR", 8.0),
            _trade("BEARISH", "T_PLUS_1", "VERY_HIGH", "NEITHER_WITHIN_15M", 3.0),
        ],
    }
    src = tmp_path / "bt.json"
    src.write_text(json.dumps(report), encoding="utf-8")
    out = analyze(src)
    p = out["directions"]["bearish"]["overall"]["TARGET_5_STOP_10"]
    # +5, -10, ambiguous -> conservative -10, neither -> +3 time exit.
    assert p["realized_count"] == 4
    assert p["exit_counts"]["AMBIGUOUS_ASSUMED_STOP"] == 1
    assert p["exit_counts"]["TIME_EXIT_15M"] == 1
    assert p["mean_realized_return_pct"] == -3.0
    assert p["sum_realized_return_pct_points"] == -12.0
    assert round(p["breakeven_target_first_pct_if_all_resolve_at_target_or_stop"], 6) == round(100 * 10 / 15, 6)


def test_exit_policy_groups_by_timing_and_confidence(tmp_path):
    report = {
        "status": "AVAILABLE",
        "entry_rule": "NEXT_MINUTE_OPEN",
        "trades": [
            _trade("BULLISH", "T_PLUS_2", "HIGH", "TARGET_FIRST", 0.0),
            _trade("BULLISH", "T_PLUS_4_5", "VERY_HIGH", "TARGET_FIRST", 0.0),
        ],
    }
    src = tmp_path / "bt.json"
    src.write_text(json.dumps(report), encoding="utf-8")
    out = analyze(src)
    assert out["directions"]["bullish"]["by_confirmation_timing"]["T_PLUS_2"]["TARGET_5_STOP_10"]["candidate_count"] == 1
    assert out["directions"]["bullish"]["by_confidence_tier"]["VERY_HIGH"]["TARGET_5_STOP_10"]["candidate_count"] == 1
