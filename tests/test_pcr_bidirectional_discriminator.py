import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_lab.pcr_bidirectional_discriminator import analyze_bidirectional_discriminator

FIELDS = [
    "session_date","timestamp","spot","forward_change_5m","forward_change_15m","forward_change_30m",
    "fixed_pcr","moving_pcr","full_pcr","fixed_moving_pcr_spread",
    "fixed_pcr_change_1m","fixed_pcr_change_5m","fixed_pcr_change_15m","fixed_pcr_change_30m",
    "moving_pcr_change_1m","moving_pcr_change_5m","moving_pcr_change_15m","moving_pcr_change_30m",
    "full_pcr_change_1m","full_pcr_change_5m","full_pcr_change_15m","full_pcr_change_30m",
    "fixed_call_oi_change_pct","fixed_put_oi_change_pct","moving_call_oi_change_pct","moving_put_oi_change_pct",
    "full_call_oi_change_pct","full_put_oi_change_pct","atm_divergence_points",
]

def make_rows(day: str, bearish_values, bullish_values):
    base=datetime.fromisoformat(day+"T09:15:00+05:30")
    rows=[]
    spot=100.0
    # enough history for prior-15 calculation
    for i in range(45):
        ts=base+timedelta(minutes=i)
        spot=100+i*0.2
        row={k:"0" for k in FIELDS}
        row.update({"session_date":day,"timestamp":ts.isoformat(),"spot":str(spot),"fixed_pcr":"1.0","moving_pcr":"1.0","full_pcr":"1.0"})
        # default neutral-ish signs that are not Stage2
        row["moving_pcr_change_5m"]="0.1"; row["moving_pcr_change_15m"]="0.1"; row["moving_pcr_change_30m"]="0.1"
        rows.append(row)
    # bearish first-entry at 09:35, prior 15m is positive; favorable 15/30 -> true reversal
    b=rows[20]; b["moving_pcr_change_5m"]="-0.1"; b["moving_pcr_change_15m"]="-0.2"; b["moving_pcr_change_30m"]="0.3"
    b["forward_change_5m"]="-1"; b["forward_change_15m"]="-2"; b["forward_change_30m"]="-3"
    for k,v in bearish_values.items(): b[k]=str(v)
    # bearish false warning at 09:38 after leaving state
    rows[21]["moving_pcr_change_5m"]="0.1"
    bf=rows[23]; bf["moving_pcr_change_5m"]="-0.1"; bf["moving_pcr_change_15m"]="-0.2"; bf["moving_pcr_change_30m"]="0.3"
    bf["forward_change_5m"]="1"; bf["forward_change_15m"]="2"; bf["forward_change_30m"]="3"
    for k,v in bearish_values.items(): bf[k]=str(v*0.5)
    # create downtrend prior to bullish event at 09:50
    for i in range(25,36): rows[i]["spot"]=str(110-(i-25)*0.5)
    u=rows[36]; u["spot"]="95.0"; u["moving_pcr_change_5m"]="0.1"; u["moving_pcr_change_15m"]="0.2"; u["moving_pcr_change_30m"]="-0.3"
    u["forward_change_5m"]="1"; u["forward_change_15m"]="2"; u["forward_change_30m"]="3"
    for k,v in bullish_values.items(): u[k]=str(v)
    rows[37]["moving_pcr_change_5m"]="-0.1"
    uf=rows[39]; uf["spot"]="94.0"; uf["moving_pcr_change_5m"]="0.1"; uf["moving_pcr_change_15m"]="0.2"; uf["moving_pcr_change_30m"]="-0.3"
    uf["forward_change_5m"]="-1"; uf["forward_change_15m"]="-2"; uf["forward_change_30m"]="-3"
    for k,v in bullish_values.items(): uf[k]=str(v*0.5)
    return rows

def write_csv(path: Path, rows):
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(rows)

def test_bidirectional_counts_and_features(tmp_path):
    train=tmp_path/"train.csv"; oos=tmp_path/"oos.csv"
    vals={"fixed_pcr_change_5m":-0.02,"moving_pcr_change_15m":-0.08,"full_pcr_change_15m":-0.08,"fixed_pcr_change_15m":-0.01,"moving_pcr_change_30m":0.03,"full_pcr_change_30m":0.03,"fixed_pcr":1.1}
    uvals={"fixed_pcr_change_5m":0.02,"moving_pcr_change_15m":0.08,"full_pcr_change_15m":0.08,"fixed_pcr_change_15m":0.01,"moving_pcr_change_30m":-0.03,"full_pcr_change_30m":-0.03,"fixed_pcr":0.9}
    write_csv(train,make_rows("2026-01-01",vals,uvals)); write_csv(oos,make_rows("2026-01-02",vals,uvals))
    report=analyze_bidirectional_discriminator([("TRAIN",train),("OOS_A",oos)])
    assert report.status=="AVAILABLE"
    assert report.bearish.total_stage_2_events==4
    assert report.bearish.total_true_reversals==2
    assert report.bearish.total_false_warnings==2
    assert report.bullish.total_stage_2_events==4
    assert report.bullish.total_true_reversals==2
    assert report.bullish.total_false_warnings==2

def test_requires_train_first(tmp_path):
    p=tmp_path/"x.csv"; write_csv(p,make_rows("2026-01-01",{},{}))
    try:
        analyze_bidirectional_discriminator([("OOS_A",p)])
    except ValueError as e:
        assert "TRAIN" in str(e)
    else:
        raise AssertionError("expected ValueError")
