import csv, json
from pathlib import Path
from market_lab.early_persistence_asymmetry_validation_v1 import (
    load_states, load_audits, build_snapshots, build_report
)

def test_early_snapshot_is_causal(tmp_path: Path):
    rows = tmp_path/"rows.csv"
    fields=["session_date","timestamp","horizon","existing_horizon_state"]
    seq=[
        ("09:30","BEARISH"),("09:35","BEARISH"),
        ("09:40","MIXED"),
        ("09:45","BULLISH"),("09:50","BULLISH"),("09:55","BULLISH"),
    ]
    data=[]
    for t,s in seq:
        for h in ("5m","10m","15m"):
            data.append({"session_date":"2026-01-01","timestamp":f"2026-01-01T{t}:00+05:30","horizon":h,"existing_horizon_state":s})
    with rows.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(data)

    audit=tmp_path/"audit.json"
    audit.write_text(json.dumps({
        "session_date":"2026-01-01",
        "rows":[
            {"timestamp":"2026-01-01T09:45:00+05:30","futures_oi_direction":"BULLISH","vwap_side":"ABOVE","session_imbalance":10,"session_pcr_change_0920_to_now":0.1},
            {"timestamp":"2026-01-01T09:50:00+05:30","futures_oi_direction":"BULLISH","vwap_side":"ABOVE","session_imbalance":10,"session_pcr_change_0920_to_now":0.1},
        ]
    }))

    snaps=build_snapshots(load_states(rows),load_audits([audit]))
    assert len(snaps)==2
    assert snaps[0]["snapshot_run_length"]==1
    assert snaps[1]["snapshot_run_length"]==2
    assert snaps[0]["final_run_length"]==3
    assert snaps[0]["outcome_three_plus"] is True
    assert snaps[0]["futures_support"] is True
    assert snaps[1]["futures_support"] is True
    report=build_report(snaps)
    assert report["status"]=="PASS"
    assert report["snapshot_1"]["three_plus_count"]==1
    assert report["snapshot_2"]["three_plus_count"]==1
