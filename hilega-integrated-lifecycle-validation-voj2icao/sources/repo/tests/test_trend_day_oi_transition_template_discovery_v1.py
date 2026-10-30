import pytest

from market_lab.trend_day_oi_transition_template_discovery_v1 import (
    sign_combo, summarize
)

def test_sign_combo():
    assert sign_combo(10,20)=="CE_UP_PE_UP"
    assert sign_combo(-10,20)=="CE_DOWN_PE_UP"
    assert sign_combo(10,-20)=="CE_UP_PE_DOWN"
    assert sign_combo(-10,-20)=="CE_DOWN_PE_DOWN"

def test_summary_keeps_quantity_pct_and_pcr():
    rows=[
        {"session_date":"2026-01-01","ce_delta":10.0,"pe_delta":30.0,
         "ce_pct":1.0,"pe_pct":3.0,"activity":40.0,
         "pcr_previous":0.9,"pcr_current":1.0},
        {"session_date":"2026-01-02","ce_delta":20.0,"pe_delta":10.0,
         "ce_pct":2.0,"pe_pct":1.0,"activity":30.0,
         "pcr_previous":1.1,"pcr_current":1.0},
    ]
    s=summarize(rows)
    assert s["ce_delta"]["median"]==15.0
    assert s["pe_pct"]["median"]==2.0
    assert s["activity"]["median"]==35.0
    assert s["pcr_change"]["median"] == pytest.approx(0.0, abs=1e-12)
    assert s["positive_imbalance_count"]==1
    assert s["negative_imbalance_count"]==1
