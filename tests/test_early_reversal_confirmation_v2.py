import csv, json
from pathlib import Path
from market_lab.early_reversal_confirmation_v2 import (
    load_states, load_audits, build_events, build_report
)

def test_candle2_confirmation_is_causal(tmp_path: Path):
    rows = tmp_path / "rows.csv"
    fields = ["session_date","timestamp","horizon","existing_horizon_state"]
    seq = [
        ("09:30","BEARISH"),
        ("09:35","BEARISH"),
        ("09:40","MIXED"),
        ("09:45","BULLISH"),
        ("09:50","BULLISH"),
        ("09:55","BULLISH"),
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
    audit.write_text(json.dumps({
        "session_date":"2026-01-01",
        "rows":[
            {
                "timestamp":"2026-01-01T09:45:00+05:30",
                "futures_oi_direction":"BULLISH",
                "futures_oi_status":"LONG_BUILDUP",
                "bullish_oi_status_streak":1,
                "vwap_side":"BELOW",
                "session_imbalance":10,
                "session_pcr_change_0920_to_now":0.1,
            },
            {
                "timestamp":"2026-01-01T09:50:00+05:30",
                "futures_oi_direction":"BULLISH",
                "futures_oi_status":"LONG_BUILDUP",
                "bullish_oi_status_streak":2,
                "vwap_side":"ABOVE",
                "session_imbalance":12,
                "session_pcr_change_0920_to_now":0.2,
            }
        ]
    }))

    events=build_events(load_states(rows),load_audits([audit]))
    assert len(events)==1
    e=events[0]
    assert e["final_run_length"]==3
    assert e["c1_futures_support"] is True
    assert e["c2_futures_support"] is True
    assert e["futures_support_maintained_c1_c2"] is True
    assert e["futures_streak_strengthened_c2"] is True
    assert e["vwap_crossed_into_alignment_c2"] is True
    report=build_report(events)
    assert report["status"]=="PASS"
    assert report["candle2"]["events_reaching_candle2"]==1
