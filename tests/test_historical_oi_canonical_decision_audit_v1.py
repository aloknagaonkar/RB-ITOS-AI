import csv
from datetime import datetime
from market_lab.historical_oi_canonical_decision_audit_v1 import all3,audit_session,load_futures

def row(ts,d):
    s=1 if d=="BULLISH" else -1 if d=="BEARISH" else 0
    mh={}
    for h in (5,10,15):
        im,pc=s*(100+h),s*.1
        if d=="MIXED" and h==10: im,pc=10,-.1
        mh[str(h)]={"imbalance":im,"pcr_change":pc}
    return {"_dt":datetime.fromisoformat(ts),"timestamp":ts,"moving_horizons":mh}

def test_all3():
    assert all3(row("2026-01-01T09:30:00+05:30","BULLISH"))["all3"]=="BULLISH_ALL_3"
    assert all3(row("2026-01-01T09:30:00+05:30","BEARISH"))["all3"]=="BEARISH_ALL_3"
    assert all3(row("2026-01-01T09:30:00+05:30","MIXED"))["all3"]=="MIXED"

def test_trade_eligible(tmp_path):
    p=tmp_path/"f.csv"
    with p.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["timestamp","futures_oi_state"]);w.writeheader()
        w.writerow({"timestamp":"2026-01-01T09:35:00+05:30","futures_oi_state":"SHORT_COVERING"})
    r=audit_session("2026-01-01",[row("2026-01-01T09:30:00+05:30","BULLISH"),row("2026-01-01T09:35:00+05:30","BULLISH")],load_futures(p))
    assert r["events"][0]["final_decision"]=="TRADE_ELIGIBLE"

def test_c2_fail():
    r=audit_session("2026-01-01",[row("2026-01-01T09:30:00+05:30","BEARISH"),row("2026-01-01T09:35:00+05:30","MIXED")],{})
    assert "C2_PERSISTENCE" in r["events"][0]["failed_check_ids"]

def test_missing_c2():
    r=audit_session("2026-01-01",[row("2026-01-01T09:30:00+05:30","BULLISH")],{})
    assert r["events"][0]["final_decision"]=="INCOMPLETE"

def test_new_opposite_only():
    rr=[row("2026-01-01T09:30:00+05:30","BULLISH"),row("2026-01-01T09:35:00+05:30","BULLISH"),
        row("2026-01-01T09:40:00+05:30","MIXED"),row("2026-01-01T09:45:00+05:30","BULLISH"),
        row("2026-01-01T09:50:00+05:30","BEARISH"),row("2026-01-01T09:55:00+05:30","BEARISH")]
    r=audit_session("2026-01-01",rr,{})
    assert [e["direction"] for e in r["events"]]==["BULLISH","BEARISH"]
