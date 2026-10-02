#!/usr/bin/env python3
"""
B FAMILY — V39 MILESTONE-AWARE RESCUE OPTIMIZATION

Why V39
-------
V38_CAP50 produced the strongest point result so far:

    V38_CAP50 = +1233.75
    V34.2 baseline = +1181.90
    improvement = +51.85

But V38 still cuts too many larger runners:

    +75 preservation  = 9/13  (69.2%)
    +100 preservation = 6/10  (60.0%)

V39 keeps the V38 structure and tunes TWO causal controls:

1) rescue point cap
2) runner lockout milestone

Runner lockout:
Once a trade has already reached the configured milestone BEFORE the rescue
signal, the rescue exit is disabled and the runner continues.

This is causal/live-computable because reached milestones are known at that time.

Fixed structure
---------------
Primary:
    V35_W1_AGE10

Secondary:
    V37 RB1/G10 post-recovery rebreak

Selective rescue:
    only if current directional points <= cap

V39 grid
--------
caps:
    35, 40, 45, 50, 55, 60

runner lockout:
    NONE
    +50
    +75
    +100

Scorecard
---------
Same 18-event development population:
- total / mean / median / worst / best
- max drawdown
- delta vs V34.2 baseline
- delta vs V29
- delta vs V35
- delta vs V38_CAP50
- +30/+40/+50/+75/+100 preservation
- later-new-MFE after actual exits
- primary / rescue / fallback counts

Development/tuning only.
Underlying NIFTY directional points only.
"""

from __future__ import annotations

import csv, json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

BASE_EVENTS = RESEARCH / "b-family-comparable-points-baseline-v34_2" / "comparable-event-points-v34_2.csv"
PATHS_CSV = RESEARCH / "b-family-degraded-state-population-v32" / "degraded-state-population-v32.csv"
ATTEMPTS_CSV = RESEARCH / "b-family-degraded-state-population-v32" / "recovery-attempts-v32.csv"
V35_WINNER = RESEARCH / "b-family-exit-optimization-v35" / "winner-v35.json"
V38_WINNER = RESEARCH / "b-family-profit-aware-selective-rescue-v38" / "winner-v38.json"

OUTDIR = RESEARCH / "b-family-milestone-aware-rescue-v39"
LEADERBOARD = OUTDIR / "candidate-leaderboard-v39.csv"
EVENTS = OUTDIR / "candidate-event-results-v39.csv"
WINNER = OUTDIR / "winner-v39.json"
REPORT = OUTDIR / "report-v39.json"
SUMMARY = OUTDIR / "summary-v39.txt"

CAPS = (35, 40, 45, 50, 55, 60)
LOCKOUTS = (None, 50, 75, 100)
MILESTONES = (30, 40, 50, 75, 100)


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("", None) else float(v)


def i(v):
    return None if v in ("", None) else int(float(v))


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def stats(vals):
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0, total=None, mean=None, median=None, min=None, max=None)
    return dict(
        n=len(xs),
        total=sum(xs),
        mean=mean(xs),
        median=median(xs),
        min=min(xs),
        max=max(xs),
    )


def maxdd(vals):
    eq = 0.0
    peak = 0.0
    dd = 0.0
    for x in vals:
        eq += float(x)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dd


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


def discover_underlying():
    u = defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if rows and {"session_date","timestamp","open","high","low","close"}.issubset(rows[0]):
            for r in rows:
                u[r["session_date"]][r["timestamp"]] = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
    return dict(u)


def load_attempts():
    by = defaultdict(list)
    for r in load_csv(ATTEMPTS_CSV):
        by[key(r)].append(r)
    for k in by:
        by[k].sort(key=lambda x: i(x["attempt_number"]) or 0)
    return by


def v35_primary(path, attempts):
    best = None
    prev = None
    streak = 0

    for a in attempts:
        gap = f(a.get("gap_to_target_at_peak"))
        if gap is None:
            continue

        if best is None or gap < best:
            best = gap
            streak = 0
        else:
            if prev is not None and gap > prev:
                streak += 1
            else:
                streak = 0

        age = mins(path["degraded_timestamp"], a["peak_timestamp"])

        if streak >= 1 and age >= 10:
            return a["peak_timestamp"]

        prev = gap

    return None


def first_recovery(path, base, u):
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


def v37_rebreak(base, recovery, u):
    direction = base["direction"]
    entry = f(base["entry_close"])
    terminal = base["terminal_timestamp"]
    rts = recovery["timestamp"]
    target = recovery["target_move"]

    for ts in sorted(u):
        if ts <= rts:
            continue
        if ts >= terminal:
            break
        if mins(rts, ts) < 10:
            continue

        move = directional(direction, entry, u[ts]["close"])
        if move < target:
            return {
                "exit_timestamp": ts,
                "exit_move": move,
            }

    return None


def milestone_reached_before(direction, entry, entry_ts, before_ts, u, milestone):
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts >= before_ts:
            break
        if directional(direction, entry, favorable(direction, u[ts])) >= milestone:
            return True
    return False


def later_new_mfe(direction, entry, exit_ts, terminal, u):
    pre = None

    for ts in sorted(u):
        if ts > exit_ts:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        pre = fav if pre is None else max(pre, fav)

    if pre is None:
        return None

    for ts in sorted(u):
        if ts <= exit_ts:
            continue
        if ts >= terminal:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        if fav > pre + 1e-9:
            return True

    return False


def milestone_ts(direction, entry, entry_ts, terminal, u, milestone):
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts >= terminal:
            break
        if directional(direction, entry, favorable(direction, u[ts])) >= milestone:
            return ts
    return None


def evaluate(cap, lockout, bases, paths, attempts_by, uall):
    lock_label = "NONE" if lockout is None else f"P{lockout}"
    name = f"V39_CAP{cap}_LOCK{lock_label}"

    rows = []

    for base in bases:
        k = key(base)
        path = paths[k]
        attempts = attempts_by.get(k, [])
        d = base["session_date"]
        u = uall[d]

        entry = f(base["entry_close"])
        terminal = base["terminal_timestamp"]
        baseline = f(base["baseline_points"])
        v29 = f(base["v29_points"])

        primary = v35_primary(path, attempts)

        exit_ts = None
        exit_type = "FALLBACK"
        rescue_move = None
        lockout_hit = False

        if primary and primary in u and primary < terminal:
            exit_ts = primary
            exit_type = "V35_PRIMARY"
        else:
            rec = first_recovery(path, base, u)
            if rec:
                rb = v37_rebreak(base, rec, u)

                if rb:
                    rescue_move = rb["exit_move"]

                    if lockout is not None:
                        lockout_hit = milestone_reached_before(
                            base["direction"],
                            entry,
                            base["entry_timestamp"],
                            rb["exit_timestamp"],
                            u,
                            lockout,
                        )

                    if rescue_move <= cap and not lockout_hit:
                        exit_ts = rb["exit_timestamp"]
                        exit_type = "MILESTONE_AWARE_RESCUE"

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

        r = {
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
            "rescue_move_seen": rescue_move,
            "runner_lockout": lockout,
            "lockout_hit": lockout_hit,
            "later_new_mfe": later,
        }

        for m in MILESTONES:
            mt = milestone_ts(
                base["direction"], entry, base["entry_timestamp"],
                terminal, u, m
            )
            r[f"plus{m}_timestamp"] = mt
            r[f"reached_plus{m}"] = mt is not None
            r[f"exit_before_plus{m}"] = bool(
                exit_ts and mt and exit_ts < mt
            )

        rows.append(r)

    vals = [r["points"] for r in rows]
    bvals = [r["baseline_points"] for r in rows]
    v29vals = [r["v29_points"] for r in rows]

    s = stats(vals)
    db = stats([v - b for v, b in zip(vals, bvals)])
    dv29 = stats([v - x for v, x in zip(vals, v29vals)])

    exits = [r for r in rows if r["exit_timestamp"]]
    primary_count = sum(r["exit_type"] == "V35_PRIMARY" for r in rows)
    rescue_count = sum(r["exit_type"] == "MILESTONE_AWARE_RESCUE" for r in rows)
    later_count = sum(r["later_new_mfe"] is True for r in exits)

    sm = {
        "candidate": name,
        "rescue_cap_points": cap,
        "runner_lockout_milestone": lockout,
        "events": len(rows),
        "primary_exits": primary_count,
        "rescue_exits": rescue_count,
        "fallbacks": len(rows) - primary_count - rescue_count,
        "actual_exit_count": len(exits),
        "later_new_mfe_count": later_count,
        "total_points": s["total"],
        "mean_points": s["mean"],
        "median_points": s["median"],
        "worst_points": s["min"],
        "best_points": s["max"],
        "max_drawdown_points": maxdd(vals),
        "delta_vs_baseline_total": db["total"],
        "delta_vs_v29_total": dv29["total"],
    }

    for m in MILESTONES:
        reached = [r for r in rows if r[f"reached_plus{m}"]]
        cut = [r for r in reached if r[f"exit_before_plus{m}"]]
        preserved = len(reached) - len(cut)

        sm[f"plus{m}_reached"] = len(reached)
        sm[f"plus{m}_preserved"] = preserved
        sm[f"plus{m}_rate"] = (
            preserved / len(reached) if reached else None
        )

    return sm, rows


def main():
    print("B FAMILY — V39 MILESTONE-AWARE RESCUE OPTIMIZATION")
    print("=" * 118)

    bases = load_csv(BASE_EVENTS)
    paths = {key(r): r for r in load_csv(PATHS_CSV)}
    attempts = load_attempts()
    uall = discover_underlying()

    if len(bases) != 18:
        raise SystemExit(f"STOP: expected 18 events, got {len(bases)}")

    v35 = json.loads(V35_WINNER.read_text())
    v38 = json.loads(V38_WINNER.read_text())

    v35_total = f(v35["total_points"])
    v38_total = f(v38["total_points"])
    baseline_total = sum(f(r["baseline_points"]) for r in bases)
    v29_total = sum(f(r["v29_points"]) for r in bases)

    leaders = []
    event_rows = []

    for cap in CAPS:
        for lockout in LOCKOUTS:
            s, rows = evaluate(
                cap, lockout, bases, paths, attempts, uall
            )

            s["delta_vs_v35_total"] = s["total_points"] - v35_total
            s["delta_vs_v38_total"] = s["total_points"] - v38_total

            leaders.append(s)
            event_rows.extend(rows)

            print(
                f"{s['candidate']:<24} "
                f"total={fmt(s['total_points'])} "
                f"ΔV38={fmt(s['delta_vs_v38_total'])} "
                f"DD={fmt(s['max_drawdown_points'])} "
                f"P={s['primary_exits']} R={s['rescue_exits']} "
                f"+50={s['plus50_preserved']}/{s['plus50_reached']} "
                f"+75={s['plus75_preserved']}/{s['plus75_reached']} "
                f"+100={s['plus100_preserved']}/{s['plus100_reached']}"
            )

    # Ranking: points first, then +100, then +75, then DD.
    leaders.sort(
        key=lambda r: (
            r["total_points"],
            r["plus100_rate"] if r["plus100_rate"] is not None else -1,
            r["plus75_rate"] if r["plus75_rate"] is not None else -1,
            r["max_drawdown_points"],
        ),
        reverse=True,
    )

    for rank, r in enumerate(leaders, 1):
        r["rank"] = rank

    winner = leaders[0]

    lines = [
        "B FAMILY — V39 MILESTONE-AWARE RESCUE OPTIMIZATION",
        "=" * 118,
        f"development_events={len(bases)}",
        f"candidate_count={len(leaders)}",
        "",
        "REFERENCE",
        "-" * 118,
        f"V34.2 baseline={fmt(baseline_total)}",
        f"V29 rejected={fmt(v29_total)}",
        f"V35 winner={fmt(v35_total)}",
        f"V38 winner={fmt(v38_total)}",
        "",
        "TOP CANDIDATES",
        "-" * 118,
    ]

    for r in leaders[:12]:
        lines.append(
            f"#{r['rank']:02d} {r['candidate']} "
            f"total={fmt(r['total_points'])} "
            f"Δbase={fmt(r['delta_vs_baseline_total'])} "
            f"ΔV35={fmt(r['delta_vs_v35_total'])} "
            f"ΔV38={fmt(r['delta_vs_v38_total'])} "
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
        f"cap={winner['rescue_cap_points']}",
        f"runner_lockout={winner['runner_lockout_milestone']}",
        f"total={fmt(winner['total_points'])}",
        f"Δ vs baseline={fmt(winner['delta_vs_baseline_total'])}",
        f"Δ vs V29={fmt(winner['delta_vs_v29_total'])}",
        f"Δ vs V35={fmt(winner['delta_vs_v35_total'])}",
        f"Δ vs V38={fmt(winner['delta_vs_v38_total'])}",
        f"mean={fmt(winner['mean_points'])}",
        f"median={fmt(winner['median_points'])}",
        f"worst={fmt(winner['worst_points'])}",
        f"best={fmt(winner['best_points'])}",
        f"maxDD={fmt(winner['max_drawdown_points'])}",
        f"primary exits={winner['primary_exits']} "
        f"rescue exits={winner['rescue_exits']} "
        f"fallbacks={winner['fallbacks']}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-" * 118,
    ]

    for m in MILESTONES:
        rate = winner[f"plus{m}_rate"]
        lines.append(
            f"+{m}: {winner[f'plus{m}_preserved']}/"
            f"{winner[f'plus{m}_reached']} "
            f"({rate*100:.1f}%)"
            if rate is not None else f"+{m}: no events"
        )

    lines += [
        f"later new MFE after actual exit: "
        f"{winner['later_new_mfe_count']}/{winner['actual_exit_count']}",
        "",
        "INTERPRETATION",
        "-" * 118,
        "- V39 asks whether once a runner has already achieved a major milestone, rescue exits should be disabled.",
        "- This is still development/tuning on the same 18 events.",
        "- If V39 improves V38 or preserves similar points with materially better +75/+100 chase, freeze it next.",
        "- Then test the frozen candidate on a separate historical block.",
        "- Underlying NIFTY points only; no option premium or rupee P&L.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(LEADERBOARD, leaders)
    write_csv(EVENTS, event_rows)
    WINNER.write_text(json.dumps(winner, indent=2))
    REPORT.write_text(json.dumps({
        "version": "V39",
        "reference": {
            "baseline": baseline_total,
            "v29": v29_total,
            "v35": v35_total,
            "v38": v38_total,
        },
        "winner": winner,
        "leaderboard": leaders,
    }, indent=2))
    SUMMARY.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("LEADERBOARD :", LEADERBOARD)
    print("EVENTS      :", EVENTS)
    print("WINNER JSON :", WINNER)
    print("REPORT JSON :", REPORT)
    print("SUMMARY     :", SUMMARY)


if __name__ == "__main__":
    main()
