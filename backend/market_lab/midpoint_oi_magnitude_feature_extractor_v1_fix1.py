from __future__ import annotations

"""
MIDPOINT_OI_MAGNITUDE_FEATURE_EXTRACTOR_V1_FIX1

Reads midpoint-global-session-exemplar-analysis-v1-development.json directly.

Population:
- TRAIN + OOS_A + OOS_B + OOS_C + OOS_D only
- OOS_E/F/G/H forbidden
- SMALL_WIN excluded
- WINNER = EXCELLENT (>=10%) or GOOD (3..10%) based on net_5m_pct
- LOSER = LOSS (0..-5%) or LARGE_LOSS (<=-5%)
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

RESEARCH_VERSION = "MIDPOINT_OI_MAGNITUDE_FEATURE_EXTRACTOR_V1_FIX1"
ALLOWED = {"TRAIN","OOS_A","OOS_B","OOS_C","OOS_D"}
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}


def num(v: Any):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_ts(v: Any):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:
        return None


def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur-prev)/prev*100.0


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def detect_cols(rows):
    keys=set().union(*(r.keys() for r in rows))
    def first(*xs):
        for x in xs:
            if x in keys:
                return x
        return None
    cols={
        "timestamp":first("timestamp","datetime","provider_timestamp","time"),
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


def snapshots(rows, ts_col):
    out={}
    for r in rows:
        ts=parse_ts(r.get(ts_col))
        if ts:
            out.setdefault(ts, []).append(r)
    return out


def outcome_group(net5):
    if net5 is None:
        return None
    if net5 >= 10:
        return "WINNER"
    if 3 <= net5 < 10:
        return "WINNER"
    if 0 < net5 < 3:
        return "SMALL_WIN"
    if -5 < net5 <= 0:
        return "LOSER"
    if net5 <= -5:
        return "LOSER"
    return None


def aggregate_band(cur, prev, cols, center, width=2):
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


def floor_5m(ts: datetime):
    return ts.replace(minute=(ts.minute//5)*5, second=0, microsecond=0)


def load_events(path: Path):
    doc=json.loads(path.read_text(encoding="utf-8"))
    events=doc.get("events")
    if not isinstance(events, list):
        raise RuntimeError("Expected top-level 'events' array in global exemplar JSON")

    out=[]
    for e in events:
        block=str(e.get("block",""))
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block found in events: {block}")
        if block not in ALLOWED:
            continue
        net5=num(e.get("net_5m_pct"))
        grp=outcome_group(net5)
        if grp == "SMALL_WIN" or grp is None:
            continue
        ts=parse_ts(e.get("signal_timestamp") or e.get("confirmation_timestamp"))
        if not ts:
            continue
        out.append({
            "block":block,
            "session_date":e.get("session_date"),
            "direction":e.get("direction"),
            "setup_type":e.get("setup_type"),
            "decision_family":e.get("decision_family"),
            "signal_timestamp":ts,
            "net_5m_pct":net5,
            "outcome_group":grp,
        })
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--events-json", required=True)
    ap.add_argument("--positioning", action="append", required=True,
                    help="BLOCK|path.csv")
    ap.add_argument("--output", required=True)
    args=ap.parse_args()

    events=load_events(Path(args.events_json))

    pos={}
    for spec in args.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden positioning block: {block}")
        if block not in ALLOWED:
            continue
        rows=read_csv(Path(path))
        cols=detect_cols(rows)
        pos[block]=(rows, cols, snapshots(rows, cols["timestamp"]))

    rows_out=[]
    skipped_no_block=0
    skipped_no_snapshot=0
    skipped_no_atm=0

    for e in events:
        block=e["block"]
        if block not in pos:
            skipped_no_block += 1
            continue

        _, cols, snaps = pos[block]
        ts=e["signal_timestamp"]

        # Use the latest completed 5-minute checkpoint at/before the signal timestamp.
        cp=floor_5m(ts)
        prev=cp-timedelta(minutes=5)

        cur=snaps.get(cp,[])
        prv=snaps.get(prev,[])
        if not cur or not prv:
            skipped_no_snapshot += 1
            continue

        atm_rows=[r for r in cur if num(r[cols["offset"]])==0]
        if not atm_rows:
            skipped_no_atm += 1
            continue

        atm=num(atm_rows[0][cols["atm"]])
        if atm is None:
            skipped_no_atm += 1
            continue

        cm={num(r[cols["strike"]]):r for r in cur}
        pm={num(r[cols["strike"]]):r for r in prv}
        cr=cm.get(atm)
        pr=pm.get(atm)
        if not cr or not pr:
            skipped_no_atm += 1
            continue

        atm_ce=num(cr[cols["ce_oi"]]); prev_ce=num(pr[cols["ce_oi"]])
        atm_pe=num(cr[cols["pe_oi"]]); prev_pe=num(pr[cols["pe_oi"]])

        row={
            "block":block,
            "session_date":e["session_date"],
            "direction":e["direction"],
            "setup_type":e["setup_type"],
            "decision_family":e["decision_family"],
            "signal_timestamp":ts.isoformat(),
            "checkpoint_timestamp":cp.isoformat(),
            "previous_checkpoint_timestamp":prev.isoformat(),
            "outcome_group":e["outcome_group"],
            "net_5m_pct":e["net_5m_pct"],
            "atm_strike":atm,
            "atm_ce_oi":atm_ce,
            "atm_pe_oi":atm_pe,
            "atm_ce_oi_change_pct_5m":pct(atm_ce,prev_ce),
            "atm_pe_oi_change_pct_5m":pct(atm_pe,prev_pe),
        }
        row.update(aggregate_band(cur,prv,cols,atm,2))
        rows_out.append(row)

    write_csv(Path(args.output), rows_out)

    print(json.dumps({
        "research_version":RESEARCH_VERSION,
        "events_after_outcome_filter":len(events),
        "rows_written":len(rows_out),
        "skipped_no_block":skipped_no_block,
        "skipped_no_snapshot":skipped_no_snapshot,
        "skipped_no_atm":skipped_no_atm,
        "blocks":sorted(set(r["block"] for r in rows_out)),
        "outcome_counts":{
            "WINNER":sum(1 for r in rows_out if r["outcome_group"]=="WINNER"),
            "LOSER":sum(1 for r in rows_out if r["outcome_group"]=="LOSER"),
        },
        "forbidden_used":False,
        "output":args.output,
    }, indent=2))


if __name__=="__main__":
    main()
