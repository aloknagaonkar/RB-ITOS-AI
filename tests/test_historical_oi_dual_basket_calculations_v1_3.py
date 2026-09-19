from pathlib import Path
from market_lab.historical_oi_build_job_v1 import _required_union_wings

def test_union_wings_expands_for_fixed_drift():
    payload={"sessions":[{"strike_interval":50,"rows":[
      {"timestamp":"2026-09-10T09:20:00+05:30","moving_atm":23450},
      {"timestamp":"2026-09-10T10:05:00+05:30","moving_atm":23400},
    ]}]}
    result=_required_union_wings(payload)
    assert result["required_wings"]==6
    assert result["fixed_atm"]==23450

def test_ui_contains_fixed_and_horizon_calculations():
    text=Path("frontend/src/historicalOiResearch.tsx").read_text()
    assert "Fixed 09:20 ATM ±5" in text
    assert "Moving same-strike 5m / 10m / 15m" in text
    assert "Session imbalance" in text
