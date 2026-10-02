#!/usr/bin/env python3
"""
B FAMILY — V34 RECOVERY-ATTEMPT DETERIORATION + POINTS SCORECARD

Purpose
-------
Study what happens AFTER the best recovery attempt inside a DEGRADED runner.

Focus:
- 3 FAILED_RECOVERY paths
- recovered counterexamples with meaningful weakening sequences

Key question:
After a runner has made its best recovery attempt, can temporary weakening be
distinguished from genuine deterioration before structural invalidation?

NEW IN V34: POINT ACCOUNTING
----------------------------
From V34 onward, every candidate/research test should report NIFTY underlying
points alongside structural diagnostics.

For each degraded path this script records:
- directional points at degraded trigger
- running MFE at degraded trigger
- directional points at best recovery-attempt peak
- directional points at terminal resolution
- structural invalidation close points, when available
- lifecycle MFE before structural invalidation
- structural giveback = lifecycle MFE - structural invalidation close move
- resolution giveback = lifecycle MFE - resolution close move
- resolution improvement vs structural = resolution close move -
  structural invalidation close move

IMPORTANT:
RECOVERED is a state transition, NOT an exit. Therefore resolution points for
RECOVERED paths are NOT strategy realized P&L.

All point figures are NIFTY underlying directional points, not CE/PE premium
points and not rupee P&L.

No threshold search.
No new exit rule.
Family-B and V20 remain frozen.
V29 remains rejected as an exit.
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

V32_DIR = RESEARCH / "b-family-degraded-state-population-v32"
PATHS_CSV = V32_DIR / "degraded-state-population-v32.csv"
ATTEMPTS_CSV = V32_DIR / "recovery-attempts-v32.csv"

# Event sources discovered by V32 often contain entry/structural fields.
V29_EVENTS = (
    RESEARCH / "b-family-v29-runner-exit-oos-100" / "b-events-v29.csv"
)

OUTDIR = RESEARCH / "b-family-recovery-deterioration-points-v34"
PATH_CSV = OUTDIR / "post-best-attempt-paths-v34.csv"
POINTS_CSV = OUTDIR / "points-scorecard-v34.csv"
ATTEMPT_CSV = OUTDIR / "post-best-attempt-sequence-v34.csv"
REPORT_JSON = OUTDIR / "report-v34.json"
SUMMARY_TXT = OUTDIR / "summary-v34.txt"


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing input: {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in ("", None):
        return None
    return float(v)


def i(v):
    if v in ("", None):
        return None
    return int(float(v))


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    if not a or not b:
        return None
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def stats(vals):
    xs = [float(x) for x in vals if x not in ("", None)]
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


def key(r):
    return (r["session_date"], r["direction"], r["entry_timestamp"])


def discover_event_rows():
    """
    Discover canonical event rows containing the point-accounting fields.
    Deduplicate by session/direction/entry.
    """
    candidates = []
    if V29_EVENTS.exists():
        candidates.append(V29_EVENTS)

    for p in RESEARCH.rglob("*.csv"):
        n = p.name.lower()
        if ("b-event" in n or n.startswith("b-events")) and p not in candidates:
            candidates.append(p)

    out = {}
    for p in candidates:
        try:
            rows = load_csv(p)
        except Exception:
            continue
        for r in rows:
            if not all(r.get(x) for x in ("session_date", "direction", "entry_timestamp")):
                continue
            k = key(r)
            # Prefer rows that have more structural/point fields.
            score = sum(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close",
                    "structural_peak_mfe",
                    "structural_invalidation_close_move",
                    "structural_invalidation_timestamp",
                    "mfe",
                )
            )
            prior = out.get(k)
            if prior is None or score > prior[0]:
                out[k] = (score, r, str(p))
    return {k: (v[1], v[2]) for k, v in out.items()}


def build_attempt_maps(attempts):
    by = defaultdict(list)
    for a in attempts:
        by[key(a)].append(a)
    for k in by:
        by[k].sort(key=lambda x: i(x.get("attempt_number")) or 0)
    return by


def analyze_sequence(path, attempts):
    """
    Best attempt = smallest causal gap-to-target among failed attempts recorded
    before resolution. Study only later attempts after that best attempt.
    """
    if not attempts:
        return {
            "best_attempt_number": None,
            "best_attempt_peak_timestamp": None,
            "best_attempt_gap": None,
            "best_attempt_peak_move": None,
            "attempts_after_best": 0,
            "improving_after_best": 0,
            "weakening_after_best": 0,
            "longest_weakening_streak_after_best": 0,
            "final_attempt_gap": None,
            "gap_expansion_best_to_final": None,
            "minutes_best_attempt_to_resolution": None,
            "later_better_attempt_after_best": False,
        }, []

    best = min(
        attempts,
        key=lambda a: f(a.get("gap_to_target_at_peak"))
        if f(a.get("gap_to_target_at_peak")) is not None
        else float("inf"),
    )
    best_num = i(best["attempt_number"])
    later = [a for a in attempts if (i(a["attempt_number"]) or 0) > best_num]

    weak = 0
    imp = 0
    streak = 0
    max_streak = 0
    seq_rows = []
    prev_gap = f(best.get("gap_to_target_at_peak"))

    for a in later:
        gap = f(a.get("gap_to_target_at_peak"))
        delta = None if gap is None or prev_gap is None else prev_gap - gap

        state = "EQUAL"
        if delta is not None:
            if delta > 0:
                state = "IMPROVING"
                imp += 1
                streak = 0
            elif delta < 0:
                state = "WEAKENING"
                weak += 1
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        seq_rows.append({
            "session_date": path["session_date"],
            "direction": path["direction"],
            "entry_timestamp": path["entry_timestamp"],
            "resolution": path["resolution"],
            "attempt_number": i(a["attempt_number"]),
            "peak_timestamp": a["peak_timestamp"],
            "peak_move": f(a.get("peak_move")),
            "gap_to_target": gap,
            "gap_change_vs_prior_attempt": delta,
            "state_vs_prior_attempt": state,
            "minutes_from_best_attempt": mins(
                best["peak_timestamp"], a["peak_timestamp"]
            ),
        })
        prev_gap = gap

    final_gap = f(attempts[-1].get("gap_to_target_at_peak"))
    best_gap = f(best.get("gap_to_target_at_peak"))
    expansion = (
        None if final_gap is None or best_gap is None
        else final_gap - best_gap
    )

    return {
        "best_attempt_number": best_num,
        "best_attempt_peak_timestamp": best["peak_timestamp"],
        "best_attempt_gap": best_gap,
        "best_attempt_peak_move": f(best.get("peak_move")),
        "attempts_after_best": len(later),
        "improving_after_best": imp,
        "weakening_after_best": weak,
        "longest_weakening_streak_after_best": max_streak,
        "final_attempt_gap": final_gap,
        "gap_expansion_best_to_final": expansion,
        "minutes_best_attempt_to_resolution": mins(
            best["peak_timestamp"], path.get("terminal_timestamp")
        ),
        "later_better_attempt_after_best": any(
            f(a.get("gap_to_target_at_peak")) is not None
            and best_gap is not None
            and f(a.get("gap_to_target_at_peak")) < best_gap
            for a in later
        ),
    }, seq_rows


def build_points_row(path, ev, ev_source, seq):
    """
    Points are directional NIFTY underlying points from original B entry.
    We intentionally do not call recovered-state points "realized P&L".
    """
    entry_close = f(ev.get("entry_close")) if ev else None

    degraded_move = None
    # V32 target is the close move at first degraded trigger.
    degraded_move = f(path.get("episode_start_directional_close_level"))

    best_attempt_move = seq.get("best_attempt_peak_move")

    # Structural fields may exist in event source.
    structural_mfe = None
    structural_close = None
    if ev:
        structural_mfe = (
            f(ev.get("structural_peak_mfe"))
            if f(ev.get("structural_peak_mfe")) is not None
            else f(ev.get("mfe"))
        )
        structural_close = f(ev.get("structural_invalidation_close_move"))

    # V32 path doesn't always store terminal move. If structural failure,
    # structural close is the terminal directional move. For recovered paths
    # the resolution level is just above the episode-start target; using the
    # exact recovered candle move is unavailable in V32 output, so do not
    # invent it.
    resolution_move = structural_close if path["resolution"] == "FAILED_RECOVERY" else None

    structural_giveback = (
        None if structural_mfe is None or structural_close is None
        else structural_mfe - structural_close
    )
    resolution_giveback = (
        None if structural_mfe is None or resolution_move is None
        else structural_mfe - resolution_move
    )

    return {
        "session_date": path["session_date"],
        "direction": path["direction"],
        "entry_timestamp": path["entry_timestamp"],
        "block": path.get("block"),
        "resolution": path["resolution"],
        "event_source_for_points": ev_source,
        "entry_close": entry_close,
        "degraded_trigger_directional_points": degraded_move,
        "best_recovery_attempt_directional_points": best_attempt_move,
        "structural_lifecycle_mfe_points": structural_mfe,
        "structural_invalidation_close_points": structural_close,
        "structural_giveback_points": structural_giveback,
        "resolution_directional_points": resolution_move,
        "resolution_giveback_points": resolution_giveback,
        "resolution_improvement_vs_structural_points": (
            None
            if resolution_move is None or structural_close is None
            else resolution_move - structural_close
        ),
        "point_accounting_note": (
            "RESEARCH_STATE_ONLY_NOT_REALIZED_PNL"
            if path["resolution"] == "RECOVERED"
            else "STRUCTURAL_FAILURE_BASELINE"
        ),
    }


def main():
    print("B FAMILY — V34 RECOVERY-ATTEMPT DETERIORATION + POINTS SCORECARD")
    print("=" * 118)

    paths = load_csv(PATHS_CSV)
    attempts = load_csv(ATTEMPTS_CSV)
    by_attempt = build_attempt_maps(attempts)
    events = discover_event_rows()

    if not paths:
        raise SystemExit("STOP: V32 paths are empty")

    path_rows = []
    point_rows = []
    sequence_rows = []

    for p in paths:
        aa = by_attempt.get(key(p), [])
        seq, seq_detail = analyze_sequence(p, aa)

        row = {
            "session_date": p["session_date"],
            "direction": p["direction"],
            "entry_timestamp": p["entry_timestamp"],
            "block": p.get("block"),
            "resolution": p["resolution"],
            "degraded_duration_minutes": f(p.get("degraded_duration_minutes")),
            "worst_damage_points": f(p.get("worst_damage_points")),
            "worst_damage_fraction": f(p.get("worst_damage_fraction")),
            **seq,
        }
        path_rows.append(row)
        sequence_rows.extend(seq_detail)

        ev_pair = events.get(key(p))
        ev = ev_pair[0] if ev_pair else None
        ev_source = ev_pair[1] if ev_pair else None
        point_rows.append(build_points_row(p, ev, ev_source, seq))

    recovered = [r for r in path_rows if r["resolution"] == "RECOVERED"]
    failed = [r for r in path_rows if r["resolution"] == "FAILED_RECOVERY"]

    # Counterexamples that have >=2 weakening transitions after best attempt.
    rec_counter = [
        r for r in recovered
        if r["longest_weakening_streak_after_best"] >= 2
    ]

    fail_expansion = stats(
        r["gap_expansion_best_to_final"] for r in failed
    )
    rec_expansion = stats(
        r["gap_expansion_best_to_final"] for r in recovered
    )

    structural_giveback = stats(
        r["structural_giveback_points"] for r in point_rows
    )
    degraded_points = stats(
        r["degraded_trigger_directional_points"] for r in point_rows
    )
    best_attempt_points = stats(
        r["best_recovery_attempt_directional_points"] for r in point_rows
    )

    lines = [
        "B FAMILY — V34 RECOVERY-ATTEMPT DETERIORATION + POINTS SCORECARD",
        "=" * 118,
        f"paths={len(path_rows)}",
        f"recovered={len(recovered)}",
        f"failed_recovery={len(failed)}",
        "",
        "POST-BEST-ATTEMPT DETERIORATION",
        "-" * 118,
        f"FAILED gap expansion best->final: n={fail_expansion['n']} "
        f"median={fmt(fail_expansion['median'])} mean={fmt(fail_expansion['mean'])}",
        f"RECOVERED gap expansion best->final: n={rec_expansion['n']} "
        f"median={fmt(rec_expansion['median'])} mean={fmt(rec_expansion['mean'])}",
        f"Recovered paths with >=2 consecutive weakening transitions AFTER best attempt: "
        f"{len(rec_counter)}/{len(recovered)}",
        "",
        "FAILED PATH DETAILS",
        "-" * 118,
    ]

    for r in failed:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"bestAttempt={r['best_attempt_number']} "
            f"bestGap={fmt(r['best_attempt_gap'])} "
            f"finalGap={fmt(r['final_attempt_gap'])} "
            f"expansion={fmt(r['gap_expansion_best_to_final'])} "
            f"afterBest={r['attempts_after_best']} "
            f"weakAfterBest={r['weakening_after_best']} "
            f"longestWeakAfterBest={r['longest_weakening_streak_after_best']} "
            f"best->resolution={fmt(r['minutes_best_attempt_to_resolution'])}m"
        )

    lines += [
        "",
        "RECOVERED COUNTEREXAMPLES AFTER BEST ATTEMPT",
        "-" * 118,
    ]

    if rec_counter:
        for r in rec_counter:
            lines.append(
                f"{r['session_date']} {r['direction']} "
                f"bestGap={fmt(r['best_attempt_gap'])} "
                f"finalGap={fmt(r['final_attempt_gap'])} "
                f"expansion={fmt(r['gap_expansion_best_to_final'])} "
                f"longestWeakAfterBest={r['longest_weakening_streak_after_best']} "
                f"best->resolution={fmt(r['minutes_best_attempt_to_resolution'])}m"
            )
    else:
        lines.append("none")

    lines += [
        "",
        "POINTS SCORECARD — NIFTY UNDERLYING, NOT OPTION P&L",
        "-" * 118,
        f"degraded-trigger directional points: n={degraded_points['n']} "
        f"median={fmt(degraded_points['median'])} mean={fmt(degraded_points['mean'])}",
        f"best recovery-attempt directional points: n={best_attempt_points['n']} "
        f"median={fmt(best_attempt_points['median'])} mean={fmt(best_attempt_points['mean'])}",
        f"structural giveback points: n={structural_giveback['n']} "
        f"median={fmt(structural_giveback['median'])} mean={fmt(structural_giveback['mean'])}",
        "",
        "POINT ACCOUNTING POLICY FROM V34 ONWARD",
        "-" * 118,
        "- Every actual EXIT candidate must report realized directional NIFTY points.",
        "- Compare candidate exit points against structural-invalidation baseline.",
        "- Compare candidate exit points against the immediately prior exit candidate.",
        "- Report total, mean, median, worst, and max-drawdown where applicable.",
        "- Report +50/+75/+100 runner preservation where applicable.",
        "- State transitions such as RECOVERED are NOT counted as realized P&L.",
        "- Option premium / rupee P&L will remain separate until option-exit validation.",
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Descriptive V34 study only.",
        "- No threshold search.",
        "- No new exit rule.",
        "- Family-B remains frozen.",
        "- V20 classifier remains frozen.",
        "- V29 remains rejected as an exit.",
        "- All point figures are underlying NIFTY directional points.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_RECOVERY_DETERIORATION_POINTS_V34",
        "paths": len(path_rows),
        "recovered": len(recovered),
        "failed_recovery": len(failed),
        "post_best_attempt": {
            "failed_gap_expansion": fail_expansion,
            "recovered_gap_expansion": rec_expansion,
            "recovered_2plus_weakening_after_best": len(rec_counter),
        },
        "points_scorecard": {
            "unit": "NIFTY_UNDERLYING_DIRECTIONAL_POINTS",
            "not_option_premium_pnl": True,
            "degraded_trigger_points": degraded_points,
            "best_recovery_attempt_points": best_attempt_points,
            "structural_giveback_points": structural_giveback,
        },
        "point_accounting_policy": {
            "future_exit_tests_report_realized_points": True,
            "compare_to_structural_baseline": True,
            "compare_to_prior_candidate": True,
            "state_transitions_not_realized_pnl": True,
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
    write_csv(PATH_CSV, path_rows)
    write_csv(POINTS_CSV, point_rows)
    write_csv(ATTEMPT_CSV, sequence_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("PATH CSV    :", PATH_CSV)
    print("POINTS CSV  :", POINTS_CSV)
    print("ATTEMPT CSV :", ATTEMPT_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
