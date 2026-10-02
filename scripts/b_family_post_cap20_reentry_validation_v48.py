#!/usr/bin/env python3
"""
B FAMILY — V48 FROZEN POST-CAP20 RE-ENTRY VALIDATION

Candidate frozen from V47 diagnostic:
- Base policy: PRIMARY_OFF + CAP20 rescue.
- After a CAP20 rescue, allow ONE shadow re-entry only if:
    1) within 20 minutes of rescue,
    2) 1m CLOSE retakes the original degraded-start directional close target,
    3) directional futures-VWAP is above its rescue-time level.
- Re-entry occurs at that candle CLOSE.
- Re-entry second leg exits only at the original structural/session terminal.
- No second rescue, no primary exit, no repeated re-entry.

Why 20 minutes?
V47 development diagnostic:
- all 3 later-new-MFE rescues retook target in 2/13/19m,
- no-later-MFE rescues retook in 61m / never.
Thus 20m is a DEVELOPMENT-derived threshold and must be validated separately.

Validation population:
V40.1 canonical 43 RUNNER_STRENGTHENING events
(2025-12-12..2026-09-08).

IMPORTANT:
This 43-event block was used for CAP20/primary tuning, but not for deriving the
post-rescue 20m re-entry rule. Treat V48 as historical validation evidence, not
globally pristine OOS.

Underlying NIFTY directional points only.
No option premium / rupee P&L / live order logic.
"""

from __future__ import annotations
import csv, json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

V40_EVENTS = (
    RESEARCH / "b-family-v38-cap50-validation-v40_1"
    / "validated-runner-events-v40_1.csv"
)

OUTDIR = RESEARCH / "b-family-post-cap20-reentry-validation-v48"
EVENTS_CSV = OUTDIR / "reentry-events-v48.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v48.csv"
REPORT_JSON = OUTDIR / "report-v48.json"
SUMMARY_TXT = OUTDIR / "summary-v48.txt"

REENTRY_WINDOW_MIN = 20
SECOND_LEG_MILESTONES = (20,30,50,75,100)


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("",None) else float(v)


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a,b):
    return (parse_dt(b)-parse_dt(a)).total_seconds()/60.0


def directional(direction,entry,price):
    return price-entry if direction=="BULLISH" else entry-price


def directional_vwap(direction,row):
    if row is None:
        return None
    raw=row["close"]-row["vwap"]
    return raw if direction=="BULLISH" else -raw


def favorable(direction,bar):
    return bar["high"] if direction=="BULLISH" else bar["low"]


def stats(vals):
    xs=[float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(
        n=len(xs), total=sum(xs), mean=mean(xs), median=median(xs),
        min=min(xs), max=max(xs)
    )


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


def discover_underlying():
    needed={r["session_date"] for r in load_csv(V40_EVENTS)}
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
            if d in needed:
                by[d][r["timestamp"]] = {
                    "open":float(r["open"]),"high":float(r["high"]),
                    "low":float(r["low"]),"close":float(r["close"]),
                }
    return dict(by)


def discover_futures():
    needed={r["session_date"] for r in load_csv(V40_EVENTS)}
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
            if d in needed and r.get("session_vwap") not in ("",None):
                by[d][r["timestamp"]] = {
                    "close":float(r["close"]),
                    "vwap":float(r["session_vwap"]),
                }
    return dict(by)


def first_recovery(direction,entry,degraded_ts,target,terminal,u):
    for ts in sorted(u):
        if ts<=degraded_ts: continue
        if ts>=terminal: break
        if directional(direction,entry,u[ts]["close"]) > target:
            return ts
    return None


def cap20_rescue(direction,entry,recovery_ts,target,terminal,u):
    for ts in sorted(u):
        if ts<=recovery_ts: continue
        if ts>=terminal: break
        if mins(recovery_ts,ts)<10: continue
        move=directional(direction,entry,u[ts]["close"])
        if move<target:
            return ts if move<=20 else None
    return None


def frozen_reentry(direction,entry,rescue_ts,target,terminal,u,fut):
    rescue_dv=directional_vwap(direction,fut.get(rescue_ts))
    if rescue_dv is None:
        return None

    for ts in sorted(u):
        if ts<=rescue_ts: continue
        if ts>=terminal: break
        age=mins(rescue_ts,ts)
        if age>REENTRY_WINDOW_MIN:
            break

        move=directional(direction,entry,u[ts]["close"])
        dv=directional_vwap(direction,fut.get(ts))
        if move>target and dv is not None and dv>rescue_dv:
            return ts
    return None


def second_leg_mfe(direction,reentry_price,reentry_ts,terminal,u):
    best=None
    for ts in sorted(u):
        if ts<=reentry_ts: continue
        if ts>=terminal: break
        fav=directional(direction,reentry_price,favorable(direction,u[ts]))
        best=fav if best is None else max(best,fav)
    return best


def main():
    print("B FAMILY — V48 FROZEN POST-CAP20 RE-ENTRY VALIDATION")
    print("="*118)

    src=load_csv(V40_EVENTS)
    if len(src)!=43:
        raise SystemExit(f"STOP: expected 43 V40.1 events, got {len(src)}")

    uall=discover_underlying()
    fall=discover_futures()

    out=[]

    for r in src:
        d=r["session_date"]
        u=uall.get(d)
        fut=fall.get(d)
        if not u or not fut:
            raise SystemExit(f"STOP: missing raw data for {d}")

        direction=r["direction"]
        entry_ts=r["entry_timestamp"]
        if entry_ts not in u:
            raise SystemExit(f"STOP: missing entry candle {d} {entry_ts}")

        entry=u[entry_ts]["close"]
        terminal=r["baseline_terminal_timestamp"]
        baseline=f(r["baseline_points"])
        degraded_ts=r.get("degraded_timestamp") or None

        base_points=baseline
        rescue_ts=None
        rescue_points=None
        reentry_ts=None
        reentry_price=None
        second_leg_points=0.0
        second_leg_mfe_val=None

        if degraded_ts:
            if degraded_ts not in u:
                raise SystemExit(f"STOP: missing degraded candle {d} {degraded_ts}")
            target=directional(direction,entry,u[degraded_ts]["close"])

            recovery=first_recovery(
                direction,entry,degraded_ts,target,terminal,u
            )
            if recovery:
                rescue_ts=cap20_rescue(
                    direction,entry,recovery,target,terminal,u
                )

            if rescue_ts:
                rescue_points=directional(
                    direction,entry,u[rescue_ts]["close"]
                )
                base_points=rescue_points

                reentry_ts=frozen_reentry(
                    direction,entry,rescue_ts,target,terminal,u,fut
                )
                if reentry_ts:
                    reentry_price=u[reentry_ts]["close"]
                    terminal_price=u[terminal]["close"]
                    second_leg_points=directional(
                        direction,reentry_price,terminal_price
                    )
                    second_leg_mfe_val=second_leg_mfe(
                        direction,reentry_price,reentry_ts,terminal,u
                    )

        combined=base_points+second_leg_points

        row={
            "session_date":d,
            "direction":direction,
            "entry_timestamp":entry_ts,
            "baseline_points":baseline,
            "base_primary_off_cap20_points":base_points,
            "rescue_timestamp":rescue_ts,
            "rescue_points":rescue_points,
            "reentry_timestamp":reentry_ts,
            "reentry_minutes_after_rescue":mins(rescue_ts,reentry_ts) if rescue_ts and reentry_ts else None,
            "reentry_price":reentry_price,
            "second_leg_points_to_terminal":second_leg_points if reentry_ts else None,
            "second_leg_mfe":second_leg_mfe_val,
            "combined_points":combined,
            "delta_reentry_vs_base":combined-base_points,
            "delta_combined_vs_baseline":combined-baseline,
        }

        for m in SECOND_LEG_MILESTONES:
            row[f"second_leg_reached_plus{m}"]=bool(
                second_leg_mfe_val is not None and second_leg_mfe_val>=m
            )

        out.append(row)

    baseline_vals=[r["baseline_points"] for r in out]
    base_vals=[r["base_primary_off_cap20_points"] for r in out]
    combined_vals=[r["combined_points"] for r in out]

    sb=stats(baseline_vals)
    sbase=stats(base_vals)
    scomb=stats(combined_vals)
    dbase=stats([v-b for v,b in zip(base_vals,baseline_vals)])
    dre=stats([v-b for v,b in zip(combined_vals,base_vals)])
    dcomb=stats([v-b for v,b in zip(combined_vals,baseline_vals)])

    rescues=[r for r in out if r["rescue_timestamp"]]
    reentries=[r for r in out if r["reentry_timestamp"]]

    milestone={}
    for m in SECOND_LEG_MILESTONES:
        milestone[m]=sum(r[f"second_leg_reached_plus{m}"] for r in reentries)

    lines=[
        "B FAMILY — V48 FROZEN POST-CAP20 RE-ENTRY VALIDATION",
        "="*118,
        f"events={len(out)}",
        f"CAP20_rescues={len(rescues)}",
        f"frozen_reentries={len(reentries)}",
        "",
        "SCORECARD",
        "-"*118,
        f"BASELINE total={fmt(sb['total'])} mean={fmt(sb['mean'])} "
        f"median={fmt(sb['median'])} worst={fmt(sb['min'])} "
        f"maxDD={fmt(maxdd(baseline_vals))}",
        f"PRIMARY_OFF+CAP20 total={fmt(sbase['total'])} "
        f"Δbase={fmt(dbase['total'])} mean={fmt(sbase['mean'])} "
        f"median={fmt(sbase['median'])} worst={fmt(sbase['min'])} "
        f"maxDD={fmt(maxdd(base_vals))}",
        f"+ FROZEN REENTRY total={fmt(scomb['total'])} "
        f"Δbase={fmt(dcomb['total'])} "
        f"ΔvsCAP20={fmt(dre['total'])} "
        f"mean={fmt(scomb['mean'])} median={fmt(scomb['median'])} "
        f"worst={fmt(scomb['min'])} maxDD={fmt(maxdd(combined_vals))}",
        "",
        "RE-ENTRY SECOND-LEG MILESTONES",
        "-"*118,
    ]

    for m in SECOND_LEG_MILESTONES:
        lines.append(
            f"+{m}: {milestone[m]}/{len(reentries)}"
            if reentries else f"+{m}: no reentries"
        )

    lines += [
        "",
        "PER RE-ENTRY EVENT",
        "-"*118,
    ]

    for r in reentries:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"rescue={fmt(r['rescue_points'])} "
            f"reentryAfter={fmt(r['reentry_minutes_after_rescue'])}m "
            f"secondLeg={fmt(r['second_leg_points_to_terminal'])} "
            f"secondLegMFE={fmt(r['second_leg_mfe'])} "
            f"combined={fmt(r['combined_points'])} "
            f"ΔvsBase={fmt(r['delta_reentry_vs_base'])}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-"*118,
        "- V48 tests one frozen re-entry rule derived from V47.",
        "- The 20-minute window is development-derived and is NOT retuned here.",
        "- This 43-event block was used for earlier CAP20/primary research, but not for deriving the V47 re-entry rule.",
        "- Treat as historical validation evidence, not pristine OOS.",
        "- No option premium, rupee P&L, or live orders.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(EVENTS_CSV,out)
    write_csv(SCORECARD_CSV,[
        {
            "policy":"BASELINE",
            "n":len(out),
            "total_points":sb["total"],
            "mean_points":sb["mean"],
            "median_points":sb["median"],
            "worst_points":sb["min"],
            "max_drawdown_points":maxdd(baseline_vals),
        },
        {
            "policy":"PRIMARY_OFF_CAP20",
            "n":len(out),
            "total_points":sbase["total"],
            "mean_points":sbase["mean"],
            "median_points":sbase["median"],
            "worst_points":sbase["min"],
            "max_drawdown_points":maxdd(base_vals),
            "delta_vs_baseline_total":dbase["total"],
        },
        {
            "policy":"PRIMARY_OFF_CAP20_PLUS_FROZEN_REENTRY",
            "n":len(out),
            "total_points":scomb["total"],
            "mean_points":scomb["mean"],
            "median_points":scomb["median"],
            "worst_points":scomb["min"],
            "max_drawdown_points":maxdd(combined_vals),
            "delta_vs_baseline_total":dcomb["total"],
            "delta_vs_cap20_total":dre["total"],
        },
    ])
    REPORT_JSON.write_text(json.dumps({
        "version":"V48",
        "events":len(out),
        "rescue_count":len(rescues),
        "reentry_count":len(reentries),
        "reentry_window_minutes":REENTRY_WINDOW_MIN,
        "scorecard":{
            "baseline":sb,
            "base_cap20":sbase,
            "combined":scomb,
            "delta_base_vs_baseline":dbase,
            "delta_reentry_vs_base":dre,
            "delta_combined_vs_baseline":dcomb,
        },
        "second_leg_milestones":milestone,
        "methodology":{
            "reentry_rule_frozen_before_run":True,
            "reentry_rule_retuned_here":False,
            "globally_pristine_oos":False,
        },
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
