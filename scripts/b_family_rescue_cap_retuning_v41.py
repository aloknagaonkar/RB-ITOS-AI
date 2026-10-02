#!/usr/bin/env python3
"""
B FAMILY — V41 43-EVENT RESCUE CONTRIBUTION + CAP RETUNING

Purpose
-------
V40.1 showed that frozen V38_CAP50 does NOT beat the common baseline on the
larger 43 RUNNER_STRENGTHENING population:

    baseline   +2416.05
    V38_CAP50  +2091.80
    delta      -324.25

However, risk improved materially:

    maxDD baseline  -156.20
    maxDD V38        -48.70

The most suspicious component is the rescue layer:
    V35 primary exits = 7
    V38 CAP50 rescues = 28
    fallbacks          = 8
    later new MFE      = 23/35

V41 therefore isolates the rescue contribution and retunes ONLY the rescue cap
on the same 43-event historical-validation population.

IMPORTANT:
- V35 primary logic remains fixed.
- Recovery/rebreak structure remains fixed.
- Only rescue cap is varied.
- This is now DEVELOPMENT/TUNING on the 43-event population, not validation.
- Untouched forward validation beginning 2026-09-29 remains reserved.

Candidates
----------
NO_RESCUE
CAP0
CAP10
CAP20
CAP30
CAP40
CAP50
CAP60
CAP75
CAP100

If rescue is disabled or rejected:
    fall back to STRUCTURAL_OR_SESSION_CUTOFF.

Outputs
-------
- total / mean / median / worst / best / maxDD
- delta vs baseline
- delta vs frozen V38_CAP50
- primary / rescue / fallback counts
- rescue-only contribution
- +30/+40/+50/+75/+100 chase preservation
- later-new-MFE after exits
- per-exit-type point contribution

Underlying NIFTY directional points only.
"""

from __future__ import annotations

import csv, json
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

V40_EVENTS = (
    RESEARCH / "b-family-v38-cap50-validation-v40_1"
    / "validated-runner-events-v40_1.csv"
)

OUTDIR = RESEARCH / "b-family-rescue-cap-retuning-v41"
LEADERBOARD = OUTDIR / "candidate-leaderboard-v41.csv"
EVENTS = OUTDIR / "candidate-event-results-v41.csv"
REPORT = OUTDIR / "report-v41.json"
SUMMARY = OUTDIR / "summary-v41.txt"

CAPS = (None, 0, 10, 20, 30, 40, 50, 60, 75, 100)
MILESTONES = (30, 40, 50, 75, 100)


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("", None) else float(v)


def b(v):
    return str(v).strip().lower() == "true"


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
        path.write_text(""); return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def reconstruct_candidate_row(src, cap):
    """
    V40.1 already contains the frozen V38_CAP50 result, but not alternative
    rescue exits. Therefore V41 uses the event's V40.1 row only to isolate
    contribution where possible.

    To retune caps correctly, we require a precomputed rescue candidate move.
    If V40.1 row was a V38_CAP50_RESCUE, then v38_points is the rescue move.
    For rows not rescued at CAP50, a higher cap cannot be reconstructed safely
    from V40.1 alone. Hence:
      - caps <=50 are fully evaluable from V40.1 rows
      - caps >50 are diagnostic lower-bound only and are marked incomplete
    """
    baseline = f(src["baseline_points"])
    frozen = f(src["v38_points"])
    exit_type = src["exit_type"]

    # Primary exits are fixed for all candidates.
    if exit_type == "V35_PRIMARY":
        points = frozen
        ctype = "V35_PRIMARY"
        actual_exit = True
        complete = True

    elif exit_type == "V38_CAP50_RESCUE":
        rescue_move = frozen
        if cap is None:
            points = baseline
            ctype = "FALLBACK_BASELINE"
            actual_exit = False
        elif rescue_move <= cap:
            points = rescue_move
            ctype = "RESCUE"
            actual_exit = True
        else:
            points = baseline
            ctype = "FALLBACK_BASELINE"
            actual_exit = False
        complete = True

    else:
        # No rescue under CAP50. For cap<=50, this means no rescue candidate
        # qualified, so result is complete. For cap>50, there may have been a
        # skipped >50 rescue that V40.1 did not retain.
        points = baseline
        ctype = "FALLBACK_BASELINE"
        actual_exit = False
        complete = (cap is None or cap <= 50)

    return points, ctype, actual_exit, complete


def main():
    print("B FAMILY — V41 43-EVENT RESCUE CONTRIBUTION + CAP RETUNING")
    print("="*118)

    rows = load_csv(V40_EVENTS)
    if len(rows) != 43:
        raise SystemExit(f"STOP: expected 43 V40.1 events, got {len(rows)}")

    baseline_total = sum(f(r["baseline_points"]) for r in rows)
    frozen_total = sum(f(r["v38_points"]) for r in rows)

    leaders=[]
    all_events=[]

    for cap in CAPS:
        name = "V41_NO_RESCUE" if cap is None else f"V41_CAP{cap}"

        out=[]
        incomplete=0

        for src in rows:
            points, ctype, actual, complete = reconstruct_candidate_row(src, cap)
            if not complete:
                incomplete += 1

            r = {
                "candidate": name,
                "session_date": src["session_date"],
                "direction": src["direction"],
                "entry_timestamp": src["entry_timestamp"],
                "candidate_exit_type": ctype,
                "points": points,
                "baseline_points": f(src["baseline_points"]),
                "delta_vs_baseline": points - f(src["baseline_points"]),
                "source_v40_exit_type": src["exit_type"],
                "source_v40_points": f(src["v38_points"]),
                "complete_for_cap": complete,
                "later_new_mfe_source": src.get("later_new_mfe"),
            }

            for m in MILESTONES:
                reached = b(src.get(f"reached_plus{m}"))
                exit_before = b(src.get(f"exit_before_plus{m}"))

                # If we fall back, milestone is preserved if baseline lifecycle
                # reached it. If actual candidate exit matches source rescue/
                # primary, source exit-before relation applies.
                r[f"reached_plus{m}"] = reached
                r[f"exit_before_plus{m}"] = (
                    exit_before if actual and ctype != "FALLBACK_BASELINE"
                    else False
                )

            out.append(r)

        vals=[r["points"] for r in out]
        bvals=[r["baseline_points"] for r in out]
        s=stats(vals)
        ds=stats([v-bv for v,bv in zip(vals,bvals)])

        primary=[r for r in out if r["candidate_exit_type"]=="V35_PRIMARY"]
        rescue=[r for r in out if r["candidate_exit_type"]=="RESCUE"]
        fallback=[r for r in out if r["candidate_exit_type"]=="FALLBACK_BASELINE"]

        rescue_delta = stats(
            r["points"] - r["baseline_points"] for r in rescue
        )

        sm = {
            "candidate": name,
            "cap": cap,
            "complete": incomplete == 0,
            "incomplete_event_count": incomplete,
            "events": len(out),
            "primary_exits": len(primary),
            "rescue_exits": len(rescue),
            "fallbacks": len(fallback),
            "total_points": s["total"],
            "mean_points": s["mean"],
            "median_points": s["median"],
            "worst_points": s["min"],
            "best_points": s["max"],
            "max_drawdown_points": maxdd(vals),
            "delta_vs_baseline_total": ds["total"],
            "delta_vs_frozen_v38_total": s["total"] - frozen_total,
            "rescue_delta_vs_baseline_total": rescue_delta["total"],
            "rescue_delta_vs_baseline_mean": rescue_delta["mean"],
        }

        for m in MILESTONES:
            reached=[r for r in out if r[f"reached_plus{m}"]]
            cut=[r for r in reached if r[f"exit_before_plus{m}"]]
            preserved=len(reached)-len(cut)
            sm[f"plus{m}_reached"]=len(reached)
            sm[f"plus{m}_preserved"]=preserved
            sm[f"plus{m}_rate"]=preserved/len(reached) if reached else None

        leaders.append(sm)
        all_events.extend(out)

        completeness = "COMPLETE" if sm["complete"] else f"INCOMPLETE({incomplete})"
        print(
            f"{name:<15} {completeness:<14} "
            f"total={fmt(sm['total_points'])} "
            f"Δbase={fmt(sm['delta_vs_baseline_total'])} "
            f"ΔV38={fmt(sm['delta_vs_frozen_v38_total'])} "
            f"DD={fmt(sm['max_drawdown_points'])} "
            f"P={sm['primary_exits']} R={sm['rescue_exits']} "
            f"+50={sm['plus50_preserved']}/{sm['plus50_reached']} "
            f"+75={sm['plus75_preserved']}/{sm['plus75_reached']} "
            f"+100={sm['plus100_preserved']}/{sm['plus100_reached']}"
        )

    complete_leaders=[r for r in leaders if r["complete"]]
    complete_leaders.sort(
        key=lambda r:(r["total_points"],r["max_drawdown_points"]),
        reverse=True,
    )
    for idx,r in enumerate(complete_leaders,1):
        r["rank_complete_candidates"]=idx

    winner=complete_leaders[0]

    lines=[
        "B FAMILY — V41 43-EVENT RESCUE CONTRIBUTION + CAP RETUNING",
        "="*118,
        f"events={len(rows)}",
        f"baseline_total={fmt(baseline_total)}",
        f"frozen_V38_CAP50_total={fmt(frozen_total)}",
        "",
        "COMPLETE CANDIDATES (CAP <= 50 OR NO RESCUE)",
        "-"*118,
    ]

    for r in complete_leaders:
        lines.append(
            f"#{r['rank_complete_candidates']:02d} {r['candidate']} "
            f"total={fmt(r['total_points'])} "
            f"Δbase={fmt(r['delta_vs_baseline_total'])} "
            f"ΔV38={fmt(r['delta_vs_frozen_v38_total'])} "
            f"mean={fmt(r['mean_points'])} median={fmt(r['median_points'])} "
            f"worst={fmt(r['worst_points'])} maxDD={fmt(r['max_drawdown_points'])} "
            f"P={r['primary_exits']} R={r['rescue_exits']} "
            f"rescueΔ={fmt(r['rescue_delta_vs_baseline_total'])}"
        )

    lines += [
        "",
        "WINNER — COMPLETE CANDIDATES ONLY",
        "-"*118,
        f"candidate={winner['candidate']}",
        f"total={fmt(winner['total_points'])}",
        f"Δ vs baseline={fmt(winner['delta_vs_baseline_total'])}",
        f"Δ vs frozen V38_CAP50={fmt(winner['delta_vs_frozen_v38_total'])}",
        f"mean={fmt(winner['mean_points'])}",
        f"median={fmt(winner['median_points'])}",
        f"worst={fmt(winner['worst_points'])}",
        f"best={fmt(winner['best_points'])}",
        f"maxDD={fmt(winner['max_drawdown_points'])}",
        f"primary exits={winner['primary_exits']} rescue exits={winner['rescue_exits']} "
        f"fallbacks={winner['fallbacks']}",
        f"rescue contribution vs baseline total={fmt(winner['rescue_delta_vs_baseline_total'])}",
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
        "",
        "INTERPRETATION",
        "-"*118,
        "- V41 is tuning on the 43-event V40.1 population.",
        "- The key question is whether CAP50 rescue added or destroyed points versus fallback baseline.",
        "- Caps >50 are marked incomplete because V40.1 did not retain skipped >50 rescue candidates.",
        "- If a lower cap or NO_RESCUE beats CAP50, that becomes the next candidate to reconstruct exactly.",
        "- Forward validation from 2026-09-29 remains untouched.",
    ]

    OUTDIR.mkdir(parents=True,exist_ok=True)
    write_csv(LEADERBOARD,leaders)
    write_csv(EVENTS,all_events)
    REPORT.write_text(json.dumps({
        "version":"V41",
        "events":len(rows),
        "baseline_total":baseline_total,
        "frozen_v38_total":frozen_total,
        "winner_complete":winner,
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
