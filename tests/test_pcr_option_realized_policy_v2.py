import json
from pathlib import Path

from market_lab.pcr_option_realized_policy_v2 import analyze


def _trade(direction, result, ret15=None):
    return {
        "session_date": "2026-01-12",
        "stage2_timestamp": "2026-01-12T10:00:00+05:30",
        "direction": direction,
        "option_side": "PE" if direction == "BEARISH" else "CE",
        "confidence_tier": "HIGH",
        "confirmation_offset_minutes": 2,
        "confirmation_offset_group": "T_PLUS_2",
        "instrument_key": "X",
        "entry_timestamp": "2026-01-12T10:03:00+05:30",
        "entry_premium": 100.0,
        "returns_pct": {"15m": ret15},
        "target_stop": {"TARGET_5_STOP_10": {"result": result}},
    }


def _write(tmp_path: Path, trades):
    p = tmp_path / "backtest.json"
    p.write_text(json.dumps({
        "status": "AVAILABLE",
        "methodology_version": "PCR_RESEARCH_METHODOLOGY_V2",
        "confidence_profile": "FROZEN_D5_D15",
        "entry_rule": "NEXT_MINUTE_OPEN",
        "contract_selection_rule": "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION",
        "trades": trades,
    }))
    return p


def test_conservative_exit_resolution_and_no_timing_filter(tmp_path):
    p = _write(tmp_path, [
        _trade("BEARISH", "TARGET_FIRST"),
        _trade("BEARISH", "STOP_FIRST"),
        _trade("BEARISH", "AMBIGUOUS_SAME_BAR"),
        _trade("BEARISH", "NEITHER_WITHIN_15M", 2.5),
    ])
    out = analyze(p)
    d = out["directions"]["bearish"]
    assert d["timing_filter"] == "NONE_ALL_FIRST_CONFIRMATIONS_T0_TO_TPLUS5"
    assert d["candidate_count"] == 4
    assert d["exit_counts"]["TARGET"] == 1
    assert d["exit_counts"]["STOP"] == 1
    assert d["exit_counts"]["AMBIGUOUS_ASSUMED_STOP"] == 1
    assert d["exit_counts"]["TIME_EXIT_15M"] == 1
    assert d["gross"]["sum_return_pct_points"] == -12.5


def test_cost_sensitivity_and_guards(tmp_path):
    p = _write(tmp_path, [
        _trade("BULLISH", "TARGET_FIRST"),
        _trade("BULLISH", "NEITHER_WITHIN_15M", 1.0),
    ])
    out = analyze(p)
    d = out["directions"]["bullish"]
    c50 = d["cost_sensitivity"]["ROUND_TRIP_COST_0.50_PCT_POINTS"]
    assert c50["mean_return_pct"] == 2.5
    assert out["policy_status"] == "FROZEN_FOR_UNTOUCHED_OOS_G"
    assert out["target_pct"] == 5.0
    assert out["stop_pct"] == 10.0
    assert out["time_exit_minutes"] == 15
