#!/usr/bin/env python3
"""LIVE OI signal-timing attribution V1.

Research-only, read-only diagnostic.
Reads LIVE_SHADOW_STEP_AUDIT_V1 NORMALIZED_FEATURES records and reports
checkpoint-by-checkpoint 5m/10m/15m OI/PCR alignment.

It does NOT change strategy rules, thresholds, orders, or stored data.

Progression labels are descriptive diagnostics only:
- PERSISTENT_BULL / PERSISTENT_BEAR: all 3 horizons aligned.
- BUILDING_BULL / BUILDING_BEAR: 5m and 10m aligned, 15m not yet aligned.
- REVERSING_TO_BULL / REVERSING_TO_BEAR: 5m opposes 15m.
- FADING_BULL / FADING_BEAR: older 15m direction remains but 5m has lost it.
- MIXED / INCOMPLETE otherwise.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

def fnum(v):
    if v is None:
        return ""
    try:
        return f"{float(v):.6f}"
    except Exception:
        return str(v)

def mnum(v):
    if v is None:
        return "—"
    x=float(v)/1_000_000.0
    return f"{x:+.2f}M"

def progression(s5: str, s10: str, s15: str) -> str:
    vals=(s5,s10,s15)
    if "NA" in vals:
        return "INCOMPLETE"
    if vals==("BULLISH","BULLISH","BULLISH"):
        return "PERSISTENT_BULL"
    if vals==("BEARISH","BEARISH","BEARISH"):
        return "PERSISTENT_BEAR"
    if s5=="BULLISH" and s10=="BULLISH" and s15!="BULLISH":
        return "BUILDING_BULL"
    if s5=="BEARISH" and s10=="BEARISH" and s15!="BEARISH":
        return "BUILDING_BEAR"
    if s5=="BULLISH" and s15=="BEARISH":
        return "REVERSING_TO_BULL"
    if s5=="BEARISH" and s15=="BULLISH":
        return "REVERSING_TO_BEAR"
    if s15=="BULLISH" and s5!="BULLISH":
        return "FADING_BULL"
    if s15=="BEARISH" and s5!="BEARISH":
        return "FADING_BEAR"
    return "MIXED"

def parse_dt(x: str) -> datetime:
    return datetime.fromisoformat(x)

def load_rows(path: Path, session_date: str) -> list[dict[str,Any]]:
    latest={}
    for line in path.open(encoding="utf-8"):
        try:
            rec=json.loads(line)
        except Exception:
            continue
        cp=str(rec.get("checkpoint") or "")
        if not cp.startswith(session_date):
            continue
        if rec.get("stage")!="NORMALIZED_FEATURES":
            continue
        # Keep latest sequence if duplicate/restart wrote same checkpoint.
        seq=int(rec.get("sequence") or 0)
        old=latest.get(cp)
        if old is None or seq>=int(old.get("sequence") or 0):
            latest[cp]=rec
    out=[]
    for cp,rec in sorted(latest.items()):
        p=rec.get("payload") or {}
        hs=p.get("horizons") or {}
        row={
            "checkpoint":cp,
            "time":cp[11:16],
            "spot":p.get("spot"),
            "moving_atm":p.get("moving_atm"),
            "source_delay_ms":p.get("source_delay_ms"),
            "all3_state":p.get("all3_state"),
            "previous_directional_all3":p.get("previous_directional_all3"),
        }
        for label in ("5m","10m","15m"):
            h=hs.get(label) or {}
            prefix=label[:-1]
            row.update({
                f"state_{prefix}":h.get("state","NA"),
                f"ce_delta_{prefix}":h.get("ce_delta"),
                f"pe_delta_{prefix}":h.get("pe_delta"),
                f"imbalance_{prefix}":h.get("imbalance"),
                f"pcr_change_{prefix}":h.get("pcr_change"),
                f"current_pcr_{prefix}":h.get("current_pcr"),
            })
        row["progression"]=progression(
            str(row["state_5"]),str(row["state_10"]),str(row["state_15"])
        )
        row["bullish_horizons"]=sum(row[f"state_{h}"]=="BULLISH" for h in ("5","10","15"))
        row["bearish_horizons"]=sum(row[f"state_{h}"]=="BEARISH" for h in ("5","10","15"))
        out.append(row)
    return out

def within(row,start,end):
    t=row["time"]
    return start<=t<=end

def first(rows,label):
    return next((r for r in rows if r["progression"]==label),None)

def minutes(a,b):
    return int((parse_dt(b["checkpoint"])-parse_dt(a["checkpoint"])).total_seconds()/60)

def print_table(rows):
    print()
    print("=== CHECKPOINT SIGNAL TIMING ===")
    print("TIME   SPOT      5m       10m      15m      ALL3             PROGRESSION          5m_IMB     10m_IMB    15m_IMB    PCRΔ5   PCRΔ10  PCRΔ15")
    print("-"*160)
    for r in rows:
        def p(v):
            if v is None:return "—"
            return f"{float(v):+.4f}"
        print(
            f'{r["time"]:5} '
            f'{float(r["spot"]):8.2f} '
            f'{str(r["state_5"]):8} '
            f'{str(r["state_10"]):8} '
            f'{str(r["state_15"]):8} '
            f'{str(r["all3_state"]):16} '
            f'{r["progression"]:20} '
            f'{mnum(r["imbalance_5"]):>9} '
            f'{mnum(r["imbalance_10"]):>9} '
            f'{mnum(r["imbalance_15"]):>9} '
            f'{p(r["pcr_change_5"]):>7} '
            f'{p(r["pcr_change_10"]):>7} '
            f'{p(r["pcr_change_15"]):>7}'
        )

def summarize(rows):
    print()
    print("=== TIMING ATTRIBUTION ===")
    for direction in ("BULL","BEAR"):
        build=first(rows,f"BUILDING_{direction}")
        persist=first(rows,f"PERSISTENT_{direction}")
        if build:
            print(f"first BUILDING_{direction}:   {build['time']} spot={float(build['spot']):.2f}")
        else:
            print(f"first BUILDING_{direction}:   NONE")
        if persist:
            print(f"first PERSISTENT_{direction}: {persist['time']} spot={float(persist['spot']):.2f}")
        else:
            print(f"first PERSISTENT_{direction}: NONE")
        if build and persist and parse_dt(persist["checkpoint"])>=parse_dt(build["checkpoint"]):
            lead=minutes(build,persist)
            move=float(persist["spot"])-float(build["spot"])
            print(f"lead BUILDING→PERSISTENT: {lead} min; spot move {move:+.2f} pts")
        print()

    # Consecutive directional state runs, useful without defining a trading rule.
    print("=== DESCRIPTIVE COUNTS ===")
    from collections import Counter
    c=Counter(r["progression"] for r in rows)
    for k,v in sorted(c.items()):
        print(f"{k:20} {v}")

def write_csv(rows,path:Path):
    fields=[
        "checkpoint","time","spot","moving_atm","source_delay_ms","all3_state","previous_directional_all3",
        "state_5","ce_delta_5","pe_delta_5","imbalance_5","pcr_change_5","current_pcr_5",
        "state_10","ce_delta_10","pe_delta_10","imbalance_10","pcr_change_10","current_pcr_10",
        "state_15","ce_delta_15","pe_delta_15","imbalance_15","pcr_change_15","current_pcr_15",
        "progression","bullish_horizons","bearish_horizons"
    ]
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for r in rows:w.writerow({k:r.get(k) for k in fields})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",required=True)
    ap.add_argument("--step-audit",default="data/live-observation/shadow-v1/step-audit.jsonl")
    ap.add_argument("--from-time",default="09:20")
    ap.add_argument("--to-time",default="12:00")
    ap.add_argument("--csv",default=None)
    args=ap.parse_args()

    rows=load_rows(Path(args.step_audit),args.date)
    rows=[r for r in rows if within(r,args.from_time,args.to_time)]
    if not rows:
        raise SystemExit("No NORMALIZED_FEATURES records found for requested window.")

    print(f"session={args.date} window={args.from_time}-{args.to_time} checkpoints={len(rows)}")
    print_table(rows)
    summarize(rows)

    out=Path(args.csv) if args.csv else Path(f"data/live-observation/analysis/{args.date}-oi-signal-timing-v1.csv")
    write_csv(rows,out)
    print(f"\nCSV: {out}")

if __name__=="__main__":
    main()
