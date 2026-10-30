import csv
from pathlib import Path

from market_lab.historical_oi_canonical_decision_audit_v1 import load_futures


def _write_minutes(path: Path):
    fields=[
        "session_date","timestamp","instrument_key","expiry","contract_source",
        "close","open_interest"
    ]
    rows=[]
    for i in range(5):
        rows.append({
            "session_date":"2026-08-25",
            "timestamp":f"2026-08-25T09:{15+i:02d}:00+05:30",
            "instrument_key":"FUT1",
            "expiry":"2026-08-25",
            "contract_source":"TEST",
            "close":str(96+i),
            "open_interest":str(960+10*i),
        })
    for i in range(5):
        rows.append({
            "session_date":"2026-08-25",
            "timestamp":f"2026-08-25T09:{20+i:02d}:00+05:30",
            "instrument_key":"FUT1",
            "expiry":"2026-08-25",
            "contract_source":"TEST",
            "close":str(101+i),
            "open_interest":str(980-20*i),
        })
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def test_futures_5m_available_at_bar_end(tmp_path):
    p=tmp_path/"f.csv"; _write_minutes(p)
    idx=load_futures(p)
    assert "2026-08-25T09:20:00+05:30" in idx
    assert "2026-08-25T09:25:00+05:30" in idx
    x=idx["2026-08-25T09:25:00+05:30"]
    assert x["bar_start"]=="2026-08-25T09:20:00+05:30"
    assert x["state"]=="SHORT_COVERING"
    assert x["price_change_5m"]==5.0
    assert x["oi_change_5m"]==-100.0


def test_incomplete_5m_bucket_is_not_emitted(tmp_path):
    p=tmp_path/"f.csv"
    fields=["session_date","timestamp","instrument_key","expiry","contract_source","close","open_interest"]
    with p.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for m in (20,21,23,24):
            w.writerow({
                "session_date":"2026-08-25",
                "timestamp":f"2026-08-25T09:{m:02d}:00+05:30",
                "instrument_key":"FUT1","expiry":"2026-08-25","contract_source":"TEST",
                "close":"100","open_interest":"1000",
            })
    idx=load_futures(p)
    assert "2026-08-25T09:25:00+05:30" not in idx
