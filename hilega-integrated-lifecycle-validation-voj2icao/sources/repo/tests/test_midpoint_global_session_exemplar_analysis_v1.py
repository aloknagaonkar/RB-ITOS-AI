from datetime import datetime

from market_lab.midpoint_global_session_exemplar_analysis_v1 import (
    latest_completed_5m,
    metric,
    quality_bucket,
)


def test_latest_completed_5m():
    t = datetime.fromisoformat("2026-09-15T09:28:00+05:30")
    assert latest_completed_5m(t).isoformat() == "2026-09-15T09:25:00+05:30"


def test_metric():
    x = metric([2.0, -1.0, 3.0])
    assert x["count"] == 3
    assert x["positive_count"] == 2
    assert x["profit_factor"] == 5.0


def test_quality_bucket_excellent():
    r = {"option_economics": {"net_5m_pct": 12.0}}
    assert quality_bucket(r) == "EXCELLENT_5M_GE_10"


def test_quality_bucket_large_loss():
    r = {"option_economics": {"net_5m_pct": -7.0}}
    assert quality_bucket(r) == "LARGE_LOSS_5M_LE_MINUS5"


def test_structural_loader_accepts_canonical_rows():
    from market_lab.midpoint_global_session_exemplar_analysis_v1 import load_structural_events
    doc = {
        "structural_event_count": 2,
        "rows": [
            {"block": "TRAIN", "session_date": "2026-09-01", "direction": "BULLISH"},
            {"block": "OOS_A", "session_date": "2026-09-02", "direction": "BEARISH"},
        ],
    }
    rows = load_structural_events(doc)
    assert len(rows) == 2
    assert all(r["_structural_source_key"] == "rows" for r in rows)


def test_decision_family_reads_nested_v2_result():
    from market_lab.midpoint_global_session_exemplar_analysis_v1 import decision_family
    assert decision_family({
        "t3_state": "WAIT_BASE",
        "v2_result": {"final_state": "CONFIRM_BASE_THEN_GO", "entry_arm": "BASE_THEN_GO"},
    }) == "BASE_THEN_GO"


def test_round_atm_50():
    from market_lab.midpoint_global_session_exemplar_analysis_v1 import round_atm_50
    assert round_atm_50(23497.0) == 23500.0
    assert round_atm_50(23474.9) == 23450.0


def test_actual_t3_features_normalizes_momentum_name():
    from market_lab.midpoint_global_session_exemplar_analysis_v1 import actual_t3_features
    key = ("TRAIN", "2026-09-07", "RED_BREAK", "2026-09-07T09:28:00+05:30")
    idx = {key: {"price_features": {
        "acceptance_pct": 100.0,
        "momentum_5m": 32.7,
        "progress_points": 27.75,
        "giveback_from_best_checkpoint_points": 0.0,
        "consecutive_closes": 4,
        "velocity": 9.25,
    }}}
    out = actual_t3_features(*key[:3], key[3], idx)
    assert out["momentum_5m_directional"] == 32.7
    assert len(out) == 6


def test_result_construction_has_no_self_reference():
    import inspect
    import market_lab.midpoint_global_session_exemplar_analysis_v1 as m
    source = inspect.getsource(m.main)
    assert '"coverage": result["coverage"]' not in source
