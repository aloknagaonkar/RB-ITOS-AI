from __future__ import annotations

"""
MIDPOINT_OI_MAGNITUDE_FEATURE_EXTRACTOR_V1

Builds a development-wide CSV of OI magnitude features aligned to existing
structural/global-exemplar events.

Important:
- exact 5-minute checkpoint-to-checkpoint comparisons
- same-strike comparison
- ATM + ATM±2 aggregates
- overall OI retained
- OI-change % retained
- no OOS E/F/G/H
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

FORBIDDEN={"OOS_E","OOS_F","OOS_G","OOS_H"}


def num(v):
    if v in ("",None): return None
    try: return float(v)
    except Exception: return None


def parse_ts(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None


def pct(cur,prev):
    if cur is None or prev in (None,0): return None
    return (cur-prev)/prev*100.0


def read_csv(path):
    with Path(path).open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path,rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def by_ts_strike(rows):
    out={}
    for r in rows:
        ts=parse_ts(r.get("timestamp") or r.get("datetime") or r.get("provider_timestamp") or r.get("time"))
        if not ts: continue
        strike=num(r.get("strike") or r.get("strike_price"))
        if strike is None: continue
        out[(ts,strike)]=r
    return out


def snapshots(rows):
    out={}
    for r in rows:
        ts=parse_ts(r.get("timestamp") or r.get("datetime") or r.get("provider_timestamp") or r.get("time"))
        if not ts: continue
        out.setdefault(ts,[]).append(r)
    return out


def detect_cols(rows):
    keys=set().union(*(r.keys() for r in rows))
    def first(*xs):
        for x in xs:
            if x in keys:return x
        return None
    cols={
        "strike":first("strike","strike_price"),
        "offset":first("strike_offset","offset"),
        "atm":first("moving_atm","atm","atm_strike"),
        "ce_oi":first("ce_oi","call_oi","ce_open_interest","call_open_interest"),
        "pe_oi":first("pe_oi","put_oi","pe_open_interest","put_open_interest"),
    }
    miss=[k for k,v in cols.items() if v is None]
    if miss:
        raise RuntimeError("Missing positioning columns: "+", ".join(miss))
    return cols


def aggregate_band(cur,prev,cols,center,width=2):
    wanted={center+i*50 for i in range(-width,width+1)}
    cm={num(r[cols["strike"]]):r for r in cur}
    pm={num(r[cols["strike"]]):r for r in prev}
    common=sorted(wanted & set(cm) & set(pm))
    if not common:
        return {}
    cur_ce=sum(num(cm[s][cols["ce_oi"]]) or 0 for s in common)
    prev_ce=sum(num(pm[s][cols["ce_oi"]]) or 0 for s in common)
    cur_pe=sum(num(cm[s][cols["pe_oi"]]) or 0 for s in common)
    prev_pe=sum(num(pm[s][cols["pe_oi"]]) or 0 for s in common)
    return {
        "pm2_ce_oi":cur_ce,
        "pm2_pe_oi":cur_pe,
        "pm2_ce_oi_change_pct_5m":pct(cur_ce,prev_ce),
        "pm2_pe_oi_change_pct_5m":pct(cur_pe,prev_pe),
        "pm2_oi_pcr":cur_pe/cur_ce if cur_ce else None,
        "pm2_common_strike_count":len(common),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--events",required=True,
                    help="CSV containing structural events with block/session/direction/confirmation timestamp/outcome group")
    ap.add_argument("--positioning",action="append",required=True,
                    help="BLOCK|path.csv ; repeat for TRAIN/OOS_A/OOS_B/OOS_C/OOS_D")
    ap.add_argument("--output",required=True)
    args=ap.parse_args()

    event_rows=read_csv(args.events)
    pos={}
    for spec in args.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")
        rows=read_csv(path)
        pos[block]=(rows,detect_cols(rows),snapshots(rows))

    out=[]
    for e in event_rows:
        block=str(e.get("block",""))
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden event block: {block}")
        if block not in pos:
            continue
        ts=parse_ts(e.get("confirmation_timestamp") or e.get("signal_timestamp") or e.get("timestamp"))
        if not ts:
            continue

        # Align to completed 5-minute checkpoint at/before event timestamp.
        minute=(ts.minute//5)*5
        cp=ts.replace(minute=minute,second=0,microsecond=0)
        prev=cp.replace(minute=cp.minute-5) if cp.minute>=5 else (cp.replace(hour=cp.hour-1,minute=55))

        rows,cols,snaps=pos[block]
        cur=snaps.get(cp,[])
        prv=snaps.get(prev,[])
        if not cur or not prv:
            continue

        atm_rows=[r for r in cur if num(r[cols["offset"]])==0]
        if not atm_rows:
            continue
        atm=num(atm_rows[0][cols["atm"]])
        if atm is None:
            continue

        cm={num(r[cols["strike"]]):r for r in cur}
        pm={num(r[cols["strike"]]):r for r in prv}
        cr=cm.get(atm); pr=pm.get(atm)
        if not cr or not pr:
            continue

        atm_ce=num(cr[cols["ce_oi"]]); prev_ce=num(pr[cols["ce_oi"]])
        atm_pe=num(cr[cols["pe_oi"]]); prev_pe=num(pr[cols["pe_oi"]])

        row={
            "block":block,
            "session_date":e.get("session_date"),
            "direction":e.get("direction"),
            "event_timestamp":ts.isoformat(),
            "checkpoint_timestamp":cp.isoformat(),
            "previous_checkpoint_timestamp":prev.isoformat(),
            "outcome_group":e.get("outcome_group"),
            "atm_strike":atm,
            "atm_ce_oi":atm_ce,
            "atm_pe_oi":atm_pe,
            "atm_ce_oi_change_pct_5m":pct(atm_ce,prev_ce),
            "atm_pe_oi_change_pct_5m":pct(atm_pe,prev_pe),
        }
        row.update(aggregate_band(cur,prv,cols,atm,2))
        out.append(row)

    write_csv(args.output,out)
    print(json.dumps({
        "rows_written":len(out),
        "output":args.output,
        "blocks":sorted(set(r["block"] for r in out)),
        "forbidden_used":False
    },indent=2))


if __name__=="__main__":
    main()
