#!/usr/bin/env python3
"""
B FAMILY — V38 PROFIT-AWARE SELECTIVE RESCUE OPTIMIZATION

Why V38
-------
V37 improved total points only slightly versus V35:
    V35 = +866.75
    V37 = +879.95  (+13.20)

But V37 damaged runner preservation:
    +75: 92.3% -> 69.2%
    +100: 90.0% -> 60.0%
    later-new-MFE: 9/17 exits

So V38 keeps the V37 rescue structure but adds one causal selectivity gate:

    only take the post-recovery rebreak rescue if the current captured
    directional points are <= a configured cap.

This is fully live-computable because current directional points are known at
the exit candle.

Fixed structure from V37 winner
-------------------------------
Primary:
    V35_W1_AGE10

Secondary rescue:
    first recovery-target retake
    then 1 close back below target
    minimum 10 minutes after recovery
    no VWAP confirmation

V38 tuning grid
---------------
rescue capture cap (NIFTY directional points):
    0, 10, 20, 30, 40, 50, 75

Interpretation:
- cap=20 means: rescue only if the rebreak happens while currently holding
  <= +20 directional points.
- if current points are above the cap, ignore the rescue and keep running.

Scorecard
---------
Same 18-event development population:
- total / mean / median / worst / best
- max drawdown
- delta vs V34.2 baseline
- delta vs V29
- delta vs V35
- delta vs V37
- +30/+40/+50/+75/+100 chase preservation
- later-new-MFE after actual exits
- primary/rescue/fallback counts

Development/tuning only.
Underlying NIFTY directional points only.
"""

from __future__ import annotations

import csv, json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

BASE_EVENTS = RESEARCH / "b-family-comparable-points-baseline-v34_2" / "comparable-event-points-v34_2.csv"
PATHS_CSV = RESEARCH / "b-family-degraded-state-population-v32" / "degraded-state-population-v32.csv"
ATTEMPTS_CSV = RESEARCH / "b-family-degraded-state-population-v32" / "recovery-attempts-v32.csv"
V35_WINNER = RESEARCH / "b-family-exit-optimization-v35" / "winner-v35.json"
V37_WINNER = RESEARCH / "b-family-post-recovery-rebreak-v37" / "winner-v37.json"

OUTDIR = RESEARCH / "b-family-profit-aware-selective-rescue-v38"
LEADERBOARD = OUTDIR / "candidate-leaderboard-v38.csv"
EVENTS = OUTDIR / "candidate-event-results-v38.csv"
WINNER = OUTDIR / "winner-v38.json"
REPORT = OUTDIR / "report-v38.json"
SUMMARY = OUTDIR / "summary-v38.txt"

CAPS = (0, 10, 20, 30, 40, 50, 75)
MILESTONES = (30, 40, 50, 75, 100)


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))

def f(v):
    return None if v in ("", None) else float(v)

def i(v):
    return None if v in ("", None) else int(float(v))

def parse_dt(s):
    return datetime.fromisoformat(s)

def mins(a,b):
    return (parse_dt(b)-parse_dt(a)).total_seconds()/60.0

def directional(direction, entry, price):
    return price-entry if direction=="BULLISH" else entry-price

def favorable(direction, bar):
    return bar["high"] if direction=="BULLISH" else bar["low"]

def stats(vals):
    xs=[float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(n=len(xs),total=sum(xs),mean=mean(xs),median=median(xs),
                min=min(xs),max=max(xs))

def maxdd(vals):
    eq=0.0; peak=0.0; dd=0.0
    for x in vals:
        eq += float(x); peak=max(peak,eq); dd=min(dd,eq-peak)
    return dd

def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"

def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:
        path.write_text(""); return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)

def key(r):
    return (r["session_date"],r["direction"],r["entry_timestamp"])

def discover_underlying():
    u=defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if rows and {"session_date","timestamp","open","high","low","close"}.issubset(rows[0]):
            for r in rows:
                u[r["session_date"]][r["timestamp"]] = {
                    "open":float(r["open"]),"high":float(r["high"]),
                    "low":float(r["low"]),"close":float(r["close"])
                }
    return dict(u)

def load_attempts():
    by=defaultdict(list)
    for r in load_csv(ATTEMPTS_CSV):
        by[key(r)].append(r)
    for k in by:
        by[k].sort(key=lambda x:i(x["attempt_number"]) or 0)
    return by

def v35_primary(path,attempts):
    best=None; prev=None; streak=0
    for a in attempts:
        gap=f(a.get("gap_to_target_at_peak"))
        if gap is None: continue
        if best is None or gap < best:
            best=gap; streak=0
        else:
            if prev is not None and gap > prev:
                streak += 1
            else:
                streak=0
        age=mins(path["degraded_timestamp"],a["peak_timestamp"])
        if streak>=1 and age>=10:
            return a["peak_timestamp"]
        prev=gap
    return None

def first_recovery(path,base,u):
    direction=base["direction"]; entry=f(base["entry_close"])
    target=f(path.get("episode_start_directional_close_level"))
    degraded=path["degraded_timestamp"]; terminal=base["terminal_timestamp"]
    if target is None: return None
    for ts in sorted(u):
        if ts<=degraded: continue
        if ts>=terminal: break
        move=directional(direction,entry,u[ts]["close"])
        if move>target:
            return dict(timestamp=ts,target_move=target,recovery_move=move)
    return None

def v37_rebreak(base,recovery,u):
    # Fixed V37 winner structure: RB1, G10, NONE.
    direction=base["direction"]; entry=f(base["entry_close"])
    terminal=base["terminal_timestamp"]
    rts=recovery["timestamp"]; target=recovery["target_move"]
    for ts in sorted(u):
        if ts<=rts: continue
        if ts>=terminal: break
        if mins(rts,ts)<10: continue
        move=directional(direction,entry,u[ts]["close"])
        if move<target:
            return dict(exit_timestamp=ts,exit_move=move,
                        minutes_after_recovery=mins(rts,ts))
    return None

def later_new_mfe(direction,entry,exit_ts,terminal,u):
    pre=None
    for ts in sorted(u):
        if ts>exit_ts: break
        fav=directional(direction,entry,favorable(direction,u[ts]))
        pre=fav if pre is None else max(pre,fav)
    if pre is None: return None
    for ts in sorted(u):
        if ts<=exit_ts: continue
        if ts>=terminal: break
        fav=directional(direction,entry,favorable(direction,u[ts]))
        if fav>pre+1e-9: return True
    return False

def milestone_ts(direction,entry,entry_ts,terminal,u,m):
    for ts in sorted(u):
        if ts<=entry_ts: continue
        if ts>=terminal: break
        if directional(direction,entry,favorable(direction,u[ts]))>=m:
            return ts
    return None

def evaluate(cap,bases,paths,attempts_by,uall):
    name=f"V38_CAP{cap}"
    rows=[]
    for base in bases:
        k=key(base); path=paths[k]; aa=attempts_by.get(k,[])
        d=base["session_date"]; u=uall[d]
        entry=f(base["entry_close"]); terminal=base["terminal_timestamp"]
        baseline=f(base["baseline_points"]); v29=f(base["v29_points"])

        primary=v35_primary(path,aa)
        exit_ts=None; exit_type="FALLBACK"; rescue_move=None

        if primary and primary in u and primary<terminal:
            exit_ts=primary; exit_type="V35_PRIMARY"
        else:
            rec=first_recovery(path,base,u)
            if rec:
                rb=v37_rebreak(base,rec,u)
                if rb:
                    rescue_move=rb["exit_move"]
                    if rescue_move<=cap:
                        exit_ts=rb["exit_timestamp"]
                        exit_type="SELECTIVE_REBREAK_RESCUE"

        if exit_ts:
            points=directional(base["direction"],entry,u[exit_ts]["close"])
            later=later_new_mfe(base["direction"],entry,exit_ts,terminal,u)
        else:
            points=baseline; later=None

        r=dict(candidate=name,session_date=d,direction=base["direction"],
               entry_timestamp=base["entry_timestamp"],exit_type=exit_type,
               exit_timestamp=exit_ts,points=points,baseline_points=baseline,
               v29_points=v29,delta_vs_baseline=points-baseline,
               rescue_move_seen=rescue_move,later_new_mfe=later)

        for m in MILESTONES:
            mt=milestone_ts(base["direction"],entry,base["entry_timestamp"],terminal,u,m)
            r[f"plus{m}_timestamp"]=mt
            r[f"reached_plus{m}"]=mt is not None
            r[f"exit_before_plus{m}"]=bool(exit_ts and mt and exit_ts<mt)
        rows.append(r)

    vals=[r["points"] for r in rows]
    bvals=[r["baseline_points"] for r in rows]
    v29=[r["v29_points"] for r in rows]
    s=stats(vals); db=stats([v-b for v,b in zip(vals,bvals)])
    dv29=stats([v-x for v,x in zip(vals,v29)])
    exits=[r for r in rows if r["exit_timestamp"]]
    primary=sum(r["exit_type"]=="V35_PRIMARY" for r in rows)
    rescue=sum(r["exit_type"]=="SELECTIVE_REBREAK_RESCUE" for r in rows)
    later=sum(r["later_new_mfe"] is True for r in exits)

    sm=dict(candidate=name,rescue_cap_points=cap,events=len(rows),
            primary_exits=primary,rescue_exits=rescue,
            fallbacks=len(rows)-primary-rescue,actual_exit_count=len(exits),
            later_new_mfe_count=later,total_points=s["total"],
            mean_points=s["mean"],median_points=s["median"],
            worst_points=s["min"],best_points=s["max"],
            max_drawdown_points=maxdd(vals),
            delta_vs_baseline_total=db["total"],
            delta_vs_v29_total=dv29["total"])

    for m in MILESTONES:
        reached=[r for r in rows if r[f"reached_plus{m}"]]
        cut=[r for r in reached if r[f"exit_before_plus{m}"]]
        preserved=len(reached)-len(cut)
        sm[f"plus{m}_reached"]=len(reached)
        sm[f"plus{m}_preserved"]=preserved
        sm[f"plus{m}_rate"]=preserved/len(reached) if reached else None
    return sm,rows

def main():
    print("B FAMILY — V38 PROFIT-AWARE SELECTIVE RESCUE OPTIMIZATION")
    print("="*118)

    bases=load_csv(BASE_EVENTS)
    paths={key(r):r for r in load_csv(PATHS_CSV)}
    attempts=load_attempts()
    uall=discover_underlying()

    if len(bases)!=18:
        raise SystemExit(f"STOP: expected 18 events, got {len(bases)}")

    v35=json.loads(V35_WINNER.read_text())
    v37=json.loads(V37_WINNER.read_text())
    v35_total=f(v35["total_points"]); v37_total=f(v37["total_points"])
    base_total=sum(f(r["baseline_points"]) for r in bases)
    v29_total=sum(f(r["v29_points"]) for r in bases)

    leaders=[]; erows=[]
    for cap in CAPS:
        s,rows=evaluate(cap,bases,paths,attempts,uall)
        s["delta_vs_v35_total"]=s["total_points"]-v35_total
        s["delta_vs_v37_total"]=s["total_points"]-v37_total
        leaders.append(s); erows.extend(rows)
        print(f"{s['candidate']:<12} total={fmt(s['total_points'])} "
              f"ΔV35={fmt(s['delta_vs_v35_total'])} "
              f"ΔV37={fmt(s['delta_vs_v37_total'])} "
              f"DD={fmt(s['max_drawdown_points'])} "
              f"P={s['primary_exits']} R={s['rescue_exits']} "
              f"+50={s['plus50_preserved']}/{s['plus50_reached']} "
              f"+75={s['plus75_preserved']}/{s['plus75_reached']} "
              f"+100={s['plus100_preserved']}/{s['plus100_reached']}")

    # Rank by total points, then +100 preservation, +75 preservation, maxDD.
    leaders.sort(key=lambda r:(
        r["total_points"],
        r["plus100_rate"] if r["plus100_rate"] is not None else -1,
        r["plus75_rate"] if r["plus75_rate"] is not None else -1,
        r["max_drawdown_points"],
    ),reverse=True)
    for n,r in enumerate(leaders,1): r["rank"]=n
    win=leaders[0]

    lines=[
        "B FAMILY — V38 PROFIT-AWARE SELECTIVE RESCUE OPTIMIZATION",
        "="*118,
        f"development_events={len(bases)}",
        f"candidate_count={len(leaders)}",
        "",
        "REFERENCE",
        "-"*118,
        f"V34.2 baseline={fmt(base_total)}",
        f"V29 rejected={fmt(v29_total)}",
        f"V35 winner={fmt(v35_total)}",
        f"V37 winner={fmt(v37_total)}",
        "",
        "TOP CANDIDATES",
        "-"*118,
    ]
    for r in leaders:
        lines.append(
            f"#{r['rank']:02d} {r['candidate']} total={fmt(r['total_points'])} "
            f"Δbase={fmt(r['delta_vs_baseline_total'])} "
            f"ΔV35={fmt(r['delta_vs_v35_total'])} "
            f"ΔV37={fmt(r['delta_vs_v37_total'])} "
            f"mean={fmt(r['mean_points'])} median={fmt(r['median_points'])} "
            f"worst={fmt(r['worst_points'])} maxDD={fmt(r['max_drawdown_points'])} "
            f"P={r['primary_exits']} R={r['rescue_exits']} "
            f"laterNewMFE={r['later_new_mfe_count']}/{r['actual_exit_count']}"
        )

    lines += [
        "",
        "WINNER SCORECARD",
        "-"*118,
        f"candidate={win['candidate']}",
        f"rescue_cap_points={win['rescue_cap_points']}",
        f"total={fmt(win['total_points'])}",
        f"Δ vs baseline={fmt(win['delta_vs_baseline_total'])}",
        f"Δ vs V29={fmt(win['delta_vs_v29_total'])}",
        f"Δ vs V35={fmt(win['delta_vs_v35_total'])}",
        f"Δ vs V37={fmt(win['delta_vs_v37_total'])}",
        f"mean={fmt(win['mean_points'])}",
        f"median={fmt(win['median_points'])}",
        f"worst={fmt(win['worst_points'])}",
        f"best={fmt(win['best_points'])}",
        f"maxDD={fmt(win['max_drawdown_points'])}",
        f"primary exits={win['primary_exits']} rescue exits={win['rescue_exits']} "
        f"fallbacks={win['fallbacks']}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-"*118,
    ]
    for m in MILESTONES:
        rate=win[f"plus{m}_rate"]
        lines.append(
            f"+{m}: {win[f'plus{m}_preserved']}/{win[f'plus{m}_reached']} "
            f"({rate*100:.1f}%)" if rate is not None else f"+{m}: no events"
        )
    lines += [
        f"later new MFE after actual exit: {win['later_new_mfe_count']}/{win['actual_exit_count']}",
        "",
        "INTERPRETATION",
        "-"*118,
        "- V38 directly tests whether rescue exits should be restricted to low-captured-point situations.",
        "- This is development/tuning on the same 18 events.",
        "- If V38 improves points while restoring +75/+100 preservation, freeze the winner and validate OOS.",
        "- Underlying NIFTY points only; no option premium or rupee P&L.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(LEADERBOARD,leaders); write_csv(EVENTS,erows)
    WINNER.write_text(json.dumps(win,indent=2))
    REPORT.write_text(json.dumps({"version":"V38","reference":{
        "baseline":base_total,"v29":v29_total,"v35":v35_total,"v37":v37_total},
        "winner":win,"leaderboard":leaders},indent=2))
    SUMMARY.write_text("\n".join(lines)+"\n")

    print()
    print("\n".join(lines))
    print()
    print("LEADERBOARD :",LEADERBOARD)
    print("EVENTS      :",EVENTS)
    print("WINNER JSON :",WINNER)
    print("REPORT JSON :",REPORT)
    print("SUMMARY     :",SUMMARY)

if __name__=="__main__":
    main()
