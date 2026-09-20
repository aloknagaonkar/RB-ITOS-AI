from pathlib import Path

P = Path("tests/test_historical_oi_canonical_decision_audit_v1.py")
if not P.exists():
    raise SystemExit("Safe-stop: V1 test file not found")

text = P.read_text(encoding="utf-8")

old = '''def test_trade_eligible(tmp_path):
    p=tmp_path/"f.csv"
    with p.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["timestamp","futures_oi_state"]);w.writeheader()
        w.writerow({"timestamp":"2026-01-01T09:35:00+05:30","futures_oi_state":"SHORT_COVERING"})
    r=audit_session("2026-01-01",[row("2026-01-01T09:30:00+05:30","BULLISH"),row("2026-01-01T09:35:00+05:30","BULLISH")],load_futures(p))
    assert r["events"][0]["final_decision"]=="TRADE_ELIGIBLE"
'''

new = '''def test_trade_eligible(tmp_path):
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
'''

if old not in text:
    raise SystemExit("Safe-stop: old test_trade_eligible block not found")

text = text.replace(old, new, 1)
P.write_text(text, encoding="utf-8")
print("Updated V1 trade-eligible test to the production 1-minute futures source contract.")
