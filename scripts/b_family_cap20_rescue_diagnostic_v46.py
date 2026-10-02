#!/usr/bin/env python3
"""
B FAMILY — V46 CAP20 RESCUE CROSS-BLOCK DIAGNOSTIC

Purpose
-------
Study every actual CAP20 rescue from the three frozen historical blocks:

V43: 2025-07-17..2025-12-11
V44: 2025-02-06..2025-07-16
V45: 2024-08-16..2025-02-05

No tuning.
No rule changes.

Questions answered
------------------
- How many CAP20 rescues fired?
- How much total point contribution did rescues add/remove vs baseline?
- How many rescues later made a new MFE?
- Were those later-new-MFE rescues still net beneficial vs baseline?
- Which milestones (+30/+40/+50/+75/+100) were cut before they were reached?
- Which individual rescue events helped and which hurt?

This is a decomposition/diagnostic only.
"""

from __future__ import annotations
import csv, json
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

SOURCES = [
    (
        "V43",
        RESEARCH / "b-family-dual-candidate-validation-v43"
        / "dual-candidate-events-v43.csv",
    ),
    (
        "V44",
        RESEARCH / "b-family-dual-candidate-validation-v44"
        / "dual-candidate-events-v44.csv",
    ),
    (
        "V45",
        RESEARCH / "b-family-primary-off-cap20-validation-v45"
        / "events-v45.csv",
    ),
]

OUTDIR = RESEARCH / "b-family-cap20-rescue-diagnostic-v46"
EVENTS = OUTDIR / "cap20-rescue-events-v46.csv"
REPORT = OUTDIR / "report-v46.json"
SUMMARY = OUTDIR / "summary-v46.txt"

MILESTONES = (30,40,50,75,100)


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("",None) else float(v)


def b(v):
    return str(v).strip().lower() == "true"


def stats(vals):
    xs=[float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0,total=None,mean=None,median=None,min=None,max=None)
    return dict(
        n=len(xs), total=sum(xs), mean=mean(xs), median=median(xs),
        min=min(xs), max=max(xs)
    )


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


def normalize(block,row):
    if block in ("V43","V44"):
        exit_type=row.get("candidate_b_exit_type")
        exit_ts=row.get("candidate_b_exit_timestamp")
        points=f(row.get("candidate_b_points"))
        baseline=f(row.get("baseline_points"))
        later=b(row.get("candidate_b_later_new_mfe"))
        rescue=(exit_type=="CAP20_RESCUE")
        rec={
            "block":block,
            "session_date":row.get("session_date"),
            "direction":row.get("direction"),
            "entry_timestamp":row.get("entry_timestamp"),
            "exit_type":exit_type,
            "exit_timestamp":exit_ts,
            "candidate_points":points,
            "baseline_points":baseline,
            "delta_vs_baseline":None if points is None or baseline is None else points-baseline,
            "later_new_mfe":later,
        }
        for m in MILESTONES:
            rec[f"reached_plus{m}"]=b(row.get(f"reached_plus{m}"))
            rec[f"exit_before_plus{m}"]=b(row.get(f"b_exit_before_plus{m}"))
        return rec if rescue else None

    # V45
    exit_type=row.get("candidate_exit_type")
    if exit_type!="CAP20_RESCUE":
        return None

    points=f(row.get("candidate_points"))
    baseline=f(row.get("baseline_points"))

    rec={
        "block":block,
        "session_date":row.get("session_date"),
        "direction":row.get("direction"),
        "entry_timestamp":row.get("entry_timestamp"),
        "exit_type":exit_type,
        "exit_timestamp":row.get("candidate_exit_timestamp"),
        "candidate_points":points,
        "baseline_points":baseline,
        "delta_vs_baseline":None if points is None or baseline is None else points-baseline,
        "later_new_mfe":b(row.get("later_new_mfe")),
    }
    for m in MILESTONES:
        rec[f"reached_plus{m}"]=b(row.get(f"reached_plus{m}"))
        rec[f"exit_before_plus{m}"]=b(row.get(f"exit_before_plus{m}"))
    return rec


def main():
    print("B FAMILY — V46 CAP20 RESCUE CROSS-BLOCK DIAGNOSTIC")
    print("="*118)

    rescues=[]
    block_counts={}

    for block,path in SOURCES:
        rows=load_csv(path)
        count=0
        for row in rows:
            rec=normalize(block,row)
            if rec:
                rescues.append(rec)
                count += 1
        block_counts[block]=count
        print(f"{block}: rescue_events={count}")

    if not rescues:
        raise SystemExit("STOP: no CAP20 rescue events found")

    deltas=[r["delta_vs_baseline"] for r in rescues]
    ds=stats(deltas)

    later=[r for r in rescues if r["later_new_mfe"]]
    no_later=[r for r in rescues if not r["later_new_mfe"]]

    later_ds=stats(r["delta_vs_baseline"] for r in later)
    no_later_ds=stats(r["delta_vs_baseline"] for r in no_later)

    beneficial=[r for r in rescues if r["delta_vs_baseline"] is not None and r["delta_vs_baseline"]>0]
    harmful=[r for r in rescues if r["delta_vs_baseline"] is not None and r["delta_vs_baseline"]<0]
    flat=[r for r in rescues if r["delta_vs_baseline"]==0]

    milestone_cut={}
    for m in MILESTONES:
        reached=[r for r in rescues if r[f"reached_plus{m}"]]
        cut=[r for r in reached if r[f"exit_before_plus{m}"]]
        milestone_cut[m]={
            "reached":len(reached),
            "cut_before":len(cut),
            "preserved":len(reached)-len(cut),
        }

    lines=[
        "B FAMILY — V46 CAP20 RESCUE CROSS-BLOCK DIAGNOSTIC",
        "="*118,
        f"total_rescues={len(rescues)}",
        f"by_block={block_counts}",
        "",
        "POINT CONTRIBUTION",
        "-"*118,
        f"total rescue contribution vs baseline={fmt(ds['total'])}",
        f"mean rescue contribution={fmt(ds['mean'])}",
        f"median rescue contribution={fmt(ds['median'])}",
        f"best rescue contribution={fmt(ds['max'])}",
        f"worst rescue contribution={fmt(ds['min'])}",
        f"beneficial rescues={len(beneficial)}",
        f"harmful rescues={len(harmful)}",
        f"flat rescues={len(flat)}",
        "",
        "LATER NEW MFE",
        "-"*118,
        f"later_new_mfe={len(later)}/{len(rescues)}",
        f"later-new-MFE rescue contribution total={fmt(later_ds['total'])}",
        f"later-new-MFE rescue contribution mean={fmt(later_ds['mean'])}",
        f"no-later-MFE rescue contribution total={fmt(no_later_ds['total'])}",
        f"no-later-MFE rescue contribution mean={fmt(no_later_ds['mean'])}",
        "",
        "MILESTONE IMPACT",
        "-"*118,
    ]

    for m in MILESTONES:
        x=milestone_cut[m]
        lines.append(
            f"+{m}: reached={x['reached']} cut_before={x['cut_before']} "
            f"preserved={x['preserved']}"
        )

    lines += [
        "",
        "PER-RESCUE EVENTS",
        "-"*118,
    ]

    rescues.sort(key=lambda r:(r["session_date"],r["entry_timestamp"] or ""))

    for r in rescues:
        cuts=[
            f"+{m}" for m in MILESTONES
            if r[f"reached_plus{m}"] and r[f"exit_before_plus{m}"]
        ]
        lines.append(
            f"{r['block']} {r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp']} exit={r['exit_timestamp']} "
            f"points={fmt(r['candidate_points'])} "
            f"baseline={fmt(r['baseline_points'])} "
            f"Δ={fmt(r['delta_vs_baseline'])} "
            f"laterNewMFE={r['later_new_mfe']} "
            f"cutMilestones={','.join(cuts) if cuts else '-'}"
        )

    lines += [
        "",
        "INTERPRETATION GUARD",
        "-"*118,
        "- V46 does not tune CAP20 or change any rule.",
        "- A later new MFE does not automatically mean the rescue was bad; compare its delta vs baseline.",
        "- If later-new-MFE rescues are still net positive, CAP20 may be correctly trading some upside for protection.",
        "- If later-new-MFE rescues are net negative, the next step should study a recovery/re-entry condition rather than simply changing the cap again.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(EVENTS,rescues)
    REPORT.write_text(json.dumps({
        "version":"V46",
        "rescue_count":len(rescues),
        "block_counts":block_counts,
        "delta_stats":ds,
        "later_new_mfe_count":len(later),
        "later_new_mfe_delta_stats":later_ds,
        "no_later_new_mfe_delta_stats":no_later_ds,
        "beneficial_count":len(beneficial),
        "harmful_count":len(harmful),
        "flat_count":len(flat),
        "milestone_impact":milestone_cut,
    },indent=2))
    SUMMARY.write_text("\n".join(lines)+"\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENTS      :",EVENTS)
    print("REPORT JSON :",REPORT)
    print("SUMMARY     :",SUMMARY)

if __name__=="__main__":
    main()
