import csv, json
from datetime import datetime
from pathlib import Path

from market_lab.historical_oi_canonical_decision_audit_v1 import (
    all3, audit_session, load_canonical_dates, run_population
)

def real_row(ts, direction):
    s=1 if direction=="BULLISH" else -1
    mh={}
    for h in (5,10,15):
        mh[f"{h}m"]={
            "status":"AVAILABLE",
            "imbalance":s*(100+h),
            "pcr_change":s*0.1,
            "ce_delta":10,
            "pe_delta":20,
            "prior_pcr":1.0,
            "current_pcr":1.0+s*0.1,
        }
    return {
        "_dt":datetime.fromisoformat(ts),
        "timestamp":ts,
        "time":ts[11:16],
        "moving_horizons":mh,
        "spot":25000,
        "moving_atm":25000,
    }

def test_real_enriched_horizon_keys_are_read():
    assert all3(real_row("2026-08-25T09:30:00+05:30","BULLISH"))["all3"]=="BULLISH_ALL_3"
    assert all3(real_row("2026-08-25T09:30:00+05:30","BEARISH"))["all3"]=="BEARISH_ALL_3"

def test_real_schema_creates_detection():
    rows=[
        real_row("2026-08-25T09:30:00+05:30","BULLISH"),
        real_row("2026-08-25T09:35:00+05:30","BULLISH"),
    ]
    r=audit_session("2026-08-25",rows,{})
    assert r["event_count"]==1
    assert r["events"][0]["direction"]=="BULLISH"

def test_canonical_date_loader(tmp_path):
    p=tmp_path/"c.csv"
    p.write_text("session_date,time\n2026-08-25,09:20\n2026-08-25,09:25\n2026-09-08,09:20\n")
    assert load_canonical_dates(p)=={"2026-08-25","2026-09-08"}

def test_population_excludes_noncanonical_enriched_dates(tmp_path):
    er=tmp_path/"enriched"; out=tmp_path/"out"; er.mkdir()
    for d in ("2026-08-25","2026-09-09"):
        dd=er/d; dd.mkdir()
        rr=[
            {k:v for k,v in real_row(f"{d}T09:30:00+05:30","BULLISH").items() if k!="_dt"},
            {k:v for k,v in real_row(f"{d}T09:35:00+05:30","BULLISH").items() if k!="_dt"},
        ]
        (dd/"enriched.json").write_text(json.dumps({"rows":rr}))
    c=tmp_path/"canonical.csv"
    c.write_text("session_date\n2026-08-25\n")
    f=tmp_path/"f.csv"
    with f.open("w",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=["timestamp","futures_oi_state"]); w.writeheader()
        w.writerow({"timestamp":"2026-08-25T09:35:00+05:30","futures_oi_state":"SHORT_COVERING"})
    s=run_population(er,f,out,canonical_csv=c)
    assert s["sessions"]==1
    assert s["checkpoints"]==2
