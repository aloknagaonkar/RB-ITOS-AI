import pandas as pd

from red_bar_lab.intelligence.institutional_flow import InstitutionalOptionFlowEngine


def _frames():
    previous = pd.DataFrame([
        {"strike": 25000, "call_ltp": 100, "call_oi": 100000, "call_volume": 50000,
         "put_ltp": 100, "put_oi": 100000, "put_volume": 50000},
        {"strike": 25100, "call_ltp": 80, "call_oi": 100000, "call_volume": 50000,
         "put_ltp": 120, "put_oi": 100000, "put_volume": 50000},
    ])
    current = pd.DataFrame([
        {"strike": 25000, "call_ltp": 110, "call_oi": 120000, "call_volume": 120000,
         "put_ltp": 90, "put_oi": 125000, "put_volume": 100000},
        {"strike": 25100, "call_ltp": 70, "call_oi": 130000, "call_volume": 100000,
         "put_ltp": 130, "put_oi": 120000, "put_volume": 110000},
    ])
    return current, previous


def test_oi_behaviour_quadrants():
    e = InstitutionalOptionFlowEngine
    assert e.classify_oi_behaviour(2, 10) == "LONG_BUILDUP"
    assert e.classify_oi_behaviour(-2, 10) == "SHORT_BUILDUP"
    assert e.classify_oi_behaviour(2, -10) == "SHORT_COVERING"
    assert e.classify_oi_behaviour(-2, -10) == "LONG_UNWINDING"


def test_writing_detector_maps_side_correctly():
    e = InstitutionalOptionFlowEngine
    assert e.classify_activity("CE", "SHORT_BUILDUP") == "CALL_WRITING"
    assert e.classify_activity("PE", "SHORT_BUILDUP") == "PUT_WRITING"
    assert e.classify_activity("CE", "LONG_BUILDUP") == "CALL_BUYING"
    assert e.classify_activity("PE", "LONG_BUILDUP") == "PUT_BUYING"


def test_snapshot_is_observational_and_classifies_strikes():
    current, previous = _frames()
    result = InstitutionalOptionFlowEngine.evaluate_frames(current, previous, option_expiry="2026-08-13")
    assert result.status == "READY"
    assert len(result.rows) == 4
    acts = {(r.strike, r.option_type): r.activity for r in result.rows}
    assert acts[(25000.0, "CE")] == "CALL_BUYING"
    assert acts[(25000.0, "PE")] == "PUT_WRITING"
    assert acts[(25100.0, "CE")] == "CALL_WRITING"
    assert acts[(25100.0, "PE")] == "PUT_BUYING"
    assert round(result.bullish_flow_pct + result.bearish_flow_pct + result.neutral_flow_pct, 1) == 100.0
