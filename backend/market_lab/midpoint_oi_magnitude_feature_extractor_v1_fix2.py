from __future__ import annotations

"""
MIDPOINT_OI_MAGNITUDE_FEATURE_EXTRACTOR_V1_FIX2

Critical fixes over FIX1:
1) Read outcome from top-level quality_bucket / nested option_economics.net_5m_pct.
2) Use oi_vwap_checkpoint_timestamp directly for causal OI alignment.
3) Fail loudly on zero-event / zero-row extraction.
4) Keep overall OI + exact 5m OI change % for ATM and ATM±2 same-strike band.

Research only:
TRAIN + OOS_A-D allowed.
OOS_E/F/G/H forbidden.
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

RESEARCH_VERSION = "MIDPOINT_OI_MAGNITUDE_FEATURE_EXTRACTOR_V1_FIX2"

ALLOWED = {"TRAIN","OOS_A","OOS_B","OOS_C","OOS_D"}
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}

WIN_BUCKETS = {
    "EXCELLENT_5M_GE_10",
    "GOOD_5M_3_TO_10",
}
LOSS_BUCKETS = {
    "LOSS_5M_0_TO_MINUS5",
    "LARGE_LOSS_5M_LE_MINUS5",
}
EXCLUDED_BUCKETS = {
    "SMALL_WIN_5M_0_TO_3",
}


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


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError("Refusing to write empty feature CSV")
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


def outcome_from_event(e):
    bucket=str(e.get("quality_bucket") or "").strip()
    if bucket in WIN_BUCKETS:
        return "WINNER"
    if bucket in LOSS_BUCKETS:
        return "LOSER"
    if bucket in EXCLUDED_BUCKETS:
        return "SMALL_WIN"

    # Defensive fallback only if quality_bucket is absent.
    econ=e.get("option_economics") or {}
    net5=num(econ.get("net_5m_pct"))
    if net5 is None:
        return None
    if net5 >= 3:
        return "WINNER"
    if 0 < net5 < 3:
        return "SMALL_WIN"
    return "LOSER"


def net5_from_event(e):
    econ=e.get("option_economics") or {}
    return num(econ.get("net_5m_pct"))


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
        "pm2_ce_oi_previous":prev_ce,
        "pm2_ce_oi":cur_ce,
        "pm2_pe_oi_previous":prev_pe,
        "pm2_pe_oi":cur_pe,
        "pm2_ce_oi_change_abs":cur_ce-prev_ce,
        "pm2_pe_oi_change_abs":cur_pe-prev_pe,
        "pm2_ce_oi_change_pct_5m":pct(cur_ce,prev_ce),
        "pm2_pe_oi_change_pct_5m":pct(cur_pe,prev_pe),
        "pm2_oi_pcr_previous":prev_pe/prev_ce if prev_ce else None,
        "pm2_oi_pcr":cur_pe/cur_ce if cur_ce else None,
        "pm2_common_strike_count":len(common),
        "pm2_common_strikes":";".join(str(int(s)) for s in common),
    }


def load_events(path: Path):
    doc=json.loads(path.read_text(encoding="utf-8"))
    events=doc.get("events")
    if not isinstance(events, list):
        raise RuntimeError("Expected top-level events array")

    if len(events) == 0:
        raise RuntimeError("Global exemplar events array is empty")

    kept=[]
    bucket_counts={}
    excluded_small=0
    missing_outcome=0

    for e in events:
        block=str(e.get("block","")).strip()

        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block found in global exemplar events: {block}")
        if block not in ALLOWED:
            continue

        bucket=str(e.get("quality_bucket") or "MISSING")
        bucket_counts[bucket]=bucket_counts.get(bucket,0)+1

        grp=outcome_from_event(e)
        if grp == "SMALL_WIN":
            excluded_small += 1
            continue
        if grp is None:
            missing_outcome += 1
            continue

        signal_ts=parse_ts(e.get("signal_timestamp"))
        checkpoint_ts=parse_ts(e.get("oi_vwap_checkpoint_timestamp"))
        if not signal_ts or not checkpoint_ts:
            continue

        kept.append({
            "block":block,
            "session_date":e.get("session_date"),
            "direction":e.get("direction"),
            "setup_type":e.get("setup_type"),
            "decision_family":e.get("decision_family"),
            "signal_timestamp":signal_ts,
            "checkpoint_timestamp":checkpoint_ts,
            "quality_bucket":bucket,
            "net_5m_pct":net5_from_event(e),
            "outcome_group":grp,
        })

    if not kept:
        raise RuntimeError(
            "Outcome-filtered event population is zero. "
            f"bucket_counts={bucket_counts}"
        )

    return events, kept, bucket_counts, excluded_small, missing_outcome


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--events-json", required=True)
    ap.add_argument("--positioning", action="append", required=True,
                    help="BLOCK|path.csv")
    ap.add_argument("--output", required=True)
    args=ap.parse_args()

    all_events, events, bucket_counts, excluded_small, missing_outcome = load_events(Path(args.events_json))

    pos={}
    for spec in args.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden positioning block: {block}")
        if block not in ALLOWED:
            continue
        rows=read_csv(Path(path))
        cols=detect_cols(rows)
        pos[block]=(cols, snapshots(rows, cols["timestamp"]))

    rows_out=[]
    skipped_no_block=0
    skipped_no_snapshot=0
    skipped_no_atm=0

    for e in events:
        block=e["block"]
        if block not in pos:
            skipped_no_block += 1
            continue

        cols, snaps = pos[block]

        # Critical causal alignment: use the checkpoint already frozen by
        # the global exemplar analysis, not floor(signal_timestamp).
        cp=e["checkpoint_timestamp"]
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
            "signal_timestamp":e["signal_timestamp"].isoformat(),
            "checkpoint_timestamp":cp.isoformat(),
            "previous_checkpoint_timestamp":prev.isoformat(),
            "quality_bucket":e["quality_bucket"],
            "outcome_group":e["outcome_group"],
            "net_5m_pct":e["net_5m_pct"],
            "atm_strike":atm,

            "atm_ce_oi_previous":prev_ce,
            "atm_ce_oi":atm_ce,
            "atm_ce_oi_change_abs":None if atm_ce is None or prev_ce is None else atm_ce-prev_ce,
            "atm_ce_oi_change_pct_5m":pct(atm_ce,prev_ce),

            "atm_pe_oi_previous":prev_pe,
            "atm_pe_oi":atm_pe,
            "atm_pe_oi_change_abs":None if atm_pe is None or prev_pe is None else atm_pe-prev_pe,
            "atm_pe_oi_change_pct_5m":pct(atm_pe,prev_pe),
        }

        row.update(aggregate_band(cur,prv,cols,atm,2))
        rows_out.append(row)

    if not rows_out:
        raise RuntimeError(
            "Feature extraction produced zero rows. "
            f"events_after_outcome_filter={len(events)}, "
            f"skipped_no_block={skipped_no_block}, "
            f"skipped_no_snapshot={skipped_no_snapshot}, "
            f"skipped_no_atm={skipped_no_atm}"
        )

    write_csv(Path(args.output), rows_out)

    result={
        "research_version":RESEARCH_VERSION,
        "global_event_count":len(all_events),
        "quality_bucket_counts":bucket_counts,
        "excluded_small_win_count":excluded_small,
        "missing_outcome_count":missing_outcome,
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
        "integrity":{
            "used_oi_vwap_checkpoint_timestamp":True,
            "nested_option_economics_supported":True,
            "quality_bucket_used_for_grouping":True,
            "same_strike_5m_comparison":True,
            "overall_oi_retained":True,
            "oos_e_f_g_h_used":False,
            "threshold_tuning_performed":False,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
        },
        "output":args.output,
    }
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
