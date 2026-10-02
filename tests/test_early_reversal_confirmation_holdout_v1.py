import csv, json
from pathlib import Path
from market_lab.early_reversal_confirmation_holdout_v1 import (
    load_states, load_audits, event_rows, build_report
)

def test_holdout_remaining_move_from_candle2(tmp_path: Path):
    rows = tmp_path/"rows.csv"
    fields=["session_date","timestamp","horizon","existing_horizon_state"]
    seq=[
        ("09:30","BEARISH"),
        ("09:35","MIXED"),
        ("09:40","BULLISH"),
        ("09:45","BULLISH"),
        ("09:50","BULLISH"),
        ("09:55","MIXED"),
    ]
    data=[]
    for t,s in seq:
        for h in ("5m","10m","15m"):
            data.append({
                "session_date":"2026-01-01",
                "timestamp":f"2026-01-01T{t}:00+05:30",
                "horizon":h,
                "existing_horizon_state":s,
            })
    with rows.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(data)

    audit=tmp_path/"audit.json"
    ar=[]
    spots={"09:30":100,"09:35":101,"09:40":102,"09:45":103,"09:50":106,"09:55":105}
    for t,_ in seq:
        ar.append({
            "timestamp":f"2026-01-01T{t}:00+05:30",
            "spot":spots[t],
            "futures_oi_direction":"BULLISH",
            "vwap_side":"ABOVE",
        })
    audit.write_text(json.dumps({"session_date":"2026-01-01","rows":ar}))

    ev=event_rows(load_states(rows),load_audits([audit]))
    assert len(ev)==1
    e=ev[0]
    assert e["has_candle2"] is True
    assert e["outcome_three_plus"] is True
    assert e["signed_spot_move_c2_to_run_end"] == 3
    assert e["remaining_all3_candles_after_c2"] == 1
    assert e["c2_futures_support"] is True
    assert e["c2_vwap_support"] is True
    report=build_report(ev)
    assert report["status"]=="PASS"
