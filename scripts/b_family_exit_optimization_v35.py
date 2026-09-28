#!/usr/bin/env python3
"""
B FAMILY — V35 EXIT OPTIMIZATION + POINT-IMPROVEMENT LEADERBOARD

Purpose
-------
Tune the recovery-attempt exit on the current 18-event DEVELOPMENT population.

This is intentionally an optimization study. The winning rule from V35 is NOT
considered validated until it is frozen and tested on separate OOS history.

Candidate family
----------------
After DEGRADED state begins:
- maintain the best (smallest) recovery gap seen so far
- a later completed recovery attempt is WEAKENING if its gap is larger than the
  previous attempt's gap
- count consecutive weakening attempts after the running best
- optional minimum degraded-state age before exit

Transparent search grid:
  weakening streak required: 1, 2, 3, 4
  minimum degraded age:      0, 3, 5, 10 minutes

Exit timestamp:
  peak timestamp of the attempt that completes the required weakening streak.

If a candidate never exits:
  fall back to STRUCTURAL_OR_SESSION_CUTOFF from V34.2.

Scorecard
---------
Every candidate reports:
- total / mean / median / worst / best NIFTY directional points
- max drawdown
- delta vs V34.2 common baseline
- delta vs V29 full policy
- milestone preservation at +30/+40/+50/+75/+100
- chase/capture rate at +30/+40/+50/+75/+100
- later-new-MFE after actual candidate exits
- actual exit count vs fallback count

All point figures are NIFTY underlying directional points.
Not option premium P&L. Not rupee P&L.
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

V34_2_EVENTS = (
    RESEARCH / "b-family-comparable-points-baseline-v34_2"
    / "comparable-event-points-v34_2.csv"
)
V34_2_SCORE = (
    RESEARCH / "b-family-comparable-points-baseline-v34_2"
    / "comparable-scorecard-v34_2.csv"
)
V32_ATTEMPTS = (
    RESEARCH / "b-family-degraded-state-population-v32"
    / "recovery-attempts-v32.csv"
)
V32_PATHS = (
    RESEARCH / "b-family-degraded-state-population-v32"
    / "degraded-state-population-v32.csv"
)

OUTDIR = RESEARCH / "b-family-exit-optimization-v35"
LEADERBOARD_CSV = OUTDIR / "candidate-leaderboard-v35.csv"
EVENT_RESULTS_CSV = OUTDIR / "candidate-event-results-v35.csv"
WINNER_JSON = OUTDIR / "winner-v35.json"
REPORT_JSON = OUTDIR / "report-v35.json"
SUMMARY_TXT = OUTDIR / "summary-v35.txt"

STREAKS = (1, 2, 3, 4)
MIN_AGES = (0, 3, 5, 10)
MILESTONES = (30, 40, 50, 75, 100)


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


def b(v):
    return str(v).strip().lower() == "true"


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {
            "n": 0, "total": None, "mean": None, "median": None,
            "min": None, "max": None
        }
    return {
        "n": len(xs),
        "total": sum(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def max_drawdown(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for x in xs:
        equity += x
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd if xs else None


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


def discover_underlying():
    files = []
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if rows and {"session_date","timestamp","open","high","low","close"}.issubset(rows[0].keys()):
            files.append(p)

    by = defaultdict(dict)
    for p in files:
        for r in load_csv(p):
            by[r["session_date"]][r["timestamp"]] = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
    return dict(by)


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def load_baselines():
    events = load_csv(V34_2_EVENTS)
    if len(events) != 18:
        raise SystemExit(f"STOP: expected 18 V34.2 events, got {len(events)}")

    by = {key(r): r for r in events}
    return events, by


def load_paths():
    rows = load_csv(V32_PATHS)
    return {key(r): r for r in rows}


def load_attempts():
    by = defaultdict(list)
    for r in load_csv(V32_ATTEMPTS):
        by[key(r)].append(r)
    for k in by:
        by[k].sort(key=lambda x: i(x["attempt_number"]) or 0)
    return by


def candidate_exit_from_attempts(path, attempts, streak_required, min_age):
    """
    Causal attempt-sequence candidate:
    - Track running best gap.
    - Count consecutive weakening transitions after that best.
    - Reset weakening count on a new running best or non-weakening transition.
    - Exit at peak timestamp completing streak, only if degraded age >= min_age.
    """
    if not attempts:
        return None

    degraded_ts = path["degraded_timestamp"]

    best_gap = None
    prev_gap = None
    weakening_streak = 0

    for a in attempts:
        gap = f(a.get("gap_to_target_at_peak"))
        if gap is None:
            continue

        if best_gap is None or gap < best_gap:
            best_gap = gap
            weakening_streak = 0
        else:
            if prev_gap is not None and gap > prev_gap:
                weakening_streak += 1
            else:
                weakening_streak = 0

        age = mins(degraded_ts, a["peak_timestamp"])

        if weakening_streak >= streak_required and age >= min_age:
            return {
                "exit_timestamp": a["peak_timestamp"],
                "trigger_attempt_number": i(a["attempt_number"]),
                "weakening_streak": weakening_streak,
                "age_minutes": age,
                "gap_at_exit_attempt": gap,
                "running_best_gap": best_gap,
            }

        prev_gap = gap

    return None


def later_new_mfe(direction, entry, exit_ts, terminal_ts, u):
    pre_peak = None
    for ts in sorted(u):
        if ts > exit_ts:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        pre_peak = fav if pre_peak is None else max(pre_peak, fav)

    if pre_peak is None:
        return None

    for ts in sorted(u):
        if ts <= exit_ts:
            continue
        if ts >= terminal_ts:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        if fav > pre_peak + 1e-9:
            return True
    return False


def milestone_timestamp(direction, entry, entry_ts, terminal_ts, u, milestone):
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts >= terminal_ts:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        if fav >= milestone:
            return ts
    return None


def evaluate_candidate(name, streak_required, min_age, baselines, baseline_by, paths, attempts_by, underlying):
    event_results = []

    for base in baselines:
        k = key(base)
        path = paths[k]
        attempts = attempts_by.get(k, [])
        d = base["session_date"]
        u = underlying[d]

        entry = f(base["entry_close"])
        if entry is None:
            raise RuntimeError(f"Missing entry_close for {k}")

        terminal_ts = base["terminal_timestamp"]
        fallback_points = f(base["baseline_points"])

        trigger = candidate_exit_from_attempts(
            path, attempts, streak_required, min_age
        )

        if trigger and trigger["exit_timestamp"] in u and trigger["exit_timestamp"] < terminal_ts:
            exit_ts = trigger["exit_timestamp"]
            points = directional(
                base["direction"],
                entry,
                u[exit_ts]["close"],
            )
            actual_exit = True
            later_mfe = later_new_mfe(
                base["direction"], entry, exit_ts, terminal_ts, u
            )
        else:
            exit_ts = None
            points = fallback_points
            actual_exit = False
            later_mfe = None
            trigger = None

        row = {
            "candidate": name,
            "session_date": base["session_date"],
            "direction": base["direction"],
            "entry_timestamp": base["entry_timestamp"],
            "actual_exit": actual_exit,
            "exit_timestamp": exit_ts,
            "points": points,
            "baseline_points": fallback_points,
            "delta_vs_baseline": points - fallback_points,
            "later_new_mfe": later_mfe,
            "trigger_attempt_number": (
                trigger["trigger_attempt_number"] if trigger else None
            ),
            "weakening_streak": (
                trigger["weakening_streak"] if trigger else None
            ),
            "age_minutes": trigger["age_minutes"] if trigger else None,
            "gap_at_exit_attempt": (
                trigger["gap_at_exit_attempt"] if trigger else None
            ),
        }

        for m in MILESTONES:
            mt = milestone_timestamp(
                base["direction"], entry, base["entry_timestamp"],
                terminal_ts, u, m
            )
            row[f"plus{m}_timestamp"] = mt
            row[f"reached_plus{m}"] = mt is not None
            row[f"exit_before_plus{m}"] = bool(exit_ts and mt and exit_ts < mt)

        event_results.append(row)

    vals = [r["points"] for r in event_results]
    base_vals = [r["baseline_points"] for r in event_results]
    v29_vals = [f(r["v29_points"]) for r in baselines]

    s = stats(vals)
    delta_base = stats(v - b for v, b in zip(vals, base_vals))
    delta_v29 = stats(v - vv for v, vv in zip(vals, v29_vals))

    actual = [r for r in event_results if r["actual_exit"]]
    later_new_count = sum(r["later_new_mfe"] is True for r in actual)

    summary = {
        "candidate": name,
        "streak_required": streak_required,
        "min_degraded_age_minutes": min_age,
        "events": len(event_results),
        "actual_exits": len(actual),
        "fallbacks": len(event_results) - len(actual),
        "total_points": s["total"],
        "mean_points": s["mean"],
        "median_points": s["median"],
        "worst_points": s["min"],
        "best_points": s["max"],
        "max_drawdown_points": max_drawdown(vals),
        "delta_vs_baseline_total": delta_base["total"],
        "delta_vs_baseline_mean": delta_base["mean"],
        "delta_vs_v29_total": delta_v29["total"],
        "delta_vs_v29_mean": delta_v29["mean"],
        "later_new_mfe_after_exit_count": later_new_count,
        "later_new_mfe_after_exit_rate": (
            later_new_count / len(actual) if actual else None
        ),
    }

    for m in MILESTONES:
        reached = [r for r in event_results if r[f"reached_plus{m}"]]
        cut = [r for r in reached if r[f"exit_before_plus{m}"]]
        preserved = len(reached) - len(cut)

        summary[f"plus{m}_reached"] = len(reached)
        summary[f"plus{m}_preserved"] = preserved
        summary[f"plus{m}_preservation_rate"] = (
            preserved / len(reached) if reached else None
        )

        # "Chased successfully" = candidate remained open long enough for the
        # lifecycle to achieve the milestone.
        summary[f"plus{m}_chase_success_rate"] = (
            preserved / len(reached) if reached else None
        )

    return summary, event_results


def main():
    print("B FAMILY — V35 EXIT OPTIMIZATION + POINT-IMPROVEMENT LEADERBOARD")
    print("=" * 118)

    baselines, baseline_by = load_baselines()
    paths = load_paths()
    attempts_by = load_attempts()
    underlying = discover_underlying()

    # Ensure all raw sessions available.
    for r in baselines:
        if r["session_date"] not in underlying:
            raise SystemExit(f"STOP: missing underlying for {r['session_date']}")

    leaderboard = []
    all_event_results = []

    for streak in STREAKS:
        for age in MIN_AGES:
            name = f"V35_W{streak}_AGE{age}"
            summary, event_results = evaluate_candidate(
                name, streak, age,
                baselines, baseline_by, paths, attempts_by, underlying
            )
            leaderboard.append(summary)
            all_event_results.extend(event_results)

            print(
                f"{name:<15} total={fmt(summary['total_points'])} "
                f"Δbase={fmt(summary['delta_vs_baseline_total'])} "
                f"ΔV29={fmt(summary['delta_vs_v29_total'])} "
                f"DD={fmt(summary['max_drawdown_points'])} "
                f"exits={summary['actual_exits']} "
                f"+50={summary['plus50_preserved']}/{summary['plus50_reached']} "
                f"+75={summary['plus75_preserved']}/{summary['plus75_reached']} "
                f"+100={summary['plus100_preserved']}/{summary['plus100_reached']}"
            )

    # Rank primarily by total points, then lower later-new-MFE rate,
    # then better max drawdown.
    def rank_key(r):
        rate = r["later_new_mfe_after_exit_rate"]
        if rate is None:
            rate = 1.0
        return (
            r["total_points"],
            -rate,
            r["max_drawdown_points"],
        )

    leaderboard.sort(key=rank_key, reverse=True)
    for idx, row in enumerate(leaderboard, 1):
        row["rank_by_total_points"] = idx

    winner = leaderboard[0]

    base_total = sum(f(r["baseline_points"]) for r in baselines)
    v29_total = sum(f(r["v29_points"]) for r in baselines)

    lines = [
        "B FAMILY — V35 EXIT OPTIMIZATION + POINT-IMPROVEMENT LEADERBOARD",
        "=" * 118,
        f"development_events={len(baselines)}",
        f"candidate_count={len(leaderboard)}",
        "",
        "REFERENCE",
        "-" * 118,
        f"V34.2 baseline total={fmt(base_total)}",
        f"V29 rejected total={fmt(v29_total)}",
        "",
        "TOP CANDIDATES BY TOTAL POINTS",
        "-" * 118,
    ]

    for row in leaderboard[:10]:
        lines.append(
            f"#{row['rank_by_total_points']:02d} {row['candidate']} "
            f"total={fmt(row['total_points'])} "
            f"Δbase={fmt(row['delta_vs_baseline_total'])} "
            f"ΔV29={fmt(row['delta_vs_v29_total'])} "
            f"mean={fmt(row['mean_points'])} "
            f"median={fmt(row['median_points'])} "
            f"worst={fmt(row['worst_points'])} "
            f"maxDD={fmt(row['max_drawdown_points'])} "
            f"exits={row['actual_exits']} "
            f"laterNewMFE={row['later_new_mfe_after_exit_count']}/{row['actual_exits']}"
        )

    lines += [
        "",
        "WINNER DEVELOPMENT SCORECARD",
        "-" * 118,
        f"candidate={winner['candidate']}",
        f"streak_required={winner['streak_required']}",
        f"min_degraded_age_minutes={winner['min_degraded_age_minutes']}",
        f"total={fmt(winner['total_points'])}",
        f"mean={fmt(winner['mean_points'])}",
        f"median={fmt(winner['median_points'])}",
        f"worst={fmt(winner['worst_points'])}",
        f"best={fmt(winner['best_points'])}",
        f"maxDD={fmt(winner['max_drawdown_points'])}",
        f"Δ vs V34.2 baseline={fmt(winner['delta_vs_baseline_total'])}",
        f"Δ vs V29={fmt(winner['delta_vs_v29_total'])}",
        "",
        "MILESTONE CHASE / PRESERVATION — WINNER",
        "-" * 118,
    ]

    for m in MILESTONES:
        lines.append(
            f"+{m}: successfully chased/preserved "
            f"{winner[f'plus{m}_preserved']}/{winner[f'plus{m}_reached']} "
            f"({winner[f'plus{m}_preservation_rate']*100:.1f}%)"
            if winner[f'plus{m}_preservation_rate'] is not None
            else f"+{m}: no events"
        )

    lines += [
        f"later new MFE after actual exit: "
        f"{winner['later_new_mfe_after_exit_count']}/{winner['actual_exits']}",
        "",
        "IMPORTANT",
        "-" * 118,
        "- V35 is a DEVELOPMENT/TUNING study.",
        "- The leaderboard winner is not yet validated.",
        "- Next step is to freeze the winner and test on separate OOS history.",
        "- We will keep this same point scorecard for every later exit version.",
        "- Optimization is allowed, but improvement must be visible numerically.",
        "",
        "GUARDS",
        "-" * 118,
        "- Underlying NIFTY directional points only.",
        "- Not option premium P&L.",
        "- Not rupee P&L.",
        "- Family-B entry unchanged.",
        "- V20 runner classifier unchanged.",
    ]

    report = {
        "version": "B_FAMILY_EXIT_OPTIMIZATION_V35",
        "development_events": len(baselines),
        "candidate_count": len(leaderboard),
        "reference": {
            "v34_2_baseline_total": base_total,
            "v29_total": v29_total,
        },
        "winner": winner,
        "leaderboard": leaderboard,
        "milestones": list(MILESTONES),
        "guards": {
            "development_tuning": True,
            "winner_validated": False,
            "unit": "NIFTY_UNDERLYING_DIRECTIONAL_POINTS",
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(LEADERBOARD_CSV, leaderboard)
    write_csv(EVENT_RESULTS_CSV, all_event_results)
    WINNER_JSON.write_text(json.dumps(winner, indent=2))
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("LEADERBOARD :", LEADERBOARD_CSV)
    print("EVENTS      :", EVENT_RESULTS_CSV)
    print("WINNER JSON :", WINNER_JSON)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
