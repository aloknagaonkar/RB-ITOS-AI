#!/usr/bin/env python3
"""
B FAMILY — V37 POST-RECOVERY FAILURE / REBREAK OPTIMIZATION

Why V37
-------
V36 showed that a simple degraded-state timeout does not improve V35:
- T10 caught one event but lost points.
- T15+ produced no rescue exits.
So the remaining problem is NOT "failed to recover quickly enough".

V37 studies the next structural hypothesis on the 14 V35 fallbacks:

    DEGRADED
      -> price successfully RETAKES the recovery target
      -> later loses that same recovery target again
      -> optional persistence / futures-VWAP confirmation
      -> secondary rescue exit

Primary exit remains FIXED:
    V35_W1_AGE10

Secondary rescue search grid
----------------------------
consecutive closes back below recovery target: 1 / 2 / 3
minimum minutes after recovery before rebreak: 0 / 3 / 5 / 10
confirmation:
    NONE
    VWAP_WEAK_VS_RECOVERY
      directional futures-VWAP at exit < directional futures-VWAP at recovery

The candidate fires only when V35 primary has NOT already fired.

Scorecard
---------
Same 18-event development population:
- total / mean / median / worst / best points
- max drawdown
- delta vs V34.2 common baseline
- delta vs V29
- delta vs V35
- delta vs V36 (= V35, since V36 did not improve)
- +30/+40/+50/+75/+100 chase/preservation
- later-new-MFE after exit
- primary / rescue / fallback counts

All figures are NIFTY underlying directional points.
Development/tuning only; not production validation.
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

BASE_EVENTS = (
    RESEARCH / "b-family-comparable-points-baseline-v34_2"
    / "comparable-event-points-v34_2.csv"
)
PATHS_CSV = (
    RESEARCH / "b-family-degraded-state-population-v32"
    / "degraded-state-population-v32.csv"
)
ATTEMPTS_CSV = (
    RESEARCH / "b-family-degraded-state-population-v32"
    / "recovery-attempts-v32.csv"
)
V35_WINNER = (
    RESEARCH / "b-family-exit-optimization-v35"
    / "winner-v35.json"
)

OUTDIR = RESEARCH / "b-family-post-recovery-rebreak-v37"
LEADERBOARD_CSV = OUTDIR / "candidate-leaderboard-v37.csv"
EVENTS_CSV = OUTDIR / "candidate-event-results-v37.csv"
WINNER_JSON = OUTDIR / "winner-v37.json"
REPORT_JSON = OUTDIR / "report-v37.json"
SUMMARY_TXT = OUTDIR / "summary-v37.txt"

STREAKS = (1, 2, 3)
GRACES = (0, 3, 5, 10)
CONFIRMS = ("NONE", "VWAP_WEAK_VS_RECOVERY")
MILESTONES = (30, 40, 50, 75, 100)


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing input {path}")
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


def minutes(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


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
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for x in vals:
        eq += float(x)
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return mdd


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def key(r):
    return (r["session_date"], r["direction"], r["entry_timestamp"])


def discover_raw():
    underlying = defaultdict(dict)
    futures = defaultdict(dict)

    for p in ROOT.rglob("*.csv"):
        n = p.name.lower()

        if "underlying" in n:
            try:
                rows = load_csv(p)
            except Exception:
                continue
            if rows and {
                "session_date","timestamp","open","high","low","close"
            }.issubset(rows[0].keys()):
                for r in rows:
                    underlying[r["session_date"]][r["timestamp"]] = {
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                    }

        if "futures" in n and "vwap" in n:
            try:
                rows = load_csv(p)
            except Exception:
                continue
            if rows and {
                "session_date","timestamp","close","session_vwap"
            }.issubset(rows[0].keys()):
                for r in rows:
                    if r.get("session_vwap") in ("", None):
                        continue
                    futures[r["session_date"]][r["timestamp"]] = {
                        "close": float(r["close"]),
                        "vwap": float(r["session_vwap"]),
                    }

    return dict(underlying), dict(futures)


def load_attempts():
    by = defaultdict(list)
    for r in load_csv(ATTEMPTS_CSV):
        by[key(r)].append(r)
    for k in by:
        by[k].sort(key=lambda r: i(r["attempt_number"]) or 0)
    return by


def v35_primary(path, attempts):
    """
    Fixed V35 winner:
      weakening streak=1
      minimum degraded age=10m
    """
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

        age = minutes(path["degraded_timestamp"], a["peak_timestamp"])

        if weakening_streak >= 1 and age >= 10:
            return a["peak_timestamp"]

        prev_gap = gap

    return None


def first_recovery(path, base, u):
    """
    V32 recovery target = episode-start directional close level.
    Recovery occurs when directional close move becomes strictly greater than
    the target.
    """
    direction = base["direction"]
    entry = f(base["entry_close"])
    target = f(path.get("episode_start_directional_close_level"))
    degraded = path["degraded_timestamp"]
    terminal = base["terminal_timestamp"]

    if target is None:
        return None

    for ts in sorted(u):
        if ts <= degraded:
            continue
        if ts >= terminal:
            break
        move = directional(direction, entry, u[ts]["close"])
        if move > target:
            return {
                "timestamp": ts,
                "target_move": target,
                "recovery_move": move,
            }

    return None


def rescue_rebreak(base, recovery, u, fut, streak_required, grace, confirm):
    direction = base["direction"]
    entry = f(base["entry_close"])
    terminal = base["terminal_timestamp"]
    recovery_ts = recovery["timestamp"]
    target = recovery["target_move"]

    recovery_dvwap = directional_vwap(direction, fut.get(recovery_ts))

    streak = 0
    streak_start = None

    for ts in sorted(u):
        if ts <= recovery_ts:
            continue
        if ts >= terminal:
            break

        if minutes(recovery_ts, ts) < grace:
            continue

        move = directional(direction, entry, u[ts]["close"])
        below = move < target

        if below:
            if streak == 0:
                streak_start = ts
            streak += 1
        else:
            streak = 0
            streak_start = None

        if streak >= streak_required:
            ok = True
            if confirm == "VWAP_WEAK_VS_RECOVERY":
                now = directional_vwap(direction, fut.get(ts))
                ok = (
                    recovery_dvwap is not None
                    and now is not None
                    and now < recovery_dvwap
                )

            if ok:
                return {
                    "exit_timestamp": ts,
                    "rebreak_streak": streak,
                    "streak_start_timestamp": streak_start,
                    "minutes_after_recovery": minutes(recovery_ts, ts),
                    "exit_move": move,
                    "recovery_dvwap": recovery_dvwap,
                    "exit_dvwap": directional_vwap(direction, fut.get(ts)),
                }

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


def evaluate(streak, grace, confirm, bases, paths, attempts_by, uall, fall):
    name = f"V37_RB{streak}_G{grace}_{confirm}"
    rows = []

    for base in bases:
        k = key(base)
        path = paths[k]
        attempts = attempts_by.get(k, [])
        d = base["session_date"]
        u = uall[d]
        fut = fall[d]

        entry = f(base["entry_close"])
        terminal = base["terminal_timestamp"]
        baseline = f(base["baseline_points"])
        v29 = f(base["v29_points"])

        primary_ts = v35_primary(path, attempts)

        exit_ts = None
        exit_type = "FALLBACK"
        recovery = None
        rescue = None

        if primary_ts and primary_ts in u and primary_ts < terminal:
            exit_ts = primary_ts
            exit_type = "V35_PRIMARY"
        else:
            recovery = first_recovery(path, base, u)
            if recovery:
                rescue = rescue_rebreak(
                    base, recovery, u, fut,
                    streak_required=streak,
                    grace=grace,
                    confirm=confirm,
                )
                if rescue:
                    exit_ts = rescue["exit_timestamp"]
                    exit_type = "POST_RECOVERY_REBREAK"

        if exit_ts:
            points = directional(
                base["direction"], entry, u[exit_ts]["close"]
            )
            later = later_new_mfe(
                base["direction"], entry, exit_ts, terminal, u
            )
        else:
            points = baseline
            later = None

        row = {
            "candidate": name,
            "session_date": d,
            "direction": base["direction"],
            "entry_timestamp": base["entry_timestamp"],
            "exit_type": exit_type,
            "exit_timestamp": exit_ts,
            "points": points,
            "baseline_points": baseline,
            "v29_points": v29,
            "delta_vs_baseline": points - baseline,
            "later_new_mfe": later,
            "recovery_timestamp": recovery["timestamp"] if recovery else None,
            "recovery_target_move": recovery["target_move"] if recovery else None,
            "rescue_streak": rescue["rebreak_streak"] if rescue else None,
            "minutes_after_recovery": (
                rescue["minutes_after_recovery"] if rescue else None
            ),
        }

        for m in MILESTONES:
            mt = milestone_timestamp(
                base["direction"], entry, base["entry_timestamp"],
                terminal, u, m
            )
            row[f"plus{m}_timestamp"] = mt
            row[f"reached_plus{m}"] = mt is not None
            row[f"exit_before_plus{m}"] = bool(
                exit_ts and mt and exit_ts < mt
            )

        rows.append(row)

    vals = [r["points"] for r in rows]
    base_vals = [r["baseline_points"] for r in rows]
    v29_vals = [r["v29_points"] for r in rows]

    s = stats(vals)
    db = stats([v - b for v, b in zip(vals, base_vals)])
    dv29 = stats([v - x for v, x in zip(vals, v29_vals)])

    exits = [r for r in rows if r["exit_timestamp"]]
    primary = sum(r["exit_type"] == "V35_PRIMARY" for r in rows)
    rescue = sum(r["exit_type"] == "POST_RECOVERY_REBREAK" for r in rows)
    later = sum(r["later_new_mfe"] is True for r in exits)

    summary = {
        "candidate": name,
        "rebreak_streak": streak,
        "recovery_grace_minutes": grace,
        "confirmation": confirm,
        "events": len(rows),
        "primary_exits": primary,
        "rescue_exits": rescue,
        "fallbacks": len(rows) - primary - rescue,
        "actual_exit_count": len(exits),
        "later_new_mfe_count": later,
        "total_points": s["total"],
        "mean_points": s["mean"],
        "median_points": s["median"],
        "worst_points": s["min"],
        "best_points": s["max"],
        "max_drawdown_points": max_drawdown(vals),
        "delta_vs_baseline_total": db["total"],
        "delta_vs_v29_total": dv29["total"],
    }

    for m in MILESTONES:
        reached = [r for r in rows if r[f"reached_plus{m}"]]
        cut = [r for r in reached if r[f"exit_before_plus{m}"]]
        preserved = len(reached) - len(cut)

        summary[f"plus{m}_reached"] = len(reached)
        summary[f"plus{m}_preserved"] = preserved
        summary[f"plus{m}_rate"] = (
            preserved / len(reached) if reached else None
        )

    return summary, rows


def main():
    print("B FAMILY — V37 POST-RECOVERY FAILURE / REBREAK OPTIMIZATION")
    print("=" * 118)

    bases = load_csv(BASE_EVENTS)
    paths = {key(r): r for r in load_csv(PATHS_CSV)}
    attempts = load_attempts()
    uall, fall = discover_raw()

    if len(bases) != 18:
        raise SystemExit(f"STOP: expected 18 baseline events, got {len(bases)}")

    v35 = json.loads(V35_WINNER.read_text())
    v35_total = f(v35["total_points"])
    baseline_total = sum(f(r["baseline_points"]) for r in bases)
    v29_total = sum(f(r["v29_points"]) for r in bases)

    leaders = []
    event_rows = []

    for streak in STREAKS:
        for grace in GRACES:
            for confirm in CONFIRMS:
                s, rows = evaluate(
                    streak, grace, confirm,
                    bases, paths, attempts, uall, fall
                )
                s["delta_vs_v35_total"] = s["total_points"] - v35_total
                leaders.append(s)
                event_rows.extend(rows)

                print(
                    f"{s['candidate']:<31} "
                    f"total={fmt(s['total_points'])} "
                    f"ΔV35={fmt(s['delta_vs_v35_total'])} "
                    f"DD={fmt(s['max_drawdown_points'])} "
                    f"P={s['primary_exits']} R={s['rescue_exits']} "
                    f"+50={s['plus50_preserved']}/{s['plus50_reached']} "
                    f"+75={s['plus75_preserved']}/{s['plus75_reached']} "
                    f"+100={s['plus100_preserved']}/{s['plus100_reached']}"
                )

    leaders.sort(
        key=lambda r: (
            r["total_points"],
            r["max_drawdown_points"],
            -r["later_new_mfe_count"],
        ),
        reverse=True,
    )

    for rank, r in enumerate(leaders, 1):
        r["rank"] = rank

    winner = leaders[0]

    lines = [
        "B FAMILY — V37 POST-RECOVERY FAILURE / REBREAK OPTIMIZATION",
        "=" * 118,
        f"development_events={len(bases)}",
        f"candidate_count={len(leaders)}",
        "",
        "REFERENCE",
        "-" * 118,
        f"V34.2 baseline={fmt(baseline_total)}",
        f"V29 rejected={fmt(v29_total)}",
        f"V35 winner={fmt(v35_total)}",
        f"V36 winner={fmt(v35_total)}  (no improvement over V35)",
        "",
        "TOP CANDIDATES",
        "-" * 118,
    ]

    for r in leaders[:10]:
        lines.append(
            f"#{r['rank']:02d} {r['candidate']} "
            f"total={fmt(r['total_points'])} "
            f"Δbase={fmt(r['delta_vs_baseline_total'])} "
            f"ΔV35={fmt(r['delta_vs_v35_total'])} "
            f"mean={fmt(r['mean_points'])} "
            f"median={fmt(r['median_points'])} "
            f"worst={fmt(r['worst_points'])} "
            f"maxDD={fmt(r['max_drawdown_points'])} "
            f"P={r['primary_exits']} R={r['rescue_exits']} "
            f"laterNewMFE={r['later_new_mfe_count']}/{r['actual_exit_count']}"
        )

    lines += [
        "",
        "WINNER SCORECARD",
        "-" * 118,
        f"candidate={winner['candidate']}",
        f"total={fmt(winner['total_points'])}",
        f"Δ vs V34.2 baseline={fmt(winner['delta_vs_baseline_total'])}",
        f"Δ vs V29={fmt(winner['delta_vs_v29_total'])}",
        f"Δ vs V35={fmt(winner['delta_vs_v35_total'])}",
        f"mean={fmt(winner['mean_points'])}",
        f"median={fmt(winner['median_points'])}",
        f"worst={fmt(winner['worst_points'])}",
        f"best={fmt(winner['best_points'])}",
        f"maxDD={fmt(winner['max_drawdown_points'])}",
        f"primary exits={winner['primary_exits']}",
        f"rescue exits={winner['rescue_exits']}",
        f"fallbacks={winner['fallbacks']}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-" * 118,
    ]

    for m in MILESTONES:
        rate = winner[f"plus{m}_rate"]
        if rate is None:
            lines.append(f"+{m}: no events")
        else:
            lines.append(
                f"+{m}: {winner[f'plus{m}_preserved']}/"
                f"{winner[f'plus{m}_reached']} ({rate*100:.1f}%)"
            )

    lines += [
        f"later new MFE after actual exit: "
        f"{winner['later_new_mfe_count']}/{winner['actual_exit_count']}",
        "",
        "INTERPRETATION GUARD",
        "-" * 118,
        "- V37 is development/tuning on the same 18-event population.",
        "- A higher point result is optimization evidence, not independent validation.",
        "- If V37 improves V35 materially, freeze the winning structure next and test it OOS.",
        "- If V37 does not improve V35, reject post-recovery target rebreak as the next rescue mechanism.",
        "- Underlying NIFTY points only; no option premium or rupee P&L.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(LEADERBOARD_CSV, leaders)
    write_csv(EVENTS_CSV, event_rows)
    WINNER_JSON.write_text(json.dumps(winner, indent=2))
    REPORT_JSON.write_text(json.dumps({
        "version": "V37",
        "reference": {
            "baseline": baseline_total,
            "v29": v29_total,
            "v35": v35_total,
            "v36": v35_total,
        },
        "winner": winner,
        "leaderboard": leaders,
    }, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("LEADERBOARD :", LEADERBOARD_CSV)
    print("EVENTS      :", EVENTS_CSV)
    print("WINNER JSON :", WINNER_JSON)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
