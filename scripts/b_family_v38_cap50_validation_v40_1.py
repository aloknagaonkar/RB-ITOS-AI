#!/usr/bin/env python3
"""
V40.1 PATCH — schema-based B-event discovery for V40.

The original V40 searched only CSV filenames containing "b-event"/"b-events".
The canonical 180-session B-family artifacts do not use that filename pattern,
so V40 found 0 events despite having all 180 underlying/futures sessions.

This patch:
- discovers candidate CSVs by SCHEMA, not filename
- normalizes common column aliases
- requires BULLISH/BEARISH direction + entry timestamp
- restricts dates to 2025-12-12..2026-09-08
- deduplicates by (session_date, direction, entry_timestamp)
- prefers the richest row with entry/structural/+20 fields
- prints source-file diagnostics before validation

It does NOT change V38_CAP50 logic or tune any parameters.
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

START_DATE = "2025-12-12"
END_DATE = "2026-09-08"
DEV_V38_TOTAL = 1233.75

OUTDIR = RESEARCH / "b-family-v38-cap50-validation-v40_1"
EVENTS_CSV = OUTDIR / "validated-runner-events-v40_1.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v40_1.csv"
REPORT_JSON = OUTDIR / "report-v40_1.json"
SUMMARY_TXT = OUTDIR / "summary-v40_1.txt"

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
    xs = [float(x) for x in vals if x not in ("", None)]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(n=len(xs),total=sum(xs),mean=mean(xs),median=median(xs),
                min=min(xs),max=max(xs))


def max_drawdown(vals):
    equity=0.0; peak=0.0; mdd=0.0
    for x in vals:
        equity += float(x)
        peak = max(peak,equity)
        mdd = min(mdd,equity-peak)
    return mdd


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


def first_present(row, names):
    for n in names:
        if n in row and row.get(n) not in ("", None):
            return row.get(n)
    return None


def normalize_event_row(r):
    out = dict(r)
    for canon, aliases in ALIASES.items():
        v = first_present(r, aliases)
        if v not in ("", None):
            out[canon] = v

    d = out.get("session_date")
    direction = str(out.get("direction","")).upper()
    ets = out.get("entry_timestamp")

    if not d or not ets:
        return None
    if direction not in ("BULLISH","BEARISH"):
        return None

    out["direction"] = direction
    return out


def discover_underlying():
    by=defaultdict(dict); files=0
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try: rows=load_csv(p)
        except Exception: continue
        if not rows or not {"session_date","timestamp","open","high","low","close"}.issubset(rows[0].keys()):
            continue
        used=False
        for r in rows:
            d=r["session_date"]
            if not date_in_range(d): continue
            by[d][r["timestamp"]]={
                "open":float(r["open"]),"high":float(r["high"]),
                "low":float(r["low"]),"close":float(r["close"])
            }
            used=True
        if used: files += 1
    return dict(by),files


def discover_futures():
    by=defaultdict(dict); files=0
    for p in ROOT.rglob("*.csv"):
        n=p.name.lower()
        if "futures" not in n or "vwap" not in n:
            continue
        try: rows=load_csv(p)
        except Exception: continue
        if not rows or not {"session_date","timestamp","close","session_vwap"}.issubset(rows[0].keys()):
            continue
        used=False
        for r in rows:
            d=r["session_date"]
            if not date_in_range(d) or r.get("session_vwap") in ("",None): continue
            by[d][r["timestamp"]]={"close":float(r["close"]),"vwap":float(r["session_vwap"])}
            used=True
        if used: files += 1
    return dict(by),files


def discover_b_events_schema():
    found={}
    source_counts=defaultdict(int)
    scanned=0
    schema_files=0

    for p in RESEARCH.rglob("*.csv"):
        # Don't ingest our own generated validation outputs.
        if "v40" in str(p).lower():
            continue

        try:
            rows=load_csv(p)
        except Exception:
            continue
        scanned += 1
        if not rows:
            continue

        headers=set(rows[0].keys())

        # Fast schema gate: need some date, direction and entry-time alias.
        if not any(x in headers for x in ALIASES["session_date"]):
            continue
        if not any(x in headers for x in ALIASES["direction"]):
            continue
        if not any(x in headers for x in ALIASES["entry_timestamp"]):
            continue

        schema_files += 1

        for raw in rows:
            r=normalize_event_row(raw)
            if not r:
                continue
            if not date_in_range(r["session_date"]):
                continue

            # Reject minute-level timelines accidentally carrying entry metadata:
            # prefer one-row-per-event shapes by requiring at least one event-like
            # field OR a filename suggesting setup/candidate/event output.
            event_like = any(
                r.get(x) not in ("",None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "plus20_timestamp",
                    "mfe",
                    "mae",
                    "candidate",
                    "event_type",
                    "setup_family",
                )
            )
            name_like = any(
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
                    "mfe","mae",
                    "observation_end_timestamp",
                    "classification",
                )
            )

            if k not in found or richness > found[k][0]:
                found[k]=(richness,r,str(p))

            source_counts[str(p)] += 1

    return (
        {k:(v[1],v[2]) for k,v in found.items()},
        dict(sorted(source_counts.items(), key=lambda kv:(-kv[1],kv[0]))),
        scanned,
        schema_files,
    )


def terminal_for_event(event,u):
    entry_ts=event["entry_timestamp"]; direction=event["direction"]
    entry=f(event.get("entry_close"))
    if entry is None:
        if entry_ts not in u: return None
        entry=u[entry_ts]["close"]

    invalid=event.get("structural_invalidation_timestamp") or None
    trusted=sorted(u)
    if invalid and invalid in u:
        terminal_ts=invalid; terminal_type="STRUCTURAL_INVALIDATION"
    else:
        terminal_ts=trusted[-1]; terminal_type="SESSION_CUTOFF"

    return {
        "entry_close":entry,
        "terminal_timestamp":terminal_ts,
        "terminal_type":terminal_type,
        "baseline_points":directional(direction,entry,u[terminal_ts]["close"]),
    }


def find_plus20(event,u,terminal_ts,entry):
    direction=event["direction"]; entry_ts=event["entry_timestamp"]
    source=event.get("plus20_timestamp")
    if source and source in u and source<terminal_ts:
        return source
    for ts in sorted(u):
        if ts<=entry_ts: continue
        if ts>=terminal_ts: break
        if directional(direction,entry,favorable(direction,u[ts]))>=20:
            return ts
    return None


def classify_runner(event,plus20_ts,u,fut,entry,terminal_ts):
    class_ts=plus_minutes(plus20_ts,10)
    if class_ts>=terminal_ts or plus20_ts not in u or class_ts not in u:
        return None
    if plus20_ts not in fut or class_ts not in fut:
        return None
    direction=event["direction"]
    proof_move=directional(direction,entry,u[plus20_ts]["close"])
    class_move=directional(direction,entry,u[class_ts]["close"])
    net=class_move-proof_move
    pv=directional_vwap(direction,fut[plus20_ts])
    cv=directional_vwap(direction,fut[class_ts])
    vc=cv-pv
    return {
        "classification_timestamp":class_ts,
        "net_progress_10m":net,
        "directional_vwap_change_10m":vc,
        "runner_strengthening":net>0 and vc>0,
    }


def first_degraded(event,class_ts,u,fut,entry,terminal_ts):
    direction=event["direction"]; running=None; prevdv=None; prior_joint=False
    for ts in sorted(u):
        if ts<=event["entry_timestamp"]: continue
        if ts>class_ts or ts>=terminal_ts: break
        move=directional(direction,entry,u[ts]["close"])
        running=move if running is None else max(running,move)
        dv=directional_vwap(direction,fut.get(ts))
        if dv is not None: prevdv=dv

    for ts in sorted(u):
        if ts<=class_ts: continue
        if ts>=terminal_ts: break
        move=directional(direction,entry,u[ts]["close"])
        running=move if running is None else max(running,move)
        dd=running-move
        dv=directional_vwap(direction,fut.get(ts))
        dvc=None if dv is None or prevdv is None else dv-prevdv
        joint=dd>0 and dvc is not None and dvc<0
        if joint and not prior_joint:
            return {"degraded_timestamp":ts,"target_move":move}
        prior_joint=joint
        if dv is not None: prevdv=dv
    return None


def failed_recovery_attempts(degraded,event,u,entry,terminal_ts):
    direction=event["direction"]; dts=degraded["degraded_timestamp"]; target=degraded["target_move"]
    attempts=[]; in_rise=False; pts=None; pm=None; prev=None

    for ts in sorted(u):
        if ts<=dts: continue
        if ts>=terminal_ts: break
        move=directional(direction,entry,u[ts]["close"])
        if move>target: break
        if prev is None:
            prev=move; continue

        if move>prev:
            if not in_rise:
                in_rise=True; pts=ts; pm=move
            elif move>=pm:
                pts=ts; pm=move
        elif in_rise:
            attempts.append({"peak_timestamp":pts,"peak_move":pm,"gap_to_target":target-pm})
            in_rise=False; pts=None; pm=None
        prev=move

    if in_rise and pts and pm is not None and pm<=target:
        attempts.append({"peak_timestamp":pts,"peak_move":pm,"gap_to_target":target-pm})
    return attempts


def v35_primary(degraded,attempts):
    best=None; prev=None; streak=0
    for a in attempts:
        gap=a["gap_to_target"]
        if best is None or gap<best:
            best=gap; streak=0
        else:
            if prev is not None and gap>prev: streak += 1
            else: streak=0
        age=(parse_dt(a["peak_timestamp"])-parse_dt(degraded["degraded_timestamp"])).total_seconds()/60
        if streak>=1 and age>=10:
            return a["peak_timestamp"]
        prev=gap
    return None


def first_recovery(degraded,event,u,entry,terminal_ts):
    direction=event["direction"]; target=degraded["target_move"]; dts=degraded["degraded_timestamp"]
    for ts in sorted(u):
        if ts<=dts: continue
        if ts>=terminal_ts: break
        move=directional(direction,entry,u[ts]["close"])
        if move>target:
            return {"timestamp":ts,"target_move":target}
    return None


def v38_rescue(recovery,event,u,entry,terminal_ts):
    direction=event["direction"]; rts=recovery["timestamp"]; target=recovery["target_move"]
    for ts in sorted(u):
        if ts<=rts: continue
        if ts>=terminal_ts: break
        age=(parse_dt(ts)-parse_dt(rts)).total_seconds()/60
        if age<10: continue
        move=directional(direction,entry,u[ts]["close"])
        if move<target:
            return {"timestamp":ts,"points":move} if move<=50 else None
    return None


def milestone_timestamp(event,u,entry,terminal_ts,m):
    for ts in sorted(u):
        if ts<=event["entry_timestamp"]: continue
        if ts>=terminal_ts: break
        if directional(event["direction"],entry,favorable(event["direction"],u[ts]))>=m:
            return ts
    return None


def later_new_mfe(event,u,entry,exit_ts,terminal_ts):
    pre=None
    for ts in sorted(u):
        if ts>exit_ts: break
        fav=directional(event["direction"],entry,favorable(event["direction"],u[ts]))
        pre=fav if pre is None else max(pre,fav)
    if pre is None: return None
    for ts in sorted(u):
        if ts<=exit_ts: continue
        if ts>=terminal_ts: break
        fav=directional(event["direction"],entry,favorable(event["direction"],u[ts]))
        if fav>pre+1e-9: return True
    return False


def score_row(name,vals,baseline=None):
    s=stats(vals)
    row={"policy":name,"n":s["n"],"total_points":s["total"],"mean_points":s["mean"],
         "median_points":s["median"],"worst_points":s["min"],"best_points":s["max"],
         "max_drawdown_points":max_drawdown(vals)}
    if baseline is not None:
        ds=stats([v-b for v,b in zip(vals,baseline)])
        row.update({"delta_vs_baseline_total":ds["total"],
                    "delta_vs_baseline_mean":ds["mean"],
                    "delta_vs_baseline_median":ds["median"]})
    return row


def main():
    print("B FAMILY — V40.1 FROZEN V38_CAP50 HISTORICAL VALIDATION")
    print("="*118)
    print(f"validation_range={START_DATE}..{END_DATE}")

    underlying,ufiles=discover_underlying()
    futures,ffiles=discover_futures()
    events,sources,scanned,schema_files=discover_b_events_schema()

    session_dates=sorted(set(underlying).intersection(futures))

    print(f"dual_raw_sessions={len(session_dates)}")
    print(f"underlying_source_files={ufiles}")
    print(f"futures_source_files={ffiles}")
    print(f"csv_files_scanned_for_events={scanned}")
    print(f"schema_candidate_files={schema_files}")
    print(f"discovered_event_keys={len(events)}")

    print()
    print("TOP EVENT SOURCES")
    print("-"*118)
    for p,c in list(sources.items())[:15]:
        print(f"{c:5d}  {p}")

    if not events:
        raise SystemExit("STOP: schema-based discovery still found 0 event rows")

    items=sorted(events.items(),key=lambda kv:(kv[0][0],kv[0][2],kv[0][1]))
    validated=[]
    b_count=plus20_count=classified_count=rs_count=0

    for _,(event,source) in items:
        d=event["session_date"]
        if d not in underlying or d not in futures: continue
        u=underlying[d]; fut=futures[d]
        base=terminal_for_event(event,u)
        if base is None: continue
        b_count += 1
        entry=base["entry_close"]; terminal=base["terminal_timestamp"]

        p20=find_plus20(event,u,terminal,entry)
        if not p20: continue
        plus20_count += 1

        cls=classify_runner(event,p20,u,fut,entry,terminal)
        if cls is None: continue
        classified_count += 1
        if not cls["runner_strengthening"]: continue
        rs_count += 1

        degraded=first_degraded(event,cls["classification_timestamp"],u,fut,entry,terminal)
        exit_ts=None; exit_type="FALLBACK_BASELINE"

        if degraded:
            attempts=failed_recovery_attempts(degraded,event,u,entry,terminal)
            primary=v35_primary(degraded,attempts)
            if primary and primary in u and primary<terminal:
                exit_ts=primary; exit_type="V35_PRIMARY"
            else:
                rec=first_recovery(degraded,event,u,entry,terminal)
                if rec:
                    rescue=v38_rescue(rec,event,u,entry,terminal)
                    if rescue:
                        exit_ts=rescue["timestamp"]; exit_type="V38_CAP50_RESCUE"

        if exit_ts:
            points=directional(event["direction"],entry,u[exit_ts]["close"])
            later=later_new_mfe(event,u,entry,exit_ts,terminal)
        else:
            points=base["baseline_points"]; later=None

        row={
            "session_date":d,"direction":event["direction"],
            "entry_timestamp":event["entry_timestamp"],"event_source":source,
            "plus20_timestamp":p20,
            "classification_timestamp":cls["classification_timestamp"],
            "net_progress_10m":cls["net_progress_10m"],
            "directional_vwap_change_10m":cls["directional_vwap_change_10m"],
            "degraded_timestamp":degraded["degraded_timestamp"] if degraded else None,
            "exit_type":exit_type,"exit_timestamp":exit_ts,
            "baseline_terminal_type":base["terminal_type"],
            "baseline_terminal_timestamp":terminal,
            "baseline_points":base["baseline_points"],
            "v38_points":points,
            "delta_vs_baseline":points-base["baseline_points"],
            "later_new_mfe":later,
        }

        for m in MILESTONES:
            mt=milestone_timestamp(event,u,entry,terminal,m)
            row[f"plus{m}_timestamp"]=mt
            row[f"reached_plus{m}"]=mt is not None
            row[f"exit_before_plus{m}"]=bool(exit_ts and mt and exit_ts<mt)
        validated.append(row)

    if not validated:
        raise SystemExit("STOP: no RUNNER_STRENGTHENING events reconstructed")

    bvals=[r["baseline_points"] for r in validated]
    vvals=[r["v38_points"] for r in validated]
    bs=stats(bvals); vs=stats(vvals); ds=stats([v-b for v,b in zip(vvals,bvals)])

    primary=sum(r["exit_type"]=="V35_PRIMARY" for r in validated)
    rescue=sum(r["exit_type"]=="V38_CAP50_RESCUE" for r in validated)
    fallback=len(validated)-primary-rescue
    exits=[r for r in validated if r["exit_timestamp"]]
    later=sum(r["later_new_mfe"] is True for r in exits)

    preservation={}
    for m in MILESTONES:
        reached=[r for r in validated if r[f"reached_plus{m}"]]
        cut=[r for r in reached if r[f"exit_before_plus{m}"]]
        preserved=len(reached)-len(cut)
        preservation[m]={"reached":len(reached),"preserved":preserved,
                         "rate":preserved/len(reached) if reached else None}

    lines=[
        "B FAMILY — V40.1 FROZEN V38_CAP50 HISTORICAL VALIDATION",
        "="*118,
        f"validation_range={START_DATE}..{END_DATE}",
        f"dual_raw_sessions={len(session_dates)}",
        f"B/event-like rows accepted={b_count}",
        f"events_reaching_plus20={plus20_count}",
        f"events_with_complete_V20_classifier={classified_count}",
        f"RUNNER_STRENGTHENING_events={rs_count}",
        f"validated_policy_events={len(validated)}",
        "",
        "HISTORICAL VALIDATION SCORECARD",
        "-"*118,
        f"BASELINE total={fmt(bs['total'])} mean={fmt(bs['mean'])} median={fmt(bs['median'])} "
        f"worst={fmt(bs['min'])} best={fmt(bs['max'])} maxDD={fmt(max_drawdown(bvals))}",
        f"V38_CAP50 total={fmt(vs['total'])} mean={fmt(vs['mean'])} median={fmt(vs['median'])} "
        f"worst={fmt(vs['min'])} best={fmt(vs['max'])} maxDD={fmt(max_drawdown(vvals))}",
        f"V38 Δ vs baseline total={fmt(ds['total'])} mean={fmt(ds['mean'])} median={fmt(ds['median'])}",
        "",
        "EXIT MIX",
        "-"*118,
        f"V35 primary exits={primary}",
        f"V38 CAP50 rescues={rescue}",
        f"fallbacks={fallback}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-"*118,
    ]

    for m in MILESTONES:
        p=preservation[m]
        if p["rate"] is None:
            lines.append(f"+{m}: no qualifying runners")
        else:
            lines.append(f"+{m}: {p['preserved']}/{p['reached']} ({p['rate']*100:.1f}%)")

    lines += [
        f"later new MFE after actual exit: {later}/{len(exits)}",
        "",
        "DEVELOPMENT REFERENCE",
        "-"*118,
        f"V38_CAP50 development total on 18 tuned events={fmt(DEV_V38_TOTAL)}",
        "",
        "INTERPRETATION GUARDS",
        "-"*118,
        "- V40.1 changes ONLY event discovery; V38_CAP50 strategy logic remains frozen.",
        "- No parameter tuning grid is performed.",
        "- This block is date-separated from V38 tuning but not globally pristine.",
        "- Treat as historical validation/stress evidence.",
        "- Forward validation beginning 2026-09-29 remains the strongest untouched check.",
        "- Underlying NIFTY directional points only.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(EVENTS_CSV,validated)
    write_csv(SCORECARD_CSV,[score_row("STRUCTURAL_OR_SESSION_CUTOFF",bvals),
                             score_row("FROZEN_V38_CAP50",vvals,bvals)])
    REPORT_JSON.write_text(json.dumps({
        "version":"V40.1","range":{"start":START_DATE,"end":END_DATE},
        "dual_raw_sessions":len(session_dates),"discovered_event_keys":len(events),
        "b_event_rows":b_count,"plus20_events":plus20_count,
        "classified_events":classified_count,"runner_strengthening_events":rs_count,
        "validated_events":len(validated),
        "scorecard":{"baseline":stats(bvals),"v38":stats(vvals),"delta":ds},
        "exit_mix":{"primary":primary,"rescue":rescue,"fallback":fallback},
        "preservation":preservation,"later_new_mfe":later,
        "methodology":{"strategy_logic_changed":False,"event_discovery_changed":True,
                       "tuning_grid":False}
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
