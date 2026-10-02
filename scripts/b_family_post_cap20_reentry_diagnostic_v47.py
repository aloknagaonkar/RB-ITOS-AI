#!/usr/bin/env python3
"""
B FAMILY — V47 POST-CAP20 RECOVERY / RE-ENTRY DIAGNOSTIC

Purpose
-------
Study the 5 actual CAP20 rescue exits from V43/V44/V45 and measure what happens
AFTER the rescue, without creating a live re-entry rule.

No tuning.
No entry/exit rule changes.
No re-entry orders.

For each rescue event V47 reconstructs:
- original B event
- +20 proof
- +10m RUNNER_STRENGTHENING classification
- first DEGRADED state
- degraded-start directional close target
- CAP20 rescue timestamp

Then measures after rescue:
1) time to retake degraded target
2) time to retake rescue-exit price
3) time to new MFE
4) additional adverse excursion before new MFE / terminal
5) directional futures-VWAP recovery
6) +1/+3/+5/+10 minute checkpoints
7) descriptive causal re-entry markers:
   A. PRICE_RETAKE:
      first close back above degraded target
   B. PRICE_RETAKE_AND_VWAP_RECOVERY:
      first close above degraded target AND directional futures-VWAP above
      its value at rescue
   C. PRICE_RETAKE_AND_POSITIVE_VWAP_CHANGE:
      first close above degraded target AND directional futures-VWAP change
      vs prior minute > 0

These are DIAGNOSTIC markers only. V47 does not select a production rule.

Underlying NIFTY directional points only.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

V46_EVENTS = (
    RESEARCH / "b-family-cap20-rescue-diagnostic-v46"
    / "cap20-rescue-events-v46.csv"
)

OUTDIR = RESEARCH / "b-family-post-cap20-reentry-diagnostic-v47"
EVENTS_CSV = OUTDIR / "post-cap20-recovery-events-v47.csv"
CHECKPOINTS_CSV = OUTDIR / "post-cap20-checkpoints-v47.csv"
REPORT_JSON = OUTDIR / "report-v47.json"
SUMMARY_TXT = OUTDIR / "summary-v47.txt"

CHECKPOINTS = (1,3,5,10)

ALIASES = {
    "session_date": ("session_date","date","trade_date"),
    "direction": ("direction","side","signal_direction"),
    "entry_timestamp": ("entry_timestamp","entry_time","entry_ts"),
    "entry_close": ("entry_close","entry_price","entry_underlying_close"),
    "structural_invalidation_timestamp": (
        "structural_invalidation_timestamp",
        "invalidation_timestamp",
        "structural_exit_timestamp",
        "exit_timestamp",
    ),
    "plus20_timestamp": ("plus20_timestamp","plus_20_timestamp","p20_timestamp"),
}


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("",None) else float(v)


def b(v):
    return str(v).strip().lower() == "true"


def parse_dt(s):
    return datetime.fromisoformat(s)


def plus_minutes(ts,n):
    return (parse_dt(ts)+timedelta(minutes=n)).isoformat()


def directional(direction,entry,price):
    return price-entry if direction=="BULLISH" else entry-price


def directional_vwap(direction,row):
    if row is None:
        return None
    raw=row["close"]-row["vwap"]
    return raw if direction=="BULLISH" else -raw


def favorable(direction,bar):
    return bar["high"] if direction=="BULLISH" else bar["low"]


def adverse(direction,bar):
    return bar["low"] if direction=="BULLISH" else bar["high"]


def stats(vals):
    xs=[float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(
        n=len(xs),total=sum(xs),mean=mean(xs),median=median(xs),
        min=min(xs),max=max(xs)
    )


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def mins(a,b):
    return (parse_dt(b)-parse_dt(a)).total_seconds()/60.0


def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def discover_underlying():
    by=defaultdict(dict)
    needed={r["session_date"] for r in load_csv(V46_EVENTS)}
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if not rows or not {"session_date","timestamp","open","high","low","close"}.issubset(rows[0]):
            continue
        for r in rows:
            d=r["session_date"]
            if d in needed:
                by[d][r["timestamp"]]={
                    "open":float(r["open"]),"high":float(r["high"]),
                    "low":float(r["low"]),"close":float(r["close"]),
                }
    return dict(by)


def discover_futures():
    by=defaultdict(dict)
    needed={r["session_date"] for r in load_csv(V46_EVENTS)}
    for p in ROOT.rglob("*.csv"):
        n=p.name.lower()
        if "futures" not in n or "vwap" not in n:
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if not rows or not {"session_date","timestamp","close","session_vwap"}.issubset(rows[0]):
            continue
        for r in rows:
            d=r["session_date"]
            if d in needed and r.get("session_vwap") not in ("",None):
                by[d][r["timestamp"]]={
                    "close":float(r["close"]),
                    "vwap":float(r["session_vwap"]),
                }
    return dict(by)


def first_present(row,names):
    for n in names:
        if n in row and row.get(n) not in ("",None):
            return row.get(n)
    return None


def normalize_event_row(raw):
    r=dict(raw)
    for canon, aliases in ALIASES.items():
        v=first_present(raw,aliases)
        if v not in ("",None):
            r[canon]=v
    d=r.get("session_date")
    direction=str(r.get("direction","")).upper()
    ets=r.get("entry_timestamp")
    if not d or not ets or direction not in ("BULLISH","BEARISH"):
        return None
    r["direction"]=direction
    return r


def discover_original_events():
    rescue_rows=load_csv(V46_EVENTS)
    wanted={(r["session_date"],r["direction"],r["entry_timestamp"]) for r in rescue_rows}
    found={}

    for p in RESEARCH.rglob("*.csv"):
        if "v47" in str(p).lower():
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if not rows:
            continue

        headers=set(rows[0])
        if not any(x in headers for x in ALIASES["session_date"]): continue
        if not any(x in headers for x in ALIASES["direction"]): continue
        if not any(x in headers for x in ALIASES["entry_timestamp"]): continue

        for raw in rows:
            r=normalize_event_row(raw)
            if not r:
                continue
            k=(r["session_date"],r["direction"],r["entry_timestamp"])
            if k not in wanted:
                continue

            richness=sum(r.get(x) not in ("",None) for x in (
                "entry_close","structural_invalidation_timestamp",
                "plus20_timestamp","mfe","mae",
                "observation_end_timestamp","classification"
            ))

            if k not in found or richness > found[k][0]:
                found[k]=(richness,r,str(p))

    return {k:(v[1],v[2]) for k,v in found.items()}


def terminal_for_event(event,u):
    entry_ts=event["entry_timestamp"]
    entry=f(event.get("entry_close"))
    if entry is None:
        if entry_ts not in u:
            return None
        entry=u[entry_ts]["close"]

    invalid=event.get("structural_invalidation_timestamp") or None
    trusted=sorted(u)

    if invalid and invalid in u:
        t=invalid
        typ="STRUCTURAL_INVALIDATION"
    else:
        t=trusted[-1]
        typ="SESSION_CUTOFF"

    return {
        "entry_close":entry,
        "terminal_timestamp":t,
        "terminal_type":typ,
    }


def find_plus20(event,u,terminal,entry):
    src=event.get("plus20_timestamp")
    if src and src in u and src<terminal:
        return src
    for ts in sorted(u):
        if ts<=event["entry_timestamp"]: continue
        if ts>=terminal: break
        if directional(event["direction"],entry,
                       favorable(event["direction"],u[ts])) >= 20:
            return ts
    return None


def classify_runner(event,p20,u,fut,entry,terminal):
    cts=plus_minutes(p20,10)
    if cts>=terminal or p20 not in u or cts not in u:
        return None
    if p20 not in fut or cts not in fut:
        return None

    d=event["direction"]
    net=(directional(d,entry,u[cts]["close"])
         - directional(d,entry,u[p20]["close"]))
    dv=(directional_vwap(d,fut[cts])
        - directional_vwap(d,fut[p20]))

    return {
        "classification_timestamp":cts,
        "net_progress_10m":net,
        "directional_vwap_change_10m":dv,
        "runner_strengthening":net>0 and dv>0,
    }


def first_degraded(event,cts,u,fut,entry,terminal):
    d=event["direction"]
    running=None
    prevdv=None
    prior_joint=False

    for ts in sorted(u):
        if ts<=event["entry_timestamp"]: continue
        if ts>cts or ts>=terminal: break
        move=directional(d,entry,u[ts]["close"])
        running=move if running is None else max(running,move)
        dv=directional_vwap(d,fut.get(ts))
        if dv is not None:
            prevdv=dv

    for ts in sorted(u):
        if ts<=cts: continue
        if ts>=terminal: break

        move=directional(d,entry,u[ts]["close"])
        running=move if running is None else max(running,move)
        dd=running-move

        dv=directional_vwap(d,fut.get(ts))
        dvc=None if dv is None or prevdv is None else dv-prevdv
        joint=dd>0 and dvc is not None and dvc<0

        if joint and not prior_joint:
            return {
                "degraded_timestamp":ts,
                "target_move":move,
                "running_close_mfe":running,
            }

        prior_joint=joint
        if dv is not None:
            prevdv=dv

    return None


def first_after(ts0,terminal,u,predicate):
    for ts in sorted(u):
        if ts<=ts0:
            continue
        if ts>=terminal:
            break
        if predicate(ts):
            return ts
    return None


def next_new_mfe(event,u,entry,rescue_ts,terminal):
    d=event["direction"]
    pre=None
    for ts in sorted(u):
        if ts>rescue_ts:
            break
        fav=directional(d,entry,favorable(d,u[ts]))
        pre=fav if pre is None else max(pre,fav)

    if pre is None:
        return None,None

    for ts in sorted(u):
        if ts<=rescue_ts:
            continue
        if ts>=terminal:
            break
        fav=directional(d,entry,favorable(d,u[ts]))
        if fav>pre+1e-9:
            return ts,fav

    return None,None


def additional_adverse_before(event,u,entry,rescue_ts,end_ts):
    d=event["direction"]
    rescue_move=directional(d,entry,u[rescue_ts]["close"])
    worst=0.0
    worst_ts=None

    for ts in sorted(u):
        if ts<=rescue_ts:
            continue
        if end_ts and ts>end_ts:
            break
        adverse_move=directional(d,entry,adverse(d,u[ts]))
        damage=rescue_move-adverse_move
        if damage>worst:
            worst=damage
            worst_ts=ts

    return worst,worst_ts


def main():
    print("B FAMILY — V47 POST-CAP20 RECOVERY / RE-ENTRY DIAGNOSTIC")
    print("="*118)

    rescues=load_csv(V46_EVENTS)
    if len(rescues)!=5:
        print(f"WARNING: expected 5 rescues, found {len(rescues)}")

    uall=discover_underlying()
    fall=discover_futures()
    originals=discover_original_events()

    event_rows=[]
    checkpoint_rows=[]

    for rr in rescues:
        k=(rr["session_date"],rr["direction"],rr["entry_timestamp"])
        if k not in originals:
            raise SystemExit(f"STOP: original event not found: {k}")

        event,source=originals[k]
        d=event["session_date"]
        u=uall.get(d)
        fut=fall.get(d)

        if not u or not fut:
            raise SystemExit(f"STOP: raw data missing for {d}")

        base=terminal_for_event(event,u)
        if base is None:
            raise SystemExit(f"STOP: terminal reconstruction failed for {k}")

        entry=base["entry_close"]
        terminal=base["terminal_timestamp"]
        rescue_ts=rr["exit_timestamp"]

        if rescue_ts not in u:
            raise SystemExit(f"STOP: rescue timestamp missing in underlying: {rescue_ts}")

        p20=find_plus20(event,u,terminal,entry)
        cls=classify_runner(event,p20,u,fut,entry,terminal)
        if not cls or not cls["runner_strengthening"]:
            raise SystemExit(f"STOP: runner reconstruction failed for {k}")

        degraded=first_degraded(
            event,cls["classification_timestamp"],
            u,fut,entry,terminal
        )
        if not degraded:
            raise SystemExit(f"STOP: degraded reconstruction failed for {k}")

        target=degraded["target_move"]
        rescue_move=directional(event["direction"],entry,u[rescue_ts]["close"])
        rescue_dv=directional_vwap(event["direction"],fut.get(rescue_ts))

        price_retake_ts=first_after(
            rescue_ts,terminal,u,
            lambda ts: directional(event["direction"],entry,u[ts]["close"]) > target
        )

        rescue_price_retake_ts=first_after(
            rescue_ts,terminal,u,
            lambda ts: directional(event["direction"],entry,u[ts]["close"]) > rescue_move
        )

        both_retake_vwap_ts=None
        both_retake_pos_vwap_change_ts=None
        prev_dv=None

        for ts in sorted(u):
            if ts<=rescue_ts:
                dv=directional_vwap(event["direction"],fut.get(ts))
                if dv is not None:
                    prev_dv=dv
                continue
            if ts>=terminal:
                break

            move=directional(event["direction"],entry,u[ts]["close"])
            dv=directional_vwap(event["direction"],fut.get(ts))
            dvc=None if dv is None or prev_dv is None else dv-prev_dv

            if both_retake_vwap_ts is None:
                if move>target and dv is not None and rescue_dv is not None and dv>rescue_dv:
                    both_retake_vwap_ts=ts

            if both_retake_pos_vwap_change_ts is None:
                if move>target and dvc is not None and dvc>0:
                    both_retake_pos_vwap_change_ts=ts

            if dv is not None:
                prev_dv=dv

        new_mfe_ts,new_mfe_move=next_new_mfe(
            event,u,entry,rescue_ts,terminal
        )

        adverse_end=new_mfe_ts or terminal
        add_adverse,worst_ts=additional_adverse_before(
            event,u,entry,rescue_ts,adverse_end
        )

        rec={
            "block":rr["block"],
            "session_date":d,
            "direction":event["direction"],
            "entry_timestamp":event["entry_timestamp"],
            "event_source":source,
            "rescue_timestamp":rescue_ts,
            "rescue_points":rescue_move,
            "baseline_points":f(rr["baseline_points"]),
            "delta_vs_baseline":f(rr["delta_vs_baseline"]),
            "degraded_timestamp":degraded["degraded_timestamp"],
            "degraded_target_move":target,
            "classification_timestamp":cls["classification_timestamp"],
            "price_retake_target_timestamp":price_retake_ts,
            "minutes_to_price_retake_target":mins(rescue_ts,price_retake_ts) if price_retake_ts else None,
            "retake_rescue_price_timestamp":rescue_price_retake_ts,
            "minutes_to_retake_rescue_price":mins(rescue_ts,rescue_price_retake_ts) if rescue_price_retake_ts else None,
            "price_retake_and_vwap_recovery_timestamp":both_retake_vwap_ts,
            "minutes_to_price_retake_and_vwap_recovery":mins(rescue_ts,both_retake_vwap_ts) if both_retake_vwap_ts else None,
            "price_retake_and_positive_vwap_change_timestamp":both_retake_pos_vwap_change_ts,
            "minutes_to_price_retake_and_positive_vwap_change":mins(rescue_ts,both_retake_pos_vwap_change_ts) if both_retake_pos_vwap_change_ts else None,
            "new_mfe_timestamp":new_mfe_ts,
            "minutes_to_new_mfe":mins(rescue_ts,new_mfe_ts) if new_mfe_ts else None,
            "new_mfe_directional_move":new_mfe_move,
            "additional_adverse_before_new_mfe_or_terminal":add_adverse,
            "worst_adverse_timestamp":worst_ts,
            "later_new_mfe":b(rr["later_new_mfe"]),
        }
        event_rows.append(rec)

        for cp in CHECKPOINTS:
            ts=plus_minutes(rescue_ts,cp)
            if ts not in u or ts>=terminal:
                checkpoint_rows.append({
                    "block":rr["block"],
                    "session_date":d,
                    "direction":event["direction"],
                    "entry_timestamp":event["entry_timestamp"],
                    "rescue_timestamp":rescue_ts,
                    "checkpoint_minutes":cp,
                    "timestamp":ts,
                    "available":False,
                })
                continue

            move=directional(event["direction"],entry,u[ts]["close"])
            dv=directional_vwap(event["direction"],fut.get(ts))
            checkpoint_rows.append({
                "block":rr["block"],
                "session_date":d,
                "direction":event["direction"],
                "entry_timestamp":event["entry_timestamp"],
                "rescue_timestamp":rescue_ts,
                "checkpoint_minutes":cp,
                "timestamp":ts,
                "available":True,
                "directional_close_move":move,
                "price_change_vs_rescue":move-rescue_move,
                "directional_vwap":dv,
                "vwap_change_vs_rescue":None if dv is None or rescue_dv is None else dv-rescue_dv,
                "above_degraded_target":move>target,
            })

    later=[r for r in event_rows if r["later_new_mfe"]]
    no_later=[r for r in event_rows if not r["later_new_mfe"]]

    summary_stats={
        "minutes_to_price_retake_target":stats(r["minutes_to_price_retake_target"] for r in event_rows),
        "minutes_to_price_retake_and_vwap_recovery":stats(r["minutes_to_price_retake_and_vwap_recovery"] for r in event_rows),
        "minutes_to_price_retake_and_positive_vwap_change":stats(r["minutes_to_price_retake_and_positive_vwap_change"] for r in event_rows),
        "minutes_to_new_mfe_later_group":stats(r["minutes_to_new_mfe"] for r in later),
        "additional_adverse_later_group":stats(r["additional_adverse_before_new_mfe_or_terminal"] for r in later),
        "additional_adverse_no_later_group":stats(r["additional_adverse_before_new_mfe_or_terminal"] for r in no_later),
    }

    lines=[
        "B FAMILY — V47 POST-CAP20 RECOVERY / RE-ENTRY DIAGNOSTIC",
        "="*118,
        f"rescue_events={len(event_rows)}",
        f"later_new_mfe={len(later)}/{len(event_rows)}",
        "",
        "RECOVERY TIMING",
        "-"*118,
        f"price retake degraded target: "
        f"n={summary_stats['minutes_to_price_retake_target']['n']} "
        f"median={fmt(summary_stats['minutes_to_price_retake_target']['median'])}m "
        f"mean={fmt(summary_stats['minutes_to_price_retake_target']['mean'])}m",
        f"price retake + VWAP above rescue level: "
        f"n={summary_stats['minutes_to_price_retake_and_vwap_recovery']['n']} "
        f"median={fmt(summary_stats['minutes_to_price_retake_and_vwap_recovery']['median'])}m "
        f"mean={fmt(summary_stats['minutes_to_price_retake_and_vwap_recovery']['mean'])}m",
        f"price retake + positive 1m VWAP change: "
        f"n={summary_stats['minutes_to_price_retake_and_positive_vwap_change']['n']} "
        f"median={fmt(summary_stats['minutes_to_price_retake_and_positive_vwap_change']['median'])}m "
        f"mean={fmt(summary_stats['minutes_to_price_retake_and_positive_vwap_change']['mean'])}m",
        f"later-new-MFE group rescue→newMFE: "
        f"n={summary_stats['minutes_to_new_mfe_later_group']['n']} "
        f"median={fmt(summary_stats['minutes_to_new_mfe_later_group']['median'])}m "
        f"mean={fmt(summary_stats['minutes_to_new_mfe_later_group']['mean'])}m",
        "",
        "POST-RESCUE ADVERSE EXCURSION",
        "-"*118,
        f"later-new-MFE group: "
        f"median={fmt(summary_stats['additional_adverse_later_group']['median'])} "
        f"mean={fmt(summary_stats['additional_adverse_later_group']['mean'])}",
        f"no-later-MFE group: "
        f"median={fmt(summary_stats['additional_adverse_no_later_group']['median'])} "
        f"mean={fmt(summary_stats['additional_adverse_no_later_group']['mean'])}",
        "",
        "PER-EVENT",
        "-"*118,
    ]

    for r in sorted(event_rows,key=lambda x:(x["session_date"],x["entry_timestamp"])):
        lines.append(
            f"{r['block']} {r['session_date']} {r['direction']} "
            f"rescue={fmt(r['rescue_points'])} Δbase={fmt(r['delta_vs_baseline'])} "
            f"laterNewMFE={r['later_new_mfe']} "
            f"retakeTarget={fmt(r['minutes_to_price_retake_target'])}m "
            f"retake+VWAP={fmt(r['minutes_to_price_retake_and_vwap_recovery'])}m "
            f"retake+posVWAP={fmt(r['minutes_to_price_retake_and_positive_vwap_change'])}m "
            f"newMFE={fmt(r['minutes_to_new_mfe'])}m "
            f"addAdverse={fmt(r['additional_adverse_before_new_mfe_or_terminal'])}"
        )

    lines += [
        "",
        "INTERPRETATION GUARD",
        "-"*118,
        "- V47 is descriptive only. No re-entry condition is selected.",
        "- The sample is only five CAP20 rescues.",
        "- A useful future re-entry candidate should recover missed runners without re-entering the two rescues that never made a new MFE.",
        "- Do not turn V47 medians directly into thresholds.",
        "- Any actual re-entry candidate must be frozen first and then validated on a separate block.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(EVENTS_CSV,event_rows)
    write_csv(CHECKPOINTS_CSV,checkpoint_rows)
    REPORT_JSON.write_text(json.dumps({
        "version":"V47",
        "rescue_events":len(event_rows),
        "later_new_mfe_count":len(later),
        "summary_stats":summary_stats,
        "events":event_rows,
    },indent=2))
    SUMMARY_TXT.write_text("\n".join(lines)+"\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENTS CSV   :",EVENTS_CSV)
    print("CHECKPOINTS  :",CHECKPOINTS_CSV)
    print("REPORT JSON  :",REPORT_JSON)
    print("SUMMARY      :",SUMMARY_TXT)

if __name__=="__main__":
    main()
