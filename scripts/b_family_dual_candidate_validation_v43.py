#!/usr/bin/env python3
"""
B FAMILY — V43 DUAL-CANDIDATE HISTORICAL COMPARISON

Purpose
-------
Compare the two frozen V42 candidates on a separate 100-session historical block:

    2025-07-17 through 2025-12-11

Candidate A:
    V42_W3_AGE30_CAP20

Candidate B:
    V42_PRIMARY_OFF_CAP20

No parameter tuning is performed in V43.

Important methodology note
--------------------------
This block is date-separated from the 43-event V42 tuning population, but it
has been used in earlier B-family historical research. Therefore V43 is a
historical validation / robustness comparison, not pristine untouched OOS.

The untouched forward block beginning 2026-09-29 remains reserved.

Frozen shared logic
-------------------
- Same B entry events.
- Same V20 RUNNER_STRENGTHENING classifier:
    +20 proof
    fixed +10m checkpoint
    net directional price progress > 0
    directional futures-VWAP change > 0

- Same DEGRADED state:
    first joint deterioration after classification:
      running close-MFE drawdown > 0
      AND prior-minute directional futures-VWAP change < 0

- Same CAP20 rescue:
    first recovery above degraded-start target
    then first rebreak below target after >=10m
    rescue only if current directional points <= +20

Candidate A primary:
    3 consecutive weakening failed-recovery attempts
    minimum degraded age = 30m

Candidate B primary:
    OFF

Fallback:
    structural invalidation close when available,
    otherwise final trusted session close.

Outputs
-------
For baseline, Candidate A and Candidate B:
- total / mean / median / worst / best / maxDD
- delta vs baseline
- primary / rescue / fallback counts
- +30/+40/+50/+75/+100 chase preservation
- later-new-MFE after actual exits
- direct A vs B point difference

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

START_DATE = "2025-07-17"
END_DATE = "2025-12-11"

OUTDIR = RESEARCH / "b-family-dual-candidate-validation-v43"
EVENTS_CSV = OUTDIR / "dual-candidate-events-v43.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v43.csv"
REPORT_JSON = OUTDIR / "report-v43.json"
SUMMARY_TXT = OUTDIR / "summary-v43.txt"

MILESTONES = (30, 40, 50, 75, 100)

ALIASES = {
    "session_date": ("session_date", "date", "trade_date"),
    "direction": ("direction", "side", "signal_direction"),
    "entry_timestamp": ("entry_timestamp", "entry_time", "entry_ts"),
    "entry_close": ("entry_close", "entry_price", "entry_underlying_close"),
    "structural_invalidation_timestamp": (
        "structural_invalidation_timestamp",
        "invalidation_timestamp",
        "structural_exit_timestamp",
        "exit_timestamp",
    ),
    "plus20_timestamp": (
        "plus20_timestamp",
        "plus_20_timestamp",
        "p20_timestamp",
    ),
}


def load_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in ("", None):
        return None
    return float(v)


def parse_dt(s):
    return datetime.fromisoformat(s)


def plus_minutes(ts, n):
    return (parse_dt(ts) + timedelta(minutes=n)).isoformat()


def date_in_range(d):
    return START_DATE <= d <= END_DATE


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def directional_vwap(direction, row):
    if row is None:
        return None
    raw = row["close"] - row["vwap"]
    return raw if direction == "BULLISH" else -raw


def stats(vals):
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(n=len(xs),total=sum(xs),mean=mean(xs),median=median(xs),
                min=min(xs),max=max(xs))


def maxdd(vals):
    eq=0.0; peak=0.0; dd=0.0
    for x in vals:
        eq += float(x)
        peak=max(peak,eq)
        dd=min(dd,eq-peak)
    return dd


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def first_present(row, names):
    for n in names:
        if n in row and row.get(n) not in ("", None):
            return row.get(n)
    return None


def normalize_event_row(raw):
    r=dict(raw)
    for canon, aliases in ALIASES.items():
        v=first_present(raw, aliases)
        if v not in ("", None):
            r[canon]=v

    d=r.get("session_date")
    direction=str(r.get("direction","")).upper()
    entry_ts=r.get("entry_timestamp")

    if not d or not entry_ts or direction not in ("BULLISH","BEARISH"):
        return None

    r["direction"]=direction
    return r


def discover_underlying():
    by=defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if not rows or not {"session_date","timestamp","open","high","low","close"}.issubset(rows[0].keys()):
            continue
        for r in rows:
            d=r["session_date"]
            if not date_in_range(d):
                continue
            by[d][r["timestamp"]]={
                "open":float(r["open"]),
                "high":float(r["high"]),
                "low":float(r["low"]),
                "close":float(r["close"]),
            }
    return dict(by)


def discover_futures():
    by=defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        n=p.name.lower()
        if "futures" not in n or "vwap" not in n:
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if not rows or not {"session_date","timestamp","close","session_vwap"}.issubset(rows[0].keys()):
            continue
        for r in rows:
            d=r["session_date"]
            if not date_in_range(d) or r.get("session_vwap") in ("",None):
                continue
            by[d][r["timestamp"]]={
                "close":float(r["close"]),
                "vwap":float(r["session_vwap"]),
            }
    return dict(by)


def discover_events():
    found={}
    for p in RESEARCH.rglob("*.csv"):
        if "v43" in str(p).lower():
            continue
        try:
            rows=load_csv(p)
        except Exception:
            continue
        if not rows:
            continue

        headers=set(rows[0].keys())
        if not any(x in headers for x in ALIASES["session_date"]):
            continue
        if not any(x in headers for x in ALIASES["direction"]):
            continue
        if not any(x in headers for x in ALIASES["entry_timestamp"]):
            continue

        for raw in rows:
            r=normalize_event_row(raw)
            if not r or not date_in_range(r["session_date"]):
                continue

            event_like=any(
                r.get(x) not in ("",None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "plus20_timestamp",
                    "mfe","mae","candidate","event_type","setup_family",
                )
            )
            name_like=any(
                token in p.name.lower()
                for token in ("event","candidate","setup","family","canonical")
            )
            if not event_like and not name_like:
                continue

            k=(r["session_date"],r["direction"],r["entry_timestamp"])
            richness=sum(
                r.get(x) not in ("",None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "plus20_timestamp",
                    "mfe","mae","observation_end_timestamp","classification",
                )
            )

            if k not in found or richness>found[k][0]:
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
        terminal_ts=invalid
        terminal_type="STRUCTURAL_INVALIDATION"
    else:
        terminal_ts=trusted[-1]
        terminal_type="SESSION_CUTOFF"

    return {
        "entry_close":entry,
        "terminal_timestamp":terminal_ts,
        "terminal_type":terminal_type,
        "baseline_points":directional(
            event["direction"],entry,u[terminal_ts]["close"]
        ),
    }


def find_plus20(event,u,terminal_ts,entry):
    source=event.get("plus20_timestamp")
    if source and source in u and source<terminal_ts:
        return source

    for ts in sorted(u):
        if ts<=event["entry_timestamp"]:
            continue
        if ts>=terminal_ts:
            break
        if directional(
            event["direction"],entry,favorable(event["direction"],u[ts])
        )>=20:
            return ts
    return None


def classify_runner(event,p20,u,fut,entry,terminal):
    cts=plus_minutes(p20,10)
    if cts>=terminal or p20 not in u or cts not in u:
        return None
    if p20 not in fut or cts not in fut:
        return None

    direction=event["direction"]
    proof=directional(direction,entry,u[p20]["close"])
    current=directional(direction,entry,u[cts]["close"])
    net=current-proof

    pv=directional_vwap(direction,fut[p20])
    cv=directional_vwap(direction,fut[cts])
    dv=cv-pv

    return {
        "classification_timestamp":cts,
        "net_progress_10m":net,
        "directional_vwap_change_10m":dv,
        "runner_strengthening":net>0 and dv>0,
    }


def first_degraded(event,cts,u,fut,entry,terminal):
    direction=event["direction"]
    running=None
    prevdv=None
    prior_joint=False

    for ts in sorted(u):
        if ts<=event["entry_timestamp"]:
            continue
        if ts>cts or ts>=terminal:
            break
        move=directional(direction,entry,u[ts]["close"])
        running=move if running is None else max(running,move)
        dv=directional_vwap(direction,fut.get(ts))
        if dv is not None:
            prevdv=dv

    for ts in sorted(u):
        if ts<=cts:
            continue
        if ts>=terminal:
            break

        move=directional(direction,entry,u[ts]["close"])
        running=move if running is None else max(running,move)
        dd=running-move

        dv=directional_vwap(direction,fut.get(ts))
        dvc=None if dv is None or prevdv is None else dv-prevdv
        joint=dd>0 and dvc is not None and dvc<0

        if joint and not prior_joint:
            return {
                "degraded_timestamp":ts,
                "target_move":move,
            }

        prior_joint=joint
        if dv is not None:
            prevdv=dv

    return None


def failed_attempts(degraded,event,u,entry,terminal):
    direction=event["direction"]
    dts=degraded["degraded_timestamp"]
    target=degraded["target_move"]

    attempts=[]
    in_rise=False
    peak_ts=None
    peak_move=None
    prev=None

    for ts in sorted(u):
        if ts<=dts:
            continue
        if ts>=terminal:
            break

        move=directional(direction,entry,u[ts]["close"])

        if move>target:
            break

        if prev is None:
            prev=move
            continue

        if move>prev:
            if not in_rise:
                in_rise=True
                peak_ts=ts
                peak_move=move
            elif move>=peak_move:
                peak_ts=ts
                peak_move=move
        elif in_rise:
            attempts.append({
                "peak_timestamp":peak_ts,
                "peak_move":peak_move,
                "gap_to_target":target-peak_move,
            })
            in_rise=False
            peak_ts=None
            peak_move=None

        prev=move

    if in_rise and peak_ts and peak_move is not None and peak_move<=target:
        attempts.append({
            "peak_timestamp":peak_ts,
            "peak_move":peak_move,
            "gap_to_target":target-peak_move,
        })

    return attempts


def primary_w3_age30(degraded,attempts):
    best=None
    prev=None
    streak=0

    for a in attempts:
        gap=a["gap_to_target"]

        if best is None or gap<best:
            best=gap
            streak=0
        else:
            if prev is not None and gap>prev:
                streak+=1
            else:
                streak=0

        age=(parse_dt(a["peak_timestamp"])-parse_dt(
            degraded["degraded_timestamp"]
        )).total_seconds()/60

        if streak>=3 and age>=30:
            return a["peak_timestamp"]

        prev=gap

    return None


def first_recovery(degraded,event,u,entry,terminal):
    target=degraded["target_move"]
    dts=degraded["degraded_timestamp"]

    for ts in sorted(u):
        if ts<=dts:
            continue
        if ts>=terminal:
            break

        move=directional(event["direction"],entry,u[ts]["close"])
        if move>target:
            return ts

    return None


def cap20_rescue(degraded,recovery_ts,event,u,entry,terminal):
    target=degraded["target_move"]

    for ts in sorted(u):
        if ts<=recovery_ts:
            continue
        if ts>=terminal:
            break

        age=(parse_dt(ts)-parse_dt(recovery_ts)).total_seconds()/60
        if age<10:
            continue

        move=directional(event["direction"],entry,u[ts]["close"])
        if move<target:
            return ts if move<=20 else None

    return None


def later_new_mfe(event,u,entry,exit_ts,terminal):
    pre=None

    for ts in sorted(u):
        if ts>exit_ts:
            break
        fav=directional(
            event["direction"],entry,favorable(event["direction"],u[ts])
        )
        pre=fav if pre is None else max(pre,fav)

    if pre is None:
        return None

    for ts in sorted(u):
        if ts<=exit_ts:
            continue
        if ts>=terminal:
            break

        fav=directional(
            event["direction"],entry,favorable(event["direction"],u[ts])
        )
        if fav>pre+1e-9:
            return True

    return False


def milestone_ts(event,u,entry,terminal,m):
    for ts in sorted(u):
        if ts<=event["entry_timestamp"]:
            continue
        if ts>=terminal:
            break

        if directional(
            event["direction"],entry,favorable(event["direction"],u[ts])
        )>=m:
            return ts
    return None


def evaluate_policy(policy,event,degraded,u,entry,terminal):
    exit_ts=None
    exit_type="FALLBACK_BASELINE"

    if degraded:
        attempts=failed_attempts(degraded,event,u,entry,terminal)

        if policy=="A_W3_AGE30_CAP20":
            p=primary_w3_age30(degraded,attempts)
            if p and p in u and p<terminal:
                exit_ts=p
                exit_type="PRIMARY_W3_AGE30"

        if not exit_ts:
            rec=first_recovery(degraded,event,u,entry,terminal)
            if rec:
                rescue=cap20_rescue(
                    degraded,rec,event,u,entry,terminal
                )
                if rescue:
                    exit_ts=rescue
                    exit_type="CAP20_RESCUE"

    return exit_ts,exit_type


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
        "delta_vs_baseline_mean":ds["mean"],
    }


def main():
    print("B FAMILY — V43 DUAL-CANDIDATE HISTORICAL COMPARISON")
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
        events.items(),key=lambda kv:(kv[0][0],kv[0][2],kv[0][1])
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

        a_ts,a_type=evaluate_policy(
            "A_W3_AGE30_CAP20",event,degraded,u,entry,terminal
        )
        b_ts,b_type=evaluate_policy(
            "B_PRIMARY_OFF_CAP20",event,degraded,u,entry,terminal
        )

        if a_ts:
            a_points=directional(
                event["direction"],entry,u[a_ts]["close"]
            )
            a_later=later_new_mfe(
                event,u,entry,a_ts,terminal
            )
        else:
            a_points=base["baseline_points"]
            a_later=None

        if b_ts:
            b_points=directional(
                event["direction"],entry,u[b_ts]["close"]
            )
            b_later=later_new_mfe(
                event,u,entry,b_ts,terminal
            )
        else:
            b_points=base["baseline_points"]
            b_later=None

        row={
            "session_date":d,
            "direction":event["direction"],
            "entry_timestamp":event["entry_timestamp"],
            "event_source":source,
            "plus20_timestamp":p20,
            "classification_timestamp":cls["classification_timestamp"],
            "degraded_timestamp":degraded["degraded_timestamp"] if degraded else None,
            "baseline_points":base["baseline_points"],
            "baseline_terminal_type":base["terminal_type"],
            "candidate_a_exit_type":a_type,
            "candidate_a_exit_timestamp":a_ts,
            "candidate_a_points":a_points,
            "candidate_a_delta_vs_baseline":a_points-base["baseline_points"],
            "candidate_a_later_new_mfe":a_later,
            "candidate_b_exit_type":b_type,
            "candidate_b_exit_timestamp":b_ts,
            "candidate_b_points":b_points,
            "candidate_b_delta_vs_baseline":b_points-base["baseline_points"],
            "candidate_b_later_new_mfe":b_later,
            "a_minus_b_points":a_points-b_points,
        }

        for m in MILESTONES:
            mt=milestone_ts(event,u,entry,terminal,m)
            row[f"plus{m}_timestamp"]=mt
            row[f"reached_plus{m}"]=mt is not None
            row[f"a_exit_before_plus{m}"]=bool(a_ts and mt and a_ts<mt)
            row[f"b_exit_before_plus{m}"]=bool(b_ts and mt and b_ts<mt)

        validated.append(row)

    if not validated:
        raise SystemExit("STOP: no RUNNER_STRENGTHENING events validated")

    baseline=[r["baseline_points"] for r in validated]
    avals=[r["candidate_a_points"] for r in validated]
    bvals=[r["candidate_b_points"] for r in validated]

    sb=score("BASELINE",baseline,baseline)
    sa=score("A_W3_AGE30_CAP20",avals,baseline)
    sc=score("B_PRIMARY_OFF_CAP20",bvals,baseline)

    a_primary=sum(r["candidate_a_exit_type"]=="PRIMARY_W3_AGE30" for r in validated)
    a_rescue=sum(r["candidate_a_exit_type"]=="CAP20_RESCUE" for r in validated)
    a_fallback=len(validated)-a_primary-a_rescue

    b_rescue=sum(r["candidate_b_exit_type"]=="CAP20_RESCUE" for r in validated)
    b_fallback=len(validated)-b_rescue

    a_actual=[r for r in validated if r["candidate_a_exit_timestamp"]]
    b_actual=[r for r in validated if r["candidate_b_exit_timestamp"]]

    a_later=sum(r["candidate_a_later_new_mfe"] is True for r in a_actual)
    b_later=sum(r["candidate_b_later_new_mfe"] is True for r in b_actual)

    preservation={}
    for label in ("a","b"):
        preservation[label]={}
        for m in MILESTONES:
            reached=[r for r in validated if r[f"reached_plus{m}"]]
            cut=[r for r in reached if r[f"{label}_exit_before_plus{m}"]]
            preserved=len(reached)-len(cut)
            preservation[label][m]={
                "reached":len(reached),
                "preserved":preserved,
                "rate":preserved/len(reached) if reached else None,
            }

    diff=stats([a-b for a,b in zip(avals,bvals)])

    lines=[
        "B FAMILY — V43 DUAL-CANDIDATE HISTORICAL COMPARISON",
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
        f"A W3/AGE30/CAP20 total={fmt(sa['total_points'])} "
        f"Δbase={fmt(sa['delta_vs_baseline_total'])} "
        f"mean={fmt(sa['mean_points'])} median={fmt(sa['median_points'])} "
        f"worst={fmt(sa['worst_points'])} maxDD={fmt(sa['max_drawdown_points'])}",
        f"B PRIMARY_OFF/CAP20 total={fmt(sc['total_points'])} "
        f"Δbase={fmt(sc['delta_vs_baseline_total'])} "
        f"mean={fmt(sc['mean_points'])} median={fmt(sc['median_points'])} "
        f"worst={fmt(sc['worst_points'])} maxDD={fmt(sc['max_drawdown_points'])}",
        f"A minus B total={fmt(diff['total'])} mean={fmt(diff['mean'])} "
        f"median={fmt(diff['median'])}",
        "",
        "EXIT MIX",
        "-"*118,
        f"A: primary={a_primary} rescue={a_rescue} fallback={a_fallback}",
        f"B: primary=0 rescue={b_rescue} fallback={b_fallback}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-"*118,
    ]

    for m in MILESTONES:
        pa=preservation["a"][m]
        pb=preservation["b"][m]
        if pa["rate"] is not None:
            lines.append(
                f"+{m}: A {pa['preserved']}/{pa['reached']} ({pa['rate']*100:.1f}%) "
                f"| B {pb['preserved']}/{pb['reached']} ({pb['rate']*100:.1f}%)"
            )

    lines += [
        f"later new MFE: A {a_later}/{len(a_actual)} | B {b_later}/{len(b_actual)}",
        "",
        "INTERPRETATION GUARDS",
        "-"*118,
        "- V43 performs no tuning grid.",
        "- Candidate A and B are frozen before this run.",
        "- This block is date-separated from the V42 43-event tuning population.",
        "- It is not globally pristine because earlier B-family research used this period.",
        "- Use V43 to judge whether the single W3/AGE30 primary component adds repeatable value.",
        "- Untouched forward validation from 2026-09-29 remains reserved.",
        "- Underlying NIFTY directional points only.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(EVENTS_CSV,validated)
    write_csv(SCORECARD_CSV,[sb,sa,sc])
    REPORT_JSON.write_text(json.dumps({
        "version":"V43",
        "range":{"start":START_DATE,"end":END_DATE},
        "dual_raw_sessions":len(sessions),
        "validated_events":len(validated),
        "scorecard":{"baseline":sb,"candidate_a":sa,"candidate_b":sc},
        "a_minus_b":diff,
        "exit_mix":{
            "a":{"primary":a_primary,"rescue":a_rescue,"fallback":a_fallback},
            "b":{"primary":0,"rescue":b_rescue,"fallback":b_fallback},
        },
        "preservation":preservation,
        "later_new_mfe":{"a":a_later,"b":b_later},
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
