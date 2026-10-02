import json
from pathlib import Path

from market_lab.historical_oi_auto_enrichment_v1 import required_raw_wings_from_session

def _session(atms):
    rows=[]
    for idx, atm in enumerate(atms):
        minute=20+idx*5
        ts=f"2026-09-09T{9 + minute//60:02d}:{minute%60:02d}:00+05:30"
        for strike in range(int(atm)-300, int(atm)+301, 50):
            rows.append({"timestamp":ts,"moving_atm":float(atm),"strike":float(strike)})
    return {"strike_interval":50,"rows":rows}

def test_required_raw_wings_one_interval_drift():
    result=required_raw_wings_from_session(_session([23500,23550,23500,23450]))
    assert result["fixed_atm"] == 23500
    assert result["max_drift_intervals"] == 1
    assert result["required_raw_wings"] == 6

def test_required_raw_wings_three_interval_drift():
    result=required_raw_wings_from_session(_session([23500,23650,23400]))
    assert result["max_drift_intervals"] == 3
    assert result["required_raw_wings"] == 8

def test_enriched_api_module_exists():
    assert Path("backend/market_lab/historical_oi_enrichment_api_v1.py").exists()
