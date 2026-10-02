#!/usr/bin/env python3
"""
B FAMILY — V33 RECOVERY ATTEMPT SEQUENCE DIAGNOSTIC

Purpose
-------
Study the causal sequence of recovery attempts inside DEGRADED runner states.

Inputs
------
V32 outputs:
- degraded-state-population-v32.csv
- recovery-attempts-v32.csv

Question
--------
Do FAILED_RECOVERY paths show a recognizable sequence of repeated attempts
that stop improving or become weaker before structural invalidation?

Measures by attempt number:
- recovery gain
- gap to episode-start target at peak
- improvement vs previous attempt
- time since previous attempt peak
- minutes from degraded state to attempt peak
- whether attempt is stronger/weaker/equal vs previous attempt

Also summarizes:
- first attempt quality
- second attempt quality
- consecutive weakening streaks
- best attempt reached before resolution
- whether failed paths contain 2+ weakening attempts in sequence

Descriptive only.
No threshold selection.
No exit rule.
Family-B and V20 remain frozen.
V29 remains rejected as an exit.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1")
V32_DIR = ROOT / "b-family-degraded-state-population-v32"

PATHS_CSV = V32_DIR / "degraded-state-population-v32.csv"
ATTEMPTS_CSV = V32_DIR / "recovery-attempts-v32.csv"

OUTDIR = ROOT / "b-family-recovery-attempt-sequence-v33"
SEQUENCE_CSV = OUTDIR / "recovery-attempt-sequences-v33.csv"
ATTEMPT_POS_CSV = OUTDIR / "attempt-position-summary-v33.csv"
REPORT_JSON = OUTDIR / "report-v33.json"
SUMMARY_TXT = OUTDIR / "summary-v33.txt"


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing input: {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in (None, ""):
        return None
    return float(v)


def i(v):
    if v in (None, ""):
        return None
    return int(float(v))


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return

    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)

    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def path_key(r):
    return (r["session_date"], r["direction"], r["entry_timestamp"])


def classify_attempt_sequence(attempts):
    """
    Build purely descriptive sequence statistics.
    No thresholds beyond sign of improvement are introduced.
    """
    attempts = sorted(attempts, key=lambda x: i(x["attempt_number"]) or 0)

    if not attempts:
        return {
            "attempt_count": 0,
            "first_gap": None,
            "second_gap": None,
            "first_gain": None,
            "second_gain": None,
            "improving_transitions": 0,
            "weakening_transitions": 0,
            "equal_transitions": 0,
            "longest_weakening_streak": 0,
            "longest_improving_streak": 0,
            "final_gap": None,
            "best_gap": None,
            "worst_gap": None,
            "final_gain": None,
            "best_gain": None,
        }

    improving = 0
    weakening = 0
    equal = 0

    weak_streak = 0
    imp_streak = 0
    max_weak_streak = 0
    max_imp_streak = 0

    for a in attempts:
        delta = f(a.get("gap_improvement_vs_prior_attempt"))
        if delta is None:
            continue

        if delta > 0:
            improving += 1
            imp_streak += 1
            weak_streak = 0
            max_imp_streak = max(max_imp_streak, imp_streak)
        elif delta < 0:
            weakening += 1
            weak_streak += 1
            imp_streak = 0
            max_weak_streak = max(max_weak_streak, weak_streak)
        else:
            equal += 1
            weak_streak = 0
            imp_streak = 0

    gaps = [f(a["gap_to_target_at_peak"]) for a in attempts]
    gaps = [x for x in gaps if x is not None]

    gains = [f(a["recovery_gain"]) for a in attempts]
    gains = [x for x in gains if x is not None]

    return {
        "attempt_count": len(attempts),
        "first_gap": f(attempts[0].get("gap_to_target_at_peak")),
        "second_gap": (
            f(attempts[1].get("gap_to_target_at_peak"))
            if len(attempts) >= 2 else None
        ),
        "first_gain": f(attempts[0].get("recovery_gain")),
        "second_gain": (
            f(attempts[1].get("recovery_gain"))
            if len(attempts) >= 2 else None
        ),
        "improving_transitions": improving,
        "weakening_transitions": weakening,
        "equal_transitions": equal,
        "longest_weakening_streak": max_weak_streak,
        "longest_improving_streak": max_imp_streak,
        "final_gap": f(attempts[-1].get("gap_to_target_at_peak")),
        "best_gap": min(gaps) if gaps else None,
        "worst_gap": max(gaps) if gaps else None,
        "final_gain": f(attempts[-1].get("recovery_gain")),
        "best_gain": max(gains) if gains else None,
    }


def main():
    print("B FAMILY — V33 RECOVERY ATTEMPT SEQUENCE DIAGNOSTIC")
    print("=" * 118)

    paths = load_csv(PATHS_CSV)
    attempts = load_csv(ATTEMPTS_CSV)

    if not paths:
        raise SystemExit("STOP: no V32 degraded paths found")

    by_path = defaultdict(list)
    for a in attempts:
        key = (a["session_date"], a["direction"], a["entry_timestamp"])
        by_path[key].append(a)

    sequence_rows = []

    for p in paths:
        key = path_key(p)
        aa = by_path.get(key, [])
        seq = classify_attempt_sequence(aa)

        row = {
            "session_date": p["session_date"],
            "direction": p["direction"],
            "entry_timestamp": p["entry_timestamp"],
            "block": p.get("block"),
            "resolution": p["resolution"],
            "degraded_duration_minutes": f(p.get("degraded_duration_minutes")),
            "worst_damage_points": f(p.get("worst_damage_points")),
            "worst_damage_fraction": f(p.get("worst_damage_fraction")),
            "recovery_attempt_count_v32": i(p.get("recovery_attempt_count")),
            **seq,
        }

        sequence_rows.append(row)

    recovered = [r for r in sequence_rows if r["resolution"] == "RECOVERED"]
    failed = [r for r in sequence_rows if r["resolution"] == "FAILED_RECOVERY"]

    # Attempt-position summaries.
    position_rows = []
    max_pos = max(
        [i(a["attempt_number"]) or 0 for a in attempts],
        default=0,
    )

    for pos in range(1, max_pos + 1):
        for outcome in ("RECOVERED", "FAILED_RECOVERY"):
            subset = [
                a for a in attempts
                if (i(a["attempt_number"]) == pos)
                and (
                    next(
                        (
                            p["resolution"]
                            for p in paths
                            if path_key(p) == (
                                a["session_date"],
                                a["direction"],
                                a["entry_timestamp"],
                            )
                        ),
                        None,
                    ) == outcome
                )
            ]

            if not subset:
                continue

            position_rows.append({
                "attempt_number": pos,
                "resolution": outcome,
                "n": len(subset),
                "gap_median": stats(
                    f(a["gap_to_target_at_peak"]) for a in subset
                )["median"],
                "gap_mean": stats(
                    f(a["gap_to_target_at_peak"]) for a in subset
                )["mean"],
                "gain_median": stats(
                    f(a["recovery_gain"]) for a in subset
                )["median"],
                "gain_mean": stats(
                    f(a["recovery_gain"]) for a in subset
                )["mean"],
                "minutes_from_degraded_median": stats(
                    f(a["minutes_from_degraded_to_peak"]) for a in subset
                )["median"],
                "spacing_from_prior_peak_median": stats(
                    f(a["minutes_since_prior_attempt_peak"]) for a in subset
                )["median"],
                "gap_improvement_vs_prior_median": stats(
                    f(a["gap_improvement_vs_prior_attempt"]) for a in subset
                )["median"],
            })

    # Overall descriptive comparison.
    lines = [
        "B FAMILY — V33 RECOVERY ATTEMPT SEQUENCE DIAGNOSTIC",
        "=" * 118,
        f"degraded_paths={len(sequence_rows)}",
        f"recovered_paths={len(recovered)}",
        f"failed_recovery_paths={len(failed)}",
        f"total_recovery_attempt_rows={len(attempts)}",
        "",
        "PATH-LEVEL ATTEMPT SEQUENCE COMPARISON",
        "-" * 118,
    ]

    for label, rows in (("RECOVERED", recovered), ("FAILED_RECOVERY", failed)):
        attempt_count = stats(r["attempt_count"] for r in rows)
        weak = stats(r["weakening_transitions"] for r in rows)
        imp = stats(r["improving_transitions"] for r in rows)
        weak_streak = stats(r["longest_weakening_streak"] for r in rows)
        best_gap = stats(r["best_gap"] for r in rows)
        final_gap = stats(r["final_gap"] for r in rows)

        lines.append(
            f"{label}: n={len(rows)} "
            f"attempts_med={fmt(attempt_count['median'])} "
            f"weakTransitions_med={fmt(weak['median'])} "
            f"improvingTransitions_med={fmt(imp['median'])} "
            f"longestWeakStreak_med={fmt(weak_streak['median'])} "
            f"bestGap_med={fmt(best_gap['median'])} "
            f"finalGap_med={fmt(final_gap['median'])}"
        )

    lines += [
        "",
        "FAILED-RECOVERY PATH DETAILS",
        "-" * 118,
    ]

    for r in failed:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"attempts={r['attempt_count']} "
            f"improving={r['improving_transitions']} "
            f"weakening={r['weakening_transitions']} "
            f"longestWeakStreak={r['longest_weakening_streak']} "
            f"firstGap={fmt(r['first_gap'])} "
            f"secondGap={fmt(r['second_gap'])} "
            f"bestGap={fmt(r['best_gap'])} "
            f"finalGap={fmt(r['final_gap'])}"
        )

    lines += [
        "",
        "RECOVERED PATHS WITH MULTIPLE ATTEMPTS",
        "-" * 118,
    ]

    for r in recovered:
        if r["attempt_count"] >= 2:
            lines.append(
                f"{r['session_date']} {r['direction']} "
                f"attempts={r['attempt_count']} "
                f"improving={r['improving_transitions']} "
                f"weakening={r['weakening_transitions']} "
                f"longestWeakStreak={r['longest_weakening_streak']} "
                f"firstGap={fmt(r['first_gap'])} "
                f"secondGap={fmt(r['second_gap'])} "
                f"bestGap={fmt(r['best_gap'])} "
                f"finalGap={fmt(r['final_gap'])}"
            )

    # Sign-only descriptive counts, no threshold creation.
    fail_two_plus_weak = sum(
        r["longest_weakening_streak"] >= 2 for r in failed
    )
    rec_two_plus_weak = sum(
        r["longest_weakening_streak"] >= 2 for r in recovered
    )

    lines += [
        "",
        "SIGN-ONLY SEQUENCE COUNTS",
        "-" * 118,
        f"FAILED paths with >=2 consecutive weakening transitions: "
        f"{fail_two_plus_weak}/{len(failed)}",
        f"RECOVERED paths with >=2 consecutive weakening transitions: "
        f"{rec_two_plus_weak}/{len(recovered)}",
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Descriptive attempt-sequence study only.",
        "- No attempt-count threshold selected.",
        "- No weakening-streak threshold selected.",
        "- No damage/duration threshold selected.",
        "- No exit rule defined.",
        "- Family-B remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- V29 remains rejected as an exit.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_RECOVERY_ATTEMPT_SEQUENCE_V33",
        "degraded_path_count": len(sequence_rows),
        "recovered_path_count": len(recovered),
        "failed_recovery_path_count": len(failed),
        "recovery_attempt_row_count": len(attempts),
        "sequence_rows": sequence_rows,
        "attempt_position_summary": position_rows,
        "sign_only_counts": {
            "failed_with_2plus_consecutive_weakening": fail_two_plus_weak,
            "recovered_with_2plus_consecutive_weakening": rec_two_plus_weak,
        },
        "guards": {
            "threshold_search": False,
            "exit_rule_defined": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "v29_status": "REJECTED_AS_EXIT",
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(SEQUENCE_CSV, sequence_rows)
    write_csv(ATTEMPT_POS_CSV, position_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("SEQUENCE CSV :", SEQUENCE_CSV)
    print("POSITION CSV :", ATTEMPT_POS_CSV)
    print("REPORT JSON  :", REPORT_JSON)
    print("SUMMARY      :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
