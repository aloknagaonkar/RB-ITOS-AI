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
    # Production futures source contract is 1-minute candles with close + open_interest.
    # Build exact 09:25-09:29 and 09:30-09:34 bars so the latter becomes
    # available at 09:35 and classifies as SHORT_COVERING.
    p=tmp_path/"f.csv"
    fields=[
        "session_date","timestamp","instrument_key","expiry",
        "contract_source","close","open_interest",
    ]
    rows=[]
    # Completed 09:25 bar: close=100, OI=1000 at 09:29.
    for i in range(5):
        rows.append({
            "session_date":"2026-01-01",
            "timestamp":f"2026-01-01T09:{25+i:02d}:00+05:30",
            "instrument_key":"FUT1",
            "expiry":"2026-01-06",
            "contract_source":"TEST",
            "close":str(96+i),
            "open_interest":str(960+10*i),
        })
    # Completed 09:30 bar: close=105, OI=900 at 09:34.
    # Price up + OI down => SHORT_COVERING.
    for i in range(5):
        rows.append({
            "session_date":"2026-01-01",
            "timestamp":f"2026-01-01T09:{30+i:02d}:00+05:30",
            "instrument_key":"FUT1",
            "expiry":"2026-01-06",
            "contract_source":"TEST",
            "close":str(101+i),
            "open_interest":str(980-20*i),
        })

    with p.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    r=audit_session(
        "2026-01-01",
        [
            row("2026-01-01T09:30:00+05:30","BULLISH"),
            row("2026-01-01T09:35:00+05:30","BULLISH"),
        ],
        load_futures(p),
    )
    assert r["events"][0]["final_decision"]=="TRADE_ELIGIBLE"
    assert r["events"][0]["futures_state"]=="SHORT_COVERING"

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
