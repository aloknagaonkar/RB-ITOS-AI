import json
from pathlib import Path
from market_lab.atm_plus_minus_5_trade_path_analysis_v1 import Signal, build_index, load_rows, analyze_one

def test_recovery_after_stop(tmp_path: Path):
    rows=[]
    vals=[(100,101,94,95),(95,106,95,105),(105,112,104,110)]
    for i,(o,h,l,c) in enumerate(vals):
        rows.append({"timestamp":f"2026-05-18T10:{46+i:02d}:00+05:30","strike":23400,
                     "side":"CE","open":o,"high":h,"low":l,"close":c})
    p=tmp_path/"x.json"; p.write_text(json.dumps({"rows":rows}))
    idx=build_index(load_rows(p,"2026-05-18"))
    s=Signal("2026-05-18T10:45:00+05:30",23400,"BULLISH")
    r=analyze_one(idx,s,23400,0,2)
    assert r["status"]=="PASS"
    assert r["hit_minus_5_0"] is True
    assert r["recovered_to_plus10_after_minus5"] is True
