#!/usr/bin/env python3
"""
B FAMILY — V36 SECOND-STAGE RESCUE EXIT OPTIMIZATION

Goal
----
Improve on V35_W1_AGE10 by catching more of the structural/session-cutoff
losers that V35 leaves as fallbacks, while preserving V35's strong runner chase.

Primary exit is FIXED from V35:
  running-best recovery logic
  1 weakening attempt
  minimum degraded age 10 minutes

Secondary rescue exit is evaluated only when the primary V35 exit has NOT fired:
  - start at V32 degraded_timestamp
  - recovery target is the V32 episode-start directional close level
  - if directional close retakes the target before timeout => RECOVERED, no rescue
  - otherwise at exact timeout T, candidate may exit
  - optional futures-VWAP confirmation: directional futures-VWAP at timeout must
    still be below its degraded-start level

Transparent tuning grid:
  timeout minutes: 10, 15, 20, 30, 45
  confirmation:    NONE, VWAP_WEAK

Every candidate uses the same 18-event development population and reports:
- total / mean / median / worst / best
- max drawdown
- delta vs V34.2 baseline
- delta vs V29
- delta vs V35 winner
- +30/+40/+50/+75/+100 chase/preservation
- later-new-MFE after actual exits
- primary vs rescue exit counts

This is a DEVELOPMENT/TUNING study, not validation.
All points are NIFTY underlying directional points.
"""

from __future__ import annotations

import csv, json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

BASE_EVENTS = RESEARCH / "b-family-comparable-points-baseline-v34_2" / "comparable-event-points-v34_2.csv"
PATHS_CSV = RESEARCH / "b-family-degraded-state-population-v32" / "degraded-state-population-v32.csv"
ATTEMPTS_CSV = RESEARCH / "b-family-degraded-state-population-v32" / "recovery-attempts-v32.csv"
V35_WINNER = RESEARCH / "b-family-exit-optimization-v35" / "winner-v35.json"

OUTDIR = RESEARCH / "b-family-second-stage-rescue-v36"
LEADERBOARD = OUTDIR / "candidate-leaderboard-v36.csv"
EVENTS = OUTDIR / "candidate-event-results-v36.csv"
WINNER = OUTDIR / "winner-v36.json"
REPORT = OUTDIR / "report-v36.json"
SUMMARY = OUTDIR / "summary-v36.txt"

TIMEOUTS = (10, 15, 20, 30, 45)
CONFIRMS = ("NONE", "VWAP_WEAK")
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

def plus_minutes(ts, n):
    return (parse_dt(ts) + timedelta(minutes=n)).isoformat()

def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price

def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]

def directional_vwap(direction, row):
    if row is None:
        return None
    x = row["close"] - row["vwap"]
    return x if direction == "BULLISH" else -x

def stats(vals):
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(n=len(xs), total=sum(xs), mean=mean(xs), median=median(xs),
                min=min(xs), max=max(xs))

def maxdd(vals):
    eq=0.0; peak=0.0; dd=0.0
    for x in vals:
        eq += float(x); peak=max(peak,eq); dd=min(dd,eq-peak)
    return dd

def fmt(x):
    return "-" if x is None else f"{x:+.2f}"

def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(""); return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)

def key(r):
    return (r["session_date"], r["direction"], r["entry_timestamp"])

def discover_raw():
    u=defaultdict(dict); fut=defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        n=p.name.lower()
        if "underlying" in n:
            try: rows=load_csv(p)
            except: continue
            if rows and {"session_date","timestamp","open","high","low","close"}.issubset(rows[0]):
                for r in rows:
                    u[r["session_date"]][r["timestamp"]] = {
                        "open":float(r["open"]),"high":float(r["high"]),
                        "low":float(r["low"]),"close":float(r["close"])
                    }
        if "futures" in n and "vwap" in n:
            try: rows=load_csv(p)
            except: continue
            if rows and {"session_date","timestamp","close","session_vwap"}.issubset(rows[0]):
                for r in rows:
                    if r.get("session_vwap") in ("",None): continue
                    fut[r["session_date"]][r["timestamp"]] = {
                        "close":float(r["close"]),"vwap":float(r["session_vwap"])
                    }
    return dict(u), dict(fut)

def load_attempts():
    by=defaultdict(list)
    for r in load_csv(ATTEMPTS_CSV):
        by[key(r)].append(r)
    for k in by:
        by[k].sort(key=lambda r:i(r["attempt_number"]) or 0)
    return by

def v35_primary(path, attempts):
    # Frozen V35 winner: W1 AGE10.
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
                streak = 0
        age=(parse_dt(a["peak_timestamp"])-parse_dt(path["degraded_timestamp"])).total_seconds()/60
        if streak >= 1 and age >= 10:
            return a["peak_timestamp"]
        prev=gap
    return None

def recovered_before_timeout(path, base, u, timeout_ts):
    direction=base["direction"]; entry=f(base["entry_close"])
    degraded=path["degraded_timestamp"]
    target=f(path.get("episode_start_directional_close_level"))
    if target is None:
        return False
    for ts in sorted(u):
        if ts <= degraded: continue
        if ts > timeout_ts: break
        move=directional(direction, entry, u[ts]["close"])
        if move > target:
            return True
    return False

def later_new_mfe(direction, entry, exit_ts, terminal_ts, u):
    pre=None
    for ts in sorted(u):
        if ts > exit_ts: break
        fav=directional(direction,entry,favorable(direction,u[ts]))
        pre=fav if pre is None else max(pre,fav)
    if pre is None: return None
    for ts in sorted(u):
        if ts <= exit_ts: continue
        if ts >= terminal_ts: break
        fav=directional(direction,entry,favorable(direction,u[ts]))
        if fav > pre + 1e-9: return True
    return False

def milestone_ts(direction, entry, entry_ts, terminal_ts, u, m):
    for ts in sorted(u):
        if ts <= entry_ts: continue
        if ts >= terminal_ts: break
        if directional(direction,entry,favorable(direction,u[ts])) >= m:
            return ts
    return None

def evaluate(timeout, confirm, bases, paths, attempts_by, uall, fall):
    name=f"V36_T{timeout}_{confirm}"
    rows=[]
    for base in bases:
        k=key(base); path=paths[k]; aa=attempts_by.get(k,[])
        d=base["session_date"]; u=uall[d]; fut=fall[d]
        entry=f(base["entry_close"]); terminal=base["terminal_timestamp"]
        baseline=f(base["baseline_points"]); v29=f(base["v29_points"])

        primary_ts=v35_primary(path,aa)
        exit_ts=None; exit_type="FALLBACK"

        if primary_ts and primary_ts in u and primary_ts < terminal:
            exit_ts=primary_ts; exit_type="V35_PRIMARY"
        else:
            degraded=path["degraded_timestamp"]
            tts=plus_minutes(degraded, timeout)
            if tts in u and tts < terminal and not recovered_before_timeout(path,base,u,tts):
                ok=True
                if confirm=="VWAP_WEAK":
                    ds=directional_vwap(base["direction"], fut.get(degraded))
                    te=directional_vwap(base["direction"], fut.get(tts))
                    ok=(ds is not None and te is not None and te < ds)
                if ok:
                    exit_ts=tts; exit_type="RESCUE"

        if exit_ts:
            points=directional(base["direction"],entry,u[exit_ts]["close"])
            later=later_new_mfe(base["direction"],entry,exit_ts,terminal,u)
        else:
            points=baseline; later=None

        r=dict(candidate=name,session_date=d,direction=base["direction"],
               entry_timestamp=base["entry_timestamp"],exit_type=exit_type,
               exit_timestamp=exit_ts,points=points,baseline_points=baseline,
               v29_points=v29,delta_vs_baseline=points-baseline,
               later_new_mfe=later)
        for m in MILESTONES:
            mt=milestone_ts(base["direction"],entry,base["entry_timestamp"],terminal,u,m)
            r[f"plus{m}_timestamp"]=mt
            r[f"reached_plus{m}"]=mt is not None
            r[f"exit_before_plus{m}"]=bool(exit_ts and mt and exit_ts < mt)
        rows.append(r)

    vals=[r["points"] for r in rows]
    bvals=[r["baseline_points"] for r in rows]
    v29=[r["v29_points"] for r in rows]
    s=stats(vals); db=stats([a-b for a,b in zip(vals,bvals)])
    dv=stats([a-b for a,b in zip(vals,v29)])
    exits=[r for r in rows if r["exit_timestamp"]]
    prim=sum(r["exit_type"]=="V35_PRIMARY" for r in rows)
    rescue=sum(r["exit_type"]=="RESCUE" for r in rows)
    later=sum(r["later_new_mfe"] is True for r in exits)

    summary=dict(candidate=name,timeout_minutes=timeout,confirmation=confirm,
                 events=len(rows),primary_exits=prim,rescue_exits=rescue,
                 fallbacks=len(rows)-prim-rescue,total_points=s["total"],
                 mean_points=s["mean"],median_points=s["median"],
                 worst_points=s["min"],best_points=s["max"],
                 max_drawdown_points=maxdd(vals),
                 delta_vs_baseline_total=db["total"],
                 delta_vs_v29_total=dv["total"],
                 later_new_mfe_count=later,
                 actual_exit_count=len(exits))
    for m in MILESTONES:
        reached=[r for r in rows if r[f"reached_plus{m}"]]
        cut=[r for r in reached if r[f"exit_before_plus{m}"]]
        preserved=len(reached)-len(cut)
        summary[f"plus{m}_reached"]=len(reached)
        summary[f"plus{m}_preserved"]=preserved
        summary[f"plus{m}_rate"]=preserved/len(reached) if reached else None
    return summary, rows

def main():
    print("B FAMILY — V36 SECOND-STAGE RESCUE EXIT OPTIMIZATION")
    print("="*118)

    bases=load_csv(BASE_EVENTS)
    paths={key(r):r for r in load_csv(PATHS_CSV)}
    attempts=load_attempts()
    uall,fall=discover_raw()

    if len(bases)!=18:
        raise SystemExit(f"STOP: expected 18 bases, got {len(bases)}")

    v35=json.loads(V35_WINNER.read_text())
    v35_total=f(v35["total_points"])
    base_total=sum(f(r["baseline_points"]) for r in bases)
    v29_total=sum(f(r["v29_points"]) for r in bases)

    leaders=[]; erows=[]
    for t in TIMEOUTS:
        for c in CONFIRMS:
            s,rows=evaluate(t,c,bases,paths,attempts,uall,fall)
            s["delta_vs_v35_total"]=s["total_points"]-v35_total
            leaders.append(s); erows.extend(rows)
            print(f"{s['candidate']:<18} total={fmt(s['total_points'])} "
                  f"Δbase={fmt(s['delta_vs_baseline_total'])} "
                  f"ΔV35={fmt(s['delta_vs_v35_total'])} "
                  f"DD={fmt(s['max_drawdown_points'])} "
                  f"primary={s['primary_exits']} rescue={s['rescue_exits']} "
                  f"+50={s['plus50_preserved']}/{s['plus50_reached']} "
                  f"+75={s['plus75_preserved']}/{s['plus75_reached']} "
                  f"+100={s['plus100_preserved']}/{s['plus100_reached']}")

    leaders.sort(key=lambda r:(r["total_points"],r["max_drawdown_points"]),reverse=True)
    for n,r in enumerate(leaders,1): r["rank"]=n
    win=leaders[0]

    lines=[
        "B FAMILY — V36 SECOND-STAGE RESCUE EXIT OPTIMIZATION",
        "="*118,
        f"development_events={len(bases)}",
        f"candidate_count={len(leaders)}",
        "",
        "REFERENCE",
        "-"*118,
        f"V34.2 baseline={fmt(base_total)}",
        f"V29 rejected={fmt(v29_total)}",
        f"V35 winner={fmt(v35_total)}",
        "",
        "TOP CANDIDATES",
        "-"*118,
    ]
    for r in leaders[:10]:
        lines.append(
            f"#{r['rank']:02d} {r['candidate']} total={fmt(r['total_points'])} "
            f"Δbase={fmt(r['delta_vs_baseline_total'])} "
            f"ΔV35={fmt(r['delta_vs_v35_total'])} "
            f"mean={fmt(r['mean_points'])} median={fmt(r['median_points'])} "
            f"worst={fmt(r['worst_points'])} maxDD={fmt(r['max_drawdown_points'])} "
            f"primary={r['primary_exits']} rescue={r['rescue_exits']} "
            f"laterNewMFE={r['later_new_mfe_count']}/{r['actual_exit_count']}"
        )

    lines += [
        "",
        "WINNER SCORECARD",
        "-"*118,
        f"candidate={win['candidate']}",
        f"total={fmt(win['total_points'])}",
        f"Δ vs V34.2 baseline={fmt(win['delta_vs_baseline_total'])}",
        f"Δ vs V29={fmt(win['delta_vs_v29_total'])}",
        f"Δ vs V35={fmt(win['delta_vs_v35_total'])}",
        f"mean={fmt(win['mean_points'])} median={fmt(win['median_points'])}",
        f"worst={fmt(win['worst_points'])} best={fmt(win['best_points'])}",
        f"maxDD={fmt(win['max_drawdown_points'])}",
        f"primary exits={win['primary_exits']} rescue exits={win['rescue_exits']} "
        f"fallbacks={win['fallbacks']}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-"*118,
    ]
    for m in MILESTONES:
        rate=win[f"plus{m}_rate"]
        lines.append(f"+{m}: {win[f'plus{m}_preserved']}/{win[f'plus{m}_reached']} "
                     f"({rate*100:.1f}%)" if rate is not None else f"+{m}: no events")
    lines += [
        f"later new MFE after actual exit: {win['later_new_mfe_count']}/{win['actual_exit_count']}",
        "",
        "IMPORTANT",
        "-"*118,
        "- V36 is development/tuning.",
        "- Goal: improve points over V35 without giving back runner preservation.",
        "- Winner must be frozen and tested separately before production consideration.",
        "- Underlying NIFTY points only; no option premium or rupee P&L.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(LEADERBOARD,leaders); write_csv(EVENTS,erows)
    WINNER.write_text(json.dumps(win,indent=2))
    REPORT.write_text(json.dumps({"version":"V36","reference":{"baseline":base_total,
                           "v29":v29_total,"v35":v35_total},"winner":win,
                           "leaderboard":leaders},indent=2))
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
