#!/usr/bin/env python3
"""
B FAMILY — V45 THIRD HISTORICAL VALIDATION
PRIMARY_OFF + CAP20 vs BASELINE

Range:
    2024-08-16 through 2025-02-05

Why V45
-------
V43 and V44 both showed:
- W3/AGE30 primary fired 0 times.
- Candidate A and B were identical.
Therefore the primary layer has no repeatable validation evidence so far.

V45 freezes the simpler candidate:
    PRIMARY_OFF + CAP20

and compares it only against the common baseline.

No tuning grid.
No entry changes.

Shared frozen logic
-------------------
- B entry logic unchanged.
- +20 proof.
- V20 RUNNER_STRENGTHENING classifier at +10m:
    net directional price progress > 0
    directional futures-VWAP change > 0.
- DEGRADED:
    running close-MFE drawdown > 0
    AND prior-minute directional futures-VWAP change < 0.
- CAP20 rescue:
    first recovery above degraded-start target,
    then first rebreak below target after >=10 minutes,
    rescue only if current directional points <= +20.
- Otherwise structural invalidation close if available,
  else final trusted session close.

Outputs
-------
- sessions / B / +20 / RUNNER_STRENGTHENING counts
- baseline vs PRIMARY_OFF+CAP20 points
- mean / median / worst / best / maxDD
- rescue / fallback counts
- +30/+40/+50/+75/+100 preservation
- later-new-MFE after rescue exits

Underlying NIFTY directional points only.
"""

from __future__ import annotations
import csv, json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

START_DATE = "2024-08-16"
END_DATE = "2025-02-05"

OUTDIR = RESEARCH / "b-family-primary-off-cap20-validation-v45"
EVENTS_CSV = OUTDIR / "events-v45.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v45.csv"
REPORT_JSON = OUTDIR / "report-v45.json"
SUMMARY_TXT = OUTDIR / "summary-v45.txt"

MILESTONES = (30,40,50,75,100)

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
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))

def f(v):
    return None if v in ("",None) else float(v)

def parse_dt(s):
    return datetime.fromisoformat(s)

def plus_minutes(ts,n):
    return (parse_dt(ts)+timedelta(minutes=n)).isoformat()

def date_in_range(d):
    return START_DATE <= d <= END_DATE

def directional(direction,entry,price):
    return price-entry if direction=="BULLISH" else entry-price

def favorable(direction,bar):
    return bar["high"] if direction=="BULLISH" else bar["low"]

def directional_vwap(direction,row):
    if row is None: return None
    raw=row["close"]-row["vwap"]
    return raw if direction=="BULLISH" else -raw

def stats(vals):
    xs=[float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(n=len(xs),total=sum(xs),mean=mean(xs),median=median(xs),
                min=min(xs),max=max(xs))

def maxdd(vals):
    eq=peak=0.0
    dd=0.0
    for x in vals:
        eq += float(x)
        peak=max(peak,eq)
        dd=min(dd,eq-peak)
    return dd

def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"

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

def discover_underlying():
    by=defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try: rows=load_csv(p)
        except Exception: continue
        if not rows or not {"session_date","timestamp","open","high","low","close"}.issubset(rows[0]):
            continue
        for r in rows:
            d=r["session_date"]
            if date_in_range(d):
                by[d][r["timestamp"]] = {
                    "open":float(r["open"]),"high":float(r["high"]),
                    "low":float(r["low"]),"close":float(r["close"])
                }
    return dict(by)

def discover_futures():
    by=defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        n=p.name.lower()
        if "futures" not in n or "vwap" not in n:
            continue
        try: rows=load_csv(p)
        except Exception: continue
        if not rows or not {"session_date","timestamp","close","session_vwap"}.issubset(rows[0]):
            continue
        for r in rows:
            d=r["session_date"]
            if date_in_range(d) and r.get("session_vwap") not in ("",None):
                by[d][r["timestamp"]] = {
                    "close":float(r["close"]),
                    "vwap":float(r["session_vwap"])
                }
    return dict(by)

def discover_events():
    found={}
    for p in RESEARCH.rglob("*.csv"):
        if "v45" in str(p).lower():
            continue
        try: rows=load_csv(p)
        except Exception: continue
        if not rows: continue

        headers=set(rows[0])
        if not any(x in headers for x in ALIASES["session_date"]): continue
        if not any(x in headers for x in ALIASES["direction"]): continue
        if not any(x in headers for x in ALIASES["entry_timestamp"]): continue

        for raw in rows:
            r=normalize_event_row(raw)
            if not r or not date_in_range(r["session_date"]):
                continue

            event_like=any(r.get(x) not in ("",None) for x in (
                "entry_close","structural_invalidation_timestamp",
                "plus20_timestamp","mfe","mae","candidate","event_type","setup_family"
            ))
            name_like=any(t in p.name.lower() for t in (
                "event","candidate","setup","family","canonical"
            ))
            if not event_like and not name_like:
                continue

            k=(r["session_date"],r["direction"],r["entry_timestamp"])
            richness=sum(r.get(x) not in ("",None) for x in (
                "entry_close","structural_invalidation_timestamp",
                "plus20_timestamp","mfe","mae",
                "observation_end_timestamp","classification"
            ))
            if k not in found or richness > found[k][0]:
                found[k]=(richness,r,str(p))

    return {k:(v[1],v[2]) for k,v in found.items()}

def terminal_for_event(event,u):
    ets=event["entry_timestamp"]
    entry=f(event.get("entry_close"))
    if entry is None:
        if ets not in u:
            return None
        entry=u[ets]["close"]

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
        "baseline_points":directional(event["direction"],entry,u[t]["close"]),
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
        if dv is not None: prevdv=dv

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
            return {"degraded_timestamp":ts,"target_move":move}

        prior_joint=joint
        if dv is not None: prevdv=dv

    return None

def first_recovery(degraded,event,u,entry,terminal):
    target=degraded["target_move"]
    dts=degraded["degraded_timestamp"]

    for ts in sorted(u):
        if ts<=dts: continue
        if ts>=terminal: break
        if directional(event["direction"],entry,u[ts]["close"]) > target:
            return ts
    return None

def cap20_rescue(degraded,recovery_ts,event,u,entry,terminal):
    target=degraded["target_move"]

    for ts in sorted(u):
        if ts<=recovery_ts: continue
        if ts>=terminal: break

        age=(parse_dt(ts)-parse_dt(recovery_ts)).total_seconds()/60
        if age<10: continue

        move=directional(event["direction"],entry,u[ts]["close"])
        if move<target:
            return ts if move<=20 else None

    return None

def later_new_mfe(event,u,entry,exit_ts,terminal):
    pre=None
    for ts in sorted(u):
        if ts>exit_ts: break
        fav=directional(event["direction"],entry,
                        favorable(event["direction"],u[ts]))
        pre=fav if pre is None else max(pre,fav)

    if pre is None: return None

    for ts in sorted(u):
        if ts<=exit_ts: continue
        if ts>=terminal: break
        fav=directional(event["direction"],entry,
                        favorable(event["direction"],u[ts]))
        if fav>pre+1e-9:
            return True
    return False

def milestone_ts(event,u,entry,terminal,m):
    for ts in sorted(u):
        if ts<=event["entry_timestamp"]: continue
        if ts>=terminal: break
        if directional(event["direction"],entry,
                       favorable(event["direction"],u[ts])) >= m:
            return ts
    return None

def score(name,vals,baseline):
    s=stats(vals)
    ds=stats([v-b for v,b in zip(vals,baseline)])
    return {
        "policy":name,
        "n":len(vals),
        "total_points":s["total"],
        "mean_points":s["mean"],
        "median_points":s["median"],
        "worst_points":s["min"],
        "best_points":s["max"],
        "max_drawdown_points":maxdd(vals),
        "delta_vs_baseline_total":ds["total"],
    }

def main():
    print("B FAMILY — V45 THIRD HISTORICAL VALIDATION")
    print("="*118)
    print(f"validation_range={START_DATE}..{END_DATE}")

    uall=discover_underlying()
    fall=discover_futures()
    events=discover_events()

    sessions=sorted(set(uall).intersection(fall))

    print(f"dual_raw_sessions={len(sessions)}")
    print(f"discovered_event_keys={len(events)}")

    if not events:
        raise SystemExit("STOP: no event rows discovered")

    validated=[]
    b_count=p20_count=class_count=rs_count=0

    for _,(event,source) in sorted(
        events.items(), key=lambda kv:(kv[0][0],kv[0][2],kv[0][1])
    ):
        d=event["session_date"]
        if d not in uall or d not in fall:
            continue

        u=uall[d]
        fut=fall[d]
        base=terminal_for_event(event,u)
        if base is None:
            continue

        b_count+=1
        entry=base["entry_close"]
        terminal=base["terminal_timestamp"]

        p20=find_plus20(event,u,terminal,entry)
        if not p20:
            continue
        p20_count+=1

        cls=classify_runner(event,p20,u,fut,entry,terminal)
        if cls is None:
            continue
        class_count+=1

        if not cls["runner_strengthening"]:
            continue
        rs_count+=1

        degraded=first_degraded(
            event,cls["classification_timestamp"],
            u,fut,entry,terminal
        )

        exit_ts=None
        exit_type="FALLBACK_BASELINE"

        if degraded:
            rec=first_recovery(degraded,event,u,entry,terminal)
            if rec:
                rescue=cap20_rescue(degraded,rec,event,u,entry,terminal)
                if rescue:
                    exit_ts=rescue
                    exit_type="CAP20_RESCUE"

        if exit_ts:
            points=directional(event["direction"],entry,u[exit_ts]["close"])
            later=later_new_mfe(event,u,entry,exit_ts,terminal)
        else:
            points=base["baseline_points"]
            later=None

        row={
            "session_date":d,
            "direction":event["direction"],
            "entry_timestamp":event["entry_timestamp"],
            "event_source":source,
            "baseline_points":base["baseline_points"],
            "candidate_exit_type":exit_type,
            "candidate_exit_timestamp":exit_ts,
            "candidate_points":points,
            "delta_vs_baseline":points-base["baseline_points"],
            "later_new_mfe":later,
        }

        for m in MILESTONES:
            mt=milestone_ts(event,u,entry,terminal,m)
            row[f"reached_plus{m}"]=mt is not None
            row[f"exit_before_plus{m}"]=bool(exit_ts and mt and exit_ts<mt)

        validated.append(row)

    if not validated:
        raise SystemExit("STOP: no RUNNER_STRENGTHENING events validated")

    baseline=[r["baseline_points"] for r in validated]
    vals=[r["candidate_points"] for r in validated]

    sb=score("BASELINE",baseline,baseline)
    sc=score("PRIMARY_OFF_CAP20",vals,baseline)

    rescue=sum(r["candidate_exit_type"]=="CAP20_RESCUE" for r in validated)
    fallback=len(validated)-rescue
    actual=[r for r in validated if r["candidate_exit_timestamp"]]
    later=sum(r["later_new_mfe"] is True for r in actual)

    preservation={}
    for m in MILESTONES:
        reached=[r for r in validated if r[f"reached_plus{m}"]]
        cut=[r for r in reached if r[f"exit_before_plus{m}"]]
        preserved=len(reached)-len(cut)
        preservation[m]={
            "reached":len(reached),
            "preserved":preserved,
            "rate":preserved/len(reached) if reached else None,
        }

    lines=[
        "B FAMILY — V45 THIRD HISTORICAL VALIDATION",
        "="*118,
        f"validation_range={START_DATE}..{END_DATE}",
        f"dual_raw_sessions={len(sessions)}",
        f"B/event-like rows accepted={b_count}",
        f"events_reaching_plus20={p20_count}",
        f"events_with_complete_V20_classifier={class_count}",
        f"RUNNER_STRENGTHENING_events={rs_count}",
        f"validated_policy_events={len(validated)}",
        "",
        "SCORECARD",
        "-"*118,
        f"BASELINE total={fmt(sb['total_points'])} mean={fmt(sb['mean_points'])} "
        f"median={fmt(sb['median_points'])} worst={fmt(sb['worst_points'])} "
        f"best={fmt(sb['best_points'])} maxDD={fmt(sb['max_drawdown_points'])}",
        f"PRIMARY_OFF/CAP20 total={fmt(sc['total_points'])} "
        f"Δbase={fmt(sc['delta_vs_baseline_total'])} "
        f"mean={fmt(sc['mean_points'])} median={fmt(sc['median_points'])} "
        f"worst={fmt(sc['worst_points'])} maxDD={fmt(sc['max_drawdown_points'])}",
        "",
        "EXIT MIX",
        "-"*118,
        f"rescue={rescue}",
        f"fallback={fallback}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-"*118,
    ]

    for m in MILESTONES:
        p=preservation[m]
        if p["rate"] is not None:
            lines.append(
                f"+{m}: {p['preserved']}/{p['reached']} "
                f"({p['rate']*100:.1f}%)"
            )

    lines += [
        f"later new MFE after rescue exit: {later}/{len(actual)}",
        "",
        "INTERPRETATION GUARDS",
        "-"*118,
        "- V45 performs no tuning grid.",
        "- PRIMARY_OFF + CAP20 is frozen before this run.",
        "- This is another date-separated historical robustness block.",
        "- It is not globally pristine because earlier B-family research used this period.",
        "- Untouched forward validation from 2026-09-29 remains reserved.",
        "- Underlying NIFTY directional points only.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(EVENTS_CSV,validated)
    write_csv(SCORECARD_CSV,[sb,sc])
    REPORT_JSON.write_text(json.dumps({
        "version":"V45",
        "range":{"start":START_DATE,"end":END_DATE},
        "dual_raw_sessions":len(sessions),
        "validated_events":len(validated),
        "scorecard":{"baseline":sb,"candidate":sc},
        "exit_mix":{"rescue":rescue,"fallback":fallback},
        "preservation":preservation,
        "later_new_mfe":later,
        "methodology":{"tuning_grid":False,"globally_untouched":False},
    },indent=2))
    SUMMARY_TXT.write_text("\n".join(lines)+"\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENTS CSV  :",EVENTS_CSV)
    print("SCORECARD   :",SCORECARD_CSV)
    print("REPORT JSON :",REPORT_JSON)
    print("SUMMARY     :",SUMMARY_TXT)

if __name__=="__main__":
    main()
