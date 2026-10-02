from market_lab.midpoint_failure_feature_diagnostics_v2_1 import (
    _stats,
    _median_gap,
    summarize_slice,
)

def test_stats():
    s = _stats([1.0, 2.0, 3.0])
    assert s["count"] == 3
    assert s["median"] == 2.0
    assert s["mean"] == 2.0

def test_median_gap():
    a = {"median": 5.0}
    b = {"median": 2.0}
    assert _median_gap(a, b) == 3.0

def test_summary_separates_outcomes():
    rows = [
        {
            "outcome_label": "CONTINUATION",
            "price_features": {
                "momentum_5m": 10, "acceptance_pct": 100, "consecutive_closes": 3,
                "extreme_count": 2, "progress_points": 20, "velocity": 5,
                "rebound_points": 2, "midpoint_cross_count": 0,
            },
            "oi": {"support_level": "STRONG", "ce_state": "SHORT_BUILDUP", "pe_state": "LONG_BUILDUP"},
            "oi_transition": "STABLE",
            "checkpoint_minutes": 3,
            "block": "TRAIN",
            "session_date": "2026-01-01",
            "setup_type": "RED_BREAK",
            "primary_outcome": "RED_BEARISH_BREAK_AND_GO",
        },
        {
            "outcome_label": "REVERSAL",
            "price_features": {
                "momentum_5m": 1, "acceptance_pct": 25, "consecutive_closes": 1,
                "extreme_count": 0, "progress_points": 2, "velocity": 0.5,
                "rebound_points": 12, "midpoint_cross_count": 2,
            },
            "oi": {"support_level": "NONE", "ce_state": "SHORT_COVERING", "pe_state": "LONG_UNWINDING"},
            "oi_transition": "REVERSAL_WARNING",
            "checkpoint_minutes": 3,
            "block": "TRAIN",
            "session_date": "2026-01-02",
            "setup_type": "RED_BREAK",
            "primary_outcome": "RED_BREAK_BULLISH_RECLAIM",
        },
    ]
    s = summarize_slice(rows)
    assert s["continuation_count"] == 1
    assert s["reversal_count"] == 1
    assert s["features"]["acceptance_pct"]["median_gap_cont_minus_rev"] == 75
    assert s["continuation_oi_support"]["STRONG"] == 1
    assert s["reversal_oi_support"]["NONE"] == 1
