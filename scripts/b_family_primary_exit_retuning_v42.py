#!/usr/bin/env python3
"""
B FAMILY — V42 PRIMARY-EXIT RETUNING WITH CAP20 FIXED

Why V42
-------
V41 on the larger 43-event population showed:

    baseline                 +2416.05
    V41_CAP20                +2370.35   (-45.70 vs baseline)
    V41_NO_RESCUE            +2247.70   (-168.35 vs baseline)

Therefore:
- CAP20 rescue ADDS +122.65 points vs fallback baseline on the rows it rescues.
- The remaining shortfall is primarily associated with the V35 primary-exit layer.

V42 keeps the CAP20 rescue FIXED and retunes only the primary exit.

Primary search grid
-------------------
weakening streak:
    OFF, 1, 2, 3

minimum degraded age:
    5, 10, 15, 20, 30 minutes

Notes:
- OFF means no V35-style primary exit; only CAP20 rescue + baseline fallback.
- CAP20 rescue is frozen:
    first recovery above degraded target
    then first rebreak below target after >=10m
    rescue only if current directional points <= +20
- No entry logic changes.
- Same 43-event historical-development population from V40.1.

Outputs
-------
- total / mean / median / worst / best / maxDD
- delta vs baseline
- delta vs V41_CAP20
- primary contribution vs fallback
- rescue contribution vs fallback
- primary / rescue / fallback counts
- +30/+40/+50/+75/+100 chase preservation
- later-new-MFE after actual exits

Underlying NIFTY directional points only.
This is development/tuning, not independent validation.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

V40_EVENTS = (
    RESEARCH / "b-family-v38-cap50-validation-v40_1"
    / "validated-runner-events-v40_1.csv"
)

OUTDIR = RESEARCH / "b-family-primary-exit-retuning-v42"
LEADERBOARD = OUTDIR / "candidate-leaderboard-v42.csv"
EVENTS = OUTDIR / "candidate-event-results-v42.csv"
REPORT = OUTDIR / "report-v42.json"
SUMMARY = OUTDIR / "summary-v42.txt"

STREAKS = (None, 1, 2, 3)   # None = primary OFF
AGES = (5, 10, 15, 20, 30)
MILESTONES = (30, 40, 50, 75, 100)

BASELINE_TOTAL_REFERENCE = 2416.05
V41_CAP20_REFERENCE = 2370.35


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("", None) else float(v)


def parse_dt(s):
    return datetime.fromisoformat(s)


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def stats(vals):
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(
        n=len(xs),
        total=sum(xs),
        mean=mean(xs),
        median=median(xs),
        min=min(xs),
        max=max(xs),
    )


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
            by[r["session_date"]][r["timestamp"]] = {
                "open":float(r["open"]),
                "high":float(r["high"]),
                "low":float(r["low"]),
                "close":float(r["close"]),
            }
    return dict(by)


def build_attempts_from_degraded(direction, entry, degraded_ts, target, terminal_ts, u):
    """
    Failed recovery attempts below degraded-start target.
    Same causal shape used in V40.1.
    """
    attempts=[]
    in_rise=False
    peak_ts=None
    peak_move=None
    prev_move=None

    for ts in sorted(u):
        if ts <= degraded_ts:
            continue
        if ts >= terminal_ts:
            break

        move=directional(direction,entry,u[ts]["close"])

        # Successful retake ends failed-attempt collection for the first degraded episode.
        if move > target:
            break

        if prev_move is None:
            prev_move=move
            continue

        if move > prev_move:
            if not in_rise:
                in_rise=True
                peak_ts=ts
                peak_move=move
            elif move >= peak_move:
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

        prev_move=move

    if in_rise and peak_ts and peak_move is not None and peak_move <= target:
        attempts.append({
            "peak_timestamp":peak_ts,
            "peak_move":peak_move,
            "gap_to_target":target-peak_move,
        })

    return attempts


def primary_exit(degraded_ts, attempts, streak_required, min_age):
    if streak_required is None:
        return None

    best=None
    prev=None
    weak_streak=0

    for a in attempts:
        gap=a["gap_to_target"]

        if best is None or gap < best:
            best=gap
            weak_streak=0
        else:
            if prev is not None and gap > prev:
                weak_streak += 1
            else:
                weak_streak=0

        age=(parse_dt(a["peak_timestamp"])-parse_dt(degraded_ts)).total_seconds()/60.0

        if weak_streak >= streak_required and age >= min_age:
            return a["peak_timestamp"]

        prev=gap

    return None


def first_recovery(direction, entry, degraded_ts, target, terminal_ts, u):
    for ts in sorted(u):
        if ts <= degraded_ts:
            continue
        if ts >= terminal_ts:
            break
        move=directional(direction,entry,u[ts]["close"])
        if move > target:
            return ts
    return None


def cap20_rescue(direction, entry, recovery_ts, target, terminal_ts, u):
    for ts in sorted(u):
        if ts <= recovery_ts:
            continue
        if ts >= terminal_ts:
            break

        age=(parse_dt(ts)-parse_dt(recovery_ts)).total_seconds()/60.0
        if age < 10:
            continue

        move=directional(direction,entry,u[ts]["close"])
        if move < target:
            if move <= 20:
                return ts
            return None

    return None


def later_new_mfe(direction, entry, exit_ts, terminal_ts, u):
    pre=None

    for ts in sorted(u):
        if ts > exit_ts:
            break
        fav=directional(direction,entry,favorable(direction,u[ts]))
        pre=fav if pre is None else max(pre,fav)

    if pre is None:
        return None

    for ts in sorted(u):
        if ts <= exit_ts:
            continue
        if ts >= terminal_ts:
            break
        fav=directional(direction,entry,favorable(direction,u[ts]))
        if fav > pre + 1e-9:
            return True

    return False


def milestone_ts(direction, entry, entry_ts, terminal_ts, u, m):
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts >= terminal_ts:
            break
        if directional(direction,entry,favorable(direction,u[ts])) >= m:
            return ts
    return None


def evaluate(streak, age, src_rows, uall):
    if streak is None:
        name="V42_PRIMARY_OFF_CAP20"
    else:
        name=f"V42_W{streak}_AGE{age}_CAP20"

    out=[]

    for src in src_rows:
        d=src["session_date"]
        u=uall.get(d)
        if not u:
            raise SystemExit(f"STOP: missing underlying for {d}")

        direction=src["direction"]
        entry_ts=src["entry_timestamp"]

        # Recover entry close from underlying exact entry timestamp.
        if entry_ts not in u:
            raise SystemExit(f"STOP: missing entry candle {d} {entry_ts}")
        entry=u[entry_ts]["close"]

        terminal_ts=src["baseline_terminal_timestamp"]
        baseline=f(src["baseline_points"])
        degraded_ts=src.get("degraded_timestamp") or None

        exit_ts=None
        exit_type="FALLBACK_BASELINE"

        if degraded_ts:
            # V40.1 target is directional close move at degraded timestamp.
            target=directional(direction,entry,u[degraded_ts]["close"])

            attempts=build_attempts_from_degraded(
                direction,entry,degraded_ts,target,terminal_ts,u
            )

            pexit=primary_exit(
                degraded_ts,attempts,streak,age
            )

            if pexit and pexit in u and pexit < terminal_ts:
                exit_ts=pexit
                exit_type="PRIMARY"
            else:
                rec=first_recovery(
                    direction,entry,degraded_ts,target,terminal_ts,u
                )
                if rec:
                    rescue=cap20_rescue(
                        direction,entry,rec,target,terminal_ts,u
                    )
                    if rescue:
                        exit_ts=rescue
                        exit_type="CAP20_RESCUE"

        if exit_ts:
            points=directional(direction,entry,u[exit_ts]["close"])
            later=later_new_mfe(direction,entry,exit_ts,terminal_ts,u)
        else:
            points=baseline
            later=None

        r={
            "candidate":name,
            "session_date":d,
            "direction":direction,
            "entry_timestamp":entry_ts,
            "exit_type":exit_type,
            "exit_timestamp":exit_ts,
            "points":points,
            "baseline_points":baseline,
            "delta_vs_baseline":points-baseline,
            "later_new_mfe":later,
        }

        for m in MILESTONES:
            mt=milestone_ts(direction,entry,entry_ts,terminal_ts,u,m)
            r[f"reached_plus{m}"]=mt is not None
            r[f"exit_before_plus{m}"]=bool(exit_ts and mt and exit_ts<mt)

        out.append(r)

    vals=[r["points"] for r in out]
    bvals=[r["baseline_points"] for r in out]
    s=stats(vals)
    ds=stats([v-b for v,b in zip(vals,bvals)])

    prim=[r for r in out if r["exit_type"]=="PRIMARY"]
    rescue=[r for r in out if r["exit_type"]=="CAP20_RESCUE"]
    fallback=[r for r in out if r["exit_type"]=="FALLBACK_BASELINE"]

    prim_delta=stats(r["points"]-r["baseline_points"] for r in prim)
    rescue_delta=stats(r["points"]-r["baseline_points"] for r in rescue)

    actual=[r for r in out if r["exit_timestamp"]]
    later=sum(r["later_new_mfe"] is True for r in actual)

    sm={
        "candidate":name,
        "weakening_streak":streak,
        "min_degraded_age":age if streak is not None else None,
        "events":len(out),
        "primary_exits":len(prim),
        "rescue_exits":len(rescue),
        "fallbacks":len(fallback),
        "actual_exits":len(actual),
        "later_new_mfe_count":later,
        "total_points":s["total"],
        "mean_points":s["mean"],
        "median_points":s["median"],
        "worst_points":s["min"],
        "best_points":s["max"],
        "max_drawdown_points":maxdd(vals),
        "delta_vs_baseline_total":ds["total"],
        "delta_vs_v41_cap20_reference":s["total"]-V41_CAP20_REFERENCE,
        "primary_delta_vs_baseline_total":prim_delta["total"],
        "primary_delta_vs_baseline_mean":prim_delta["mean"],
        "rescue_delta_vs_baseline_total":rescue_delta["total"],
        "rescue_delta_vs_baseline_mean":rescue_delta["mean"],
    }

    for m in MILESTONES:
        reached=[r for r in out if r[f"reached_plus{m}"]]
        cut=[r for r in reached if r[f"exit_before_plus{m}"]]
        preserved=len(reached)-len(cut)
        sm[f"plus{m}_reached"]=len(reached)
        sm[f"plus{m}_preserved"]=preserved
        sm[f"plus{m}_rate"]=preserved/len(reached) if reached else None

    return sm,out


def main():
    print("B FAMILY — V42 PRIMARY-EXIT RETUNING WITH CAP20 FIXED")
    print("="*118)

    src=load_csv(V40_EVENTS)
    if len(src)!=43:
        raise SystemExit(f"STOP: expected 43 V40.1 events, got {len(src)}")

    uall=discover_underlying()

    leaders=[]
    all_events=[]

    # Primary OFF evaluated once.
    s,rows=evaluate(None,None,src,uall)
    leaders.append(s)
    all_events.extend(rows)
    print(
        f"{s['candidate']:<25} total={fmt(s['total_points'])} "
        f"Δbase={fmt(s['delta_vs_baseline_total'])} "
        f"ΔV41={fmt(s['delta_vs_v41_cap20_reference'])} "
        f"DD={fmt(s['max_drawdown_points'])} "
        f"P={s['primary_exits']} R={s['rescue_exits']} "
        f"+75={s['plus75_preserved']}/{s['plus75_reached']} "
        f"+100={s['plus100_preserved']}/{s['plus100_reached']}"
    )

    for streak in (1,2,3):
        for age in AGES:
            s,rows=evaluate(streak,age,src,uall)
            leaders.append(s)
            all_events.extend(rows)

            print(
                f"{s['candidate']:<25} total={fmt(s['total_points'])} "
                f"Δbase={fmt(s['delta_vs_baseline_total'])} "
                f"ΔV41={fmt(s['delta_vs_v41_cap20_reference'])} "
                f"DD={fmt(s['max_drawdown_points'])} "
                f"P={s['primary_exits']} R={s['rescue_exits']} "
                f"+75={s['plus75_preserved']}/{s['plus75_reached']} "
                f"+100={s['plus100_preserved']}/{s['plus100_reached']}"
            )

    leaders.sort(
        key=lambda r:(
            r["total_points"],
            r["plus100_rate"] if r["plus100_rate"] is not None else -1,
            r["plus75_rate"] if r["plus75_rate"] is not None else -1,
            r["max_drawdown_points"],
        ),
        reverse=True,
    )

    for idx,r in enumerate(leaders,1):
        r["rank"]=idx

    winner=leaders[0]

    lines=[
        "B FAMILY — V42 PRIMARY-EXIT RETUNING WITH CAP20 FIXED",
        "="*118,
        f"events={len(src)}",
        f"baseline_reference={fmt(BASELINE_TOTAL_REFERENCE)}",
        f"V41_CAP20_reference={fmt(V41_CAP20_REFERENCE)}",
        "",
        "TOP CANDIDATES",
        "-"*118,
    ]

    for r in leaders[:12]:
        lines.append(
            f"#{r['rank']:02d} {r['candidate']} "
            f"total={fmt(r['total_points'])} "
            f"Δbase={fmt(r['delta_vs_baseline_total'])} "
            f"ΔV41={fmt(r['delta_vs_v41_cap20_reference'])} "
            f"mean={fmt(r['mean_points'])} median={fmt(r['median_points'])} "
            f"worst={fmt(r['worst_points'])} maxDD={fmt(r['max_drawdown_points'])} "
            f"P={r['primary_exits']} R={r['rescue_exits']} "
            f"primaryΔ={fmt(r['primary_delta_vs_baseline_total'])} "
            f"rescueΔ={fmt(r['rescue_delta_vs_baseline_total'])}"
        )

    lines += [
        "",
        "WINNER SCORECARD",
        "-"*118,
        f"candidate={winner['candidate']}",
        f"total={fmt(winner['total_points'])}",
        f"Δ vs baseline={fmt(winner['delta_vs_baseline_total'])}",
        f"Δ vs V41_CAP20={fmt(winner['delta_vs_v41_cap20_reference'])}",
        f"mean={fmt(winner['mean_points'])}",
        f"median={fmt(winner['median_points'])}",
        f"worst={fmt(winner['worst_points'])}",
        f"best={fmt(winner['best_points'])}",
        f"maxDD={fmt(winner['max_drawdown_points'])}",
        f"primary exits={winner['primary_exits']}",
        f"rescue exits={winner['rescue_exits']}",
        f"fallbacks={winner['fallbacks']}",
        f"primary contribution vs baseline={fmt(winner['primary_delta_vs_baseline_total'])}",
        f"rescue contribution vs baseline={fmt(winner['rescue_delta_vs_baseline_total'])}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-"*118,
    ]

    for m in MILESTONES:
        rate=winner[f"plus{m}_rate"]
        lines.append(
            f"+{m}: {winner[f'plus{m}_preserved']}/{winner[f'plus{m}_reached']} "
            f"({rate*100:.1f}%)" if rate is not None else f"+{m}: no events"
        )

    lines += [
        f"later new MFE after actual exit: "
        f"{winner['later_new_mfe_count']}/{winner['actual_exits']}",
        "",
        "INTERPRETATION",
        "-"*118,
        "- CAP20 rescue is fixed in V42.",
        "- Only the primary exit is retuned.",
        "- If PRIMARY_OFF wins, the V35 primary layer should be removed from the next candidate.",
        "- If another W/AGE combination wins, that becomes the next development candidate.",
        "- This is tuning on the same 43 events, not independent validation.",
        "- Forward block beginning 2026-09-29 remains untouched.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(LEADERBOARD,leaders)
    write_csv(EVENTS,all_events)
    REPORT.write_text(json.dumps({
        "version":"V42",
        "events":len(src),
        "baseline_reference":BASELINE_TOTAL_REFERENCE,
        "v41_cap20_reference":V41_CAP20_REFERENCE,
        "winner":winner,
        "leaderboard":leaders,
    },indent=2))
    SUMMARY.write_text("\n".join(lines)+"\n")

    print()
    print("\n".join(lines))
    print()
    print("LEADERBOARD :",LEADERBOARD)
    print("EVENTS      :",EVENTS)
    print("REPORT JSON :",REPORT)
    print("SUMMARY     :",SUMMARY)


if __name__=="__main__":
    main()
