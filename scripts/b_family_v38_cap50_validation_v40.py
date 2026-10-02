#!/usr/bin/env python3
"""
B FAMILY — V40 FROZEN V38_CAP50 HISTORICAL VALIDATION

Purpose
-------
Freeze the current best DEVELOPMENT rule V38_CAP50 and apply it unchanged to a
separate 180-session historical block:

    2025-12-12 through 2026-09-08

IMPORTANT METHODOLOGY NOTE
--------------------------
This block is date-separated from the 18-event V38 tuning population, but it is
NOT globally untouched: earlier B-family / runner research used this canonical
180-session history. Therefore V40 is a larger historical validation / stress
check, not pristine OOS.

The truly untouched forward check remains the forward block beginning
2026-09-29.

Frozen V38 policy
-----------------
B entry logic is NOT changed.

For B events that reach +20 and classify RUNNER_STRENGTHENING at +10 minutes:

1) V35 primary exit:
   - enter DEGRADED on first joint deterioration:
       running-close-MFE drawdown > 0
       AND prior-minute directional futures-VWAP change < 0
   - record failed recovery attempts below the degraded-start close target
   - running best recovery gap
   - exit on first weakening attempt after running best
   - minimum degraded age = 10 minutes

2) If V35 primary never fires:
   - wait for first close recovery above degraded-start target
   - after at least 10 minutes, first close back below target
   - rescue only when current directional points <= +50

3) Otherwise:
   - structural invalidation close if available
   - else final trusted session close

This script reconstructs the frozen policy from raw 1-minute underlying and
futures-VWAP data plus discovered canonical B-event rows.

Outputs:
- B population / +20 / RUNNER_STRENGTHENING counts
- full same-population baseline vs frozen V38
- total / mean / median / worst / best / max drawdown
- delta vs baseline
- +30/+40/+50/+75/+100 chase preservation
- later-new-MFE after exits
- primary / rescue / fallback counts
- development-reference comparison to V38_CAP50 (+1233.75 on 18 events)

Underlying NIFTY directional points only.
No option premium or rupee P&L.
No tuning grid in V40.
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

OUTDIR = RESEARCH / "b-family-v38-cap50-validation-v40"
EVENTS_CSV = OUTDIR / "validated-runner-events-v40.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v40.csv"
REPORT_JSON = OUTDIR / "report-v40.json"
SUMMARY_TXT = OUTDIR / "summary-v40.txt"

MILESTONES = (30, 40, 50, 75, 100)


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
        return dict(n=0, total=None, mean=None, median=None, min=None, max=None)
    return dict(
        n=len(xs),
        total=sum(xs),
        mean=mean(xs),
        median=median(xs),
        min=min(xs),
        max=max(xs),
    )


def max_drawdown(vals):
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for x in vals:
        equity += float(x)
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd


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


def discover_underlying():
    by = defaultdict(dict)
    files = 0

    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows or not {
            "session_date", "timestamp", "open", "high", "low", "close"
        }.issubset(rows[0].keys()):
            continue

        used = False
        for r in rows:
            d = r["session_date"]
            if not date_in_range(d):
                continue
            by[d][r["timestamp"]] = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            used = True
        if used:
            files += 1

    return dict(by), files


def discover_futures():
    by = defaultdict(dict)
    files = 0

    for p in ROOT.rglob("*.csv"):
        n = p.name.lower()
        if "futures" not in n or "vwap" not in n:
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows or not {
            "session_date", "timestamp", "close", "session_vwap"
        }.issubset(rows[0].keys()):
            continue

        used = False
        for r in rows:
            d = r["session_date"]
            if not date_in_range(d):
                continue
            if r.get("session_vwap") in ("", None):
                continue
            by[d][r["timestamp"]] = {
                "close": float(r["close"]),
                "vwap": float(r["session_vwap"]),
            }
            used = True
        if used:
            files += 1

    return dict(by), files


def discover_b_events():
    """
    Discover the richest B event row per session/direction/entry inside V40 range.
    """
    found = {}

    for p in RESEARCH.rglob("*.csv"):
        name = p.name.lower()
        if not ("b-event" in name or name.startswith("b-events")):
            continue

        try:
            rows = load_csv(p)
        except Exception:
            continue

        for r in rows:
            if not all(r.get(k) for k in (
                "session_date", "direction", "entry_timestamp"
            )):
                continue
            if not date_in_range(r["session_date"]):
                continue

            k = (r["session_date"], r["direction"], r["entry_timestamp"])
            score = sum(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "mfe",
                    "plus20_timestamp",
                    "observation_end_timestamp",
                )
            )

            if k not in found or score > found[k][0]:
                found[k] = (score, dict(r), str(p))

    return {k: (v[1], v[2]) for k, v in found.items()}


def terminal_for_event(event, u):
    entry_ts = event["entry_timestamp"]
    direction = event["direction"]

    entry = f(event.get("entry_close"))
    if entry is None:
        if entry_ts not in u:
            return None
        entry = u[entry_ts]["close"]

    invalid = event.get("structural_invalidation_timestamp") or None
    trusted = sorted(u)

    if invalid and invalid in u:
        terminal_ts = invalid
        terminal_type = "STRUCTURAL_INVALIDATION"
    else:
        terminal_ts = trusted[-1]
        terminal_type = "SESSION_CUTOFF"

    terminal_points = directional(
        direction, entry, u[terminal_ts]["close"]
    )

    return {
        "entry_close": entry,
        "terminal_timestamp": terminal_ts,
        "terminal_type": terminal_type,
        "baseline_points": terminal_points,
    }


def find_plus20(event, u, terminal_ts, entry):
    direction = event["direction"]
    entry_ts = event["entry_timestamp"]

    # Prefer source timestamp if trustworthy and present.
    source = event.get("plus20_timestamp")
    if source and source in u and source < terminal_ts:
        return source

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts >= terminal_ts:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        if fav >= 20:
            return ts

    return None


def classify_runner(event, plus20_ts, u, fut, entry, terminal_ts):
    """
    Frozen V20 sign-only classifier:
      at +10m after +20 proof:
        net directional price progress > 0
        directional futures-VWAP change > 0
    """
    class_ts = plus_minutes(plus20_ts, 10)
    if class_ts >= terminal_ts:
        return None
    if plus20_ts not in u or class_ts not in u:
        return None
    if plus20_ts not in fut or class_ts not in fut:
        return None

    direction = event["direction"]

    proof_move = directional(direction, entry, u[plus20_ts]["close"])
    class_move = directional(direction, entry, u[class_ts]["close"])
    net_progress = class_move - proof_move

    proof_vwap = directional_vwap(direction, fut[plus20_ts])
    class_vwap = directional_vwap(direction, fut[class_ts])
    vwap_change = class_vwap - proof_vwap

    return {
        "classification_timestamp": class_ts,
        "proof_move": proof_move,
        "classification_move": class_move,
        "net_progress_10m": net_progress,
        "directional_vwap_change_10m": vwap_change,
        "runner_strengthening": net_progress > 0 and vwap_change > 0,
    }


def first_degraded(event, class_ts, u, fut, entry, terminal_ts):
    direction = event["direction"]
    running_close_mfe = None
    prev_dvwap = None
    prior_joint = False

    # Seed through classification.
    for ts in sorted(u):
        if ts <= event["entry_timestamp"]:
            continue
        if ts > class_ts:
            break
        if ts >= terminal_ts:
            break

        move = directional(direction, entry, u[ts]["close"])
        running_close_mfe = (
            move if running_close_mfe is None
            else max(running_close_mfe, move)
        )

        dv = directional_vwap(direction, fut.get(ts))
        if dv is not None:
            prev_dvwap = dv

    for ts in sorted(u):
        if ts <= class_ts:
            continue
        if ts >= terminal_ts:
            break

        move = directional(direction, entry, u[ts]["close"])
        running_close_mfe = (
            move if running_close_mfe is None
            else max(running_close_mfe, move)
        )
        dd = running_close_mfe - move

        dv = directional_vwap(direction, fut.get(ts))
        dv_change = None if dv is None or prev_dvwap is None else dv - prev_dvwap

        joint = dd > 0 and dv_change is not None and dv_change < 0

        if joint and not prior_joint:
            return {
                "degraded_timestamp": ts,
                "target_move": move,
                "running_close_mfe_at_degraded": running_close_mfe,
            }

        prior_joint = joint
        if dv is not None:
            prev_dvwap = dv

    return None


def failed_recovery_attempts(degraded, event, u, entry, terminal_ts):
    """
    Build failed recovery attempts below target from contiguous directional-close
    rises. A successful retake above target is not a failed attempt.
    """
    direction = event["direction"]
    degraded_ts = degraded["degraded_timestamp"]
    target = degraded["target_move"]

    attempts = []
    in_rise = False
    peak_ts = None
    peak_move = None
    prev_move = None

    for ts in sorted(u):
        if ts <= degraded_ts:
            continue
        if ts >= terminal_ts:
            break

        move = directional(direction, entry, u[ts]["close"])

        # Successful retake ends failed-attempt collection.
        if move > target:
            break

        if prev_move is None:
            prev_move = move
            continue

        if move > prev_move:
            if not in_rise:
                in_rise = True
                peak_ts = ts
                peak_move = move
            elif peak_move is None or move >= peak_move:
                peak_ts = ts
                peak_move = move

        elif in_rise:
            gap = target - peak_move
            attempts.append({
                "peak_timestamp": peak_ts,
                "peak_move": peak_move,
                "gap_to_target": gap,
            })
            in_rise = False
            peak_ts = None
            peak_move = None

        prev_move = move

    # Close unfinished failed rise if no successful retake and still below target.
    if in_rise and peak_ts is not None and peak_move is not None and peak_move <= target:
        attempts.append({
            "peak_timestamp": peak_ts,
            "peak_move": peak_move,
            "gap_to_target": target - peak_move,
        })

    return attempts


def v35_primary(degraded, attempts):
    best_gap = None
    prev_gap = None
    weakening_streak = 0

    for a in attempts:
        gap = a["gap_to_target"]

        if best_gap is None or gap < best_gap:
            best_gap = gap
            weakening_streak = 0
        else:
            if prev_gap is not None and gap > prev_gap:
                weakening_streak += 1
            else:
                weakening_streak = 0

        age = (
            parse_dt(a["peak_timestamp"]) -
            parse_dt(degraded["degraded_timestamp"])
        ).total_seconds() / 60.0

        if weakening_streak >= 1 and age >= 10:
            return a["peak_timestamp"]

        prev_gap = gap

    return None


def first_recovery(degraded, event, u, entry, terminal_ts):
    direction = event["direction"]
    target = degraded["target_move"]
    degraded_ts = degraded["degraded_timestamp"]

    for ts in sorted(u):
        if ts <= degraded_ts:
            continue
        if ts >= terminal_ts:
            break

        move = directional(direction, entry, u[ts]["close"])
        if move > target:
            return {
                "timestamp": ts,
                "target_move": target,
                "recovery_move": move,
            }

    return None


def v38_rescue(recovery, event, u, entry, terminal_ts):
    """
    Fixed V38_CAP50 rescue:
      first close back below recovery target after >=10 minutes,
      only if current directional points <= +50.
    """
    direction = event["direction"]
    rts = recovery["timestamp"]
    target = recovery["target_move"]

    for ts in sorted(u):
        if ts <= rts:
            continue
        if ts >= terminal_ts:
            break

        age = (parse_dt(ts) - parse_dt(rts)).total_seconds() / 60.0
        if age < 10:
            continue

        move = directional(direction, entry, u[ts]["close"])
        if move < target:
            if move <= 50:
                return {
                    "timestamp": ts,
                    "points": move,
                }
            # Frozen V38 checks the first qualifying rebreak structure;
            # if captured points are >50, rescue is skipped.
            return None

    return None


def milestone_timestamp(event, u, entry, terminal_ts, milestone):
    direction = event["direction"]

    for ts in sorted(u):
        if ts <= event["entry_timestamp"]:
            continue
        if ts >= terminal_ts:
            break

        fav = directional(direction, entry, favorable(direction, u[ts]))
        if fav >= milestone:
            return ts

    return None


def later_new_mfe(event, u, entry, exit_ts, terminal_ts):
    direction = event["direction"]
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


def score_row(name, vals, baseline=None):
    s = stats(vals)
    row = {
        "policy": name,
        "n": s["n"],
        "total_points": s["total"],
        "mean_points": s["mean"],
        "median_points": s["median"],
        "worst_points": s["min"],
        "best_points": s["max"],
        "max_drawdown_points": max_drawdown(vals),
    }

    if baseline is not None:
        ds = stats([v - b for v, b in zip(vals, baseline)])
        row.update({
            "delta_vs_baseline_total": ds["total"],
            "delta_vs_baseline_mean": ds["mean"],
            "delta_vs_baseline_median": ds["median"],
        })

    return row


def main():
    print("B FAMILY — V40 FROZEN V38_CAP50 HISTORICAL VALIDATION")
    print("=" * 118)
    print(f"validation_range={START_DATE}..{END_DATE}")

    underlying, ufiles = discover_underlying()
    futures, ffiles = discover_futures()
    events = discover_b_events()

    session_dates = sorted(
        set(underlying).intersection(futures)
    )

    print(f"dual_raw_sessions={len(session_dates)}")
    print(f"underlying_source_files={ufiles}")
    print(f"futures_source_files={ffiles}")
    print(f"discovered_b_event_keys={len(events)}")

    if not session_dates:
        raise SystemExit("STOP: no dual-valid raw sessions in V40 range")
    if not events:
        raise SystemExit("STOP: no B event rows discovered in V40 range")

    # Sort and dedupe B events.
    event_items = sorted(
        events.items(),
        key=lambda kv: (
            kv[0][0], kv[0][2], kv[0][1]
        )
    )

    validated_rows = []

    b_count = 0
    plus20_count = 0
    classified_count = 0
    rs_count = 0

    for _, (event, source) in event_items:
        d = event["session_date"]
        if d not in underlying or d not in futures:
            continue

        u = underlying[d]
        fut = futures[d]

        base = terminal_for_event(event, u)
        if base is None:
            continue

        b_count += 1
        entry = base["entry_close"]
        terminal_ts = base["terminal_timestamp"]

        plus20 = find_plus20(event, u, terminal_ts, entry)
        if not plus20:
            continue
        plus20_count += 1

        cls = classify_runner(
            event, plus20, u, fut, entry, terminal_ts
        )
        if cls is None:
            continue
        classified_count += 1

        if not cls["runner_strengthening"]:
            continue
        rs_count += 1

        degraded = first_degraded(
            event,
            cls["classification_timestamp"],
            u,
            fut,
            entry,
            terminal_ts,
        )

        primary_ts = None
        rescue_ts = None
        exit_type = "FALLBACK_BASELINE"
        exit_ts = None

        if degraded:
            attempts = failed_recovery_attempts(
                degraded, event, u, entry, terminal_ts
            )

            primary_ts = v35_primary(degraded, attempts)

            if primary_ts and primary_ts in u and primary_ts < terminal_ts:
                exit_ts = primary_ts
                exit_type = "V35_PRIMARY"
            else:
                recovery = first_recovery(
                    degraded, event, u, entry, terminal_ts
                )
                if recovery:
                    rescue = v38_rescue(
                        recovery, event, u, entry, terminal_ts
                    )
                    if rescue:
                        rescue_ts = rescue["timestamp"]
                        exit_ts = rescue_ts
                        exit_type = "V38_CAP50_RESCUE"

        if exit_ts:
            points = directional(
                event["direction"], entry, u[exit_ts]["close"]
            )
            later = later_new_mfe(
                event, u, entry, exit_ts, terminal_ts
            )
        else:
            points = base["baseline_points"]
            later = None

        row = {
            "session_date": d,
            "direction": event["direction"],
            "entry_timestamp": event["entry_timestamp"],
            "event_source": source,
            "plus20_timestamp": plus20,
            "classification_timestamp": cls["classification_timestamp"],
            "net_progress_10m": cls["net_progress_10m"],
            "directional_vwap_change_10m": cls["directional_vwap_change_10m"],
            "degraded_timestamp": (
                degraded["degraded_timestamp"] if degraded else None
            ),
            "exit_type": exit_type,
            "exit_timestamp": exit_ts,
            "baseline_terminal_type": base["terminal_type"],
            "baseline_terminal_timestamp": terminal_ts,
            "baseline_points": base["baseline_points"],
            "v38_points": points,
            "delta_vs_baseline": points - base["baseline_points"],
            "later_new_mfe": later,
        }

        for m in MILESTONES:
            mt = milestone_timestamp(
                event, u, entry, terminal_ts, m
            )
            row[f"plus{m}_timestamp"] = mt
            row[f"reached_plus{m}"] = mt is not None
            row[f"exit_before_plus{m}"] = bool(
                exit_ts and mt and exit_ts < mt
            )

        validated_rows.append(row)

    if not validated_rows:
        raise SystemExit(
            "STOP: no RUNNER_STRENGTHENING events reconstructed in V40 range"
        )

    baseline_vals = [r["baseline_points"] for r in validated_rows]
    v38_vals = [r["v38_points"] for r in validated_rows]

    baseline_score = score_row(
        "STRUCTURAL_OR_SESSION_CUTOFF",
        baseline_vals,
    )
    v38_score = score_row(
        "FROZEN_V38_CAP50",
        v38_vals,
        baseline_vals,
    )

    primary = sum(r["exit_type"] == "V35_PRIMARY" for r in validated_rows)
    rescue = sum(r["exit_type"] == "V38_CAP50_RESCUE" for r in validated_rows)
    fallback = len(validated_rows) - primary - rescue
    actual_exits = [r for r in validated_rows if r["exit_timestamp"]]
    later = sum(r["later_new_mfe"] is True for r in actual_exits)

    preservation = {}
    for m in MILESTONES:
        reached = [r for r in validated_rows if r[f"reached_plus{m}"]]
        cut = [r for r in reached if r[f"exit_before_plus{m}"]]
        preserved = len(reached) - len(cut)
        preservation[m] = {
            "reached": len(reached),
            "preserved": preserved,
            "rate": preserved / len(reached) if reached else None,
        }

    bs = stats(baseline_vals)
    vs = stats(v38_vals)
    delta = stats([v - b for v, b in zip(v38_vals, baseline_vals)])

    lines = [
        "B FAMILY — V40 FROZEN V38_CAP50 HISTORICAL VALIDATION",
        "=" * 118,
        f"validation_range={START_DATE}..{END_DATE}",
        f"dual_raw_sessions={len(session_dates)}",
        f"B_events_discovered={b_count}",
        f"B_events_reaching_plus20={plus20_count}",
        f"B_events_with_complete_V20_classifier={classified_count}",
        f"RUNNER_STRENGTHENING_events={rs_count}",
        f"validated_policy_events={len(validated_rows)}",
        "",
        "HISTORICAL VALIDATION SCORECARD",
        "-" * 118,
        f"BASELINE total={fmt(bs['total'])} mean={fmt(bs['mean'])} "
        f"median={fmt(bs['median'])} worst={fmt(bs['min'])} "
        f"best={fmt(bs['max'])} maxDD={fmt(max_drawdown(baseline_vals))}",
        f"V38_CAP50 total={fmt(vs['total'])} mean={fmt(vs['mean'])} "
        f"median={fmt(vs['median'])} worst={fmt(vs['min'])} "
        f"best={fmt(vs['max'])} maxDD={fmt(max_drawdown(v38_vals))}",
        f"V38 Δ vs baseline total={fmt(delta['total'])} "
        f"mean={fmt(delta['mean'])} median={fmt(delta['median'])}",
        "",
        "EXIT MIX",
        "-" * 118,
        f"V35 primary exits={primary}",
        f"V38 CAP50 rescues={rescue}",
        f"fallbacks={fallback}",
        "",
        "MILESTONE CHASE / PRESERVATION",
        "-" * 118,
    ]

    for m in MILESTONES:
        p = preservation[m]
        if p["rate"] is None:
            lines.append(f"+{m}: no qualifying runners")
        else:
            lines.append(
                f"+{m}: {p['preserved']}/{p['reached']} "
                f"({p['rate']*100:.1f}%)"
            )

    lines += [
        f"later new MFE after actual exit: {later}/{len(actual_exits)}",
        "",
        "DEVELOPMENT REFERENCE",
        "-" * 118,
        f"V38_CAP50 development total on 18 tuned events={fmt(DEV_V38_TOTAL)}",
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- V38_CAP50 was frozen before this run; V40 performs no tuning grid.",
        "- This 180-session block is date-separated from the V38 18-event tuning population.",
        "- It is NOT globally untouched because earlier B-family research used the canonical 180-session history.",
        "- Treat V40 as historical validation/stress evidence, not pristine OOS.",
        "- The untouched forward validation beginning 2026-09-29 remains important.",
        "- Underlying NIFTY directional points only; no option premium or rupee P&L.",
    ]

    report = {
        "version": "B_FAMILY_V40_FROZEN_V38_CAP50_VALIDATION",
        "range": {"start": START_DATE, "end": END_DATE},
        "dual_raw_sessions": len(session_dates),
        "b_events": b_count,
        "plus20_events": plus20_count,
        "classified_events": classified_count,
        "runner_strengthening_events": rs_count,
        "validated_events": len(validated_rows),
        "scorecard": [baseline_score, v38_score],
        "exit_mix": {
            "v35_primary": primary,
            "v38_rescue": rescue,
            "fallback": fallback,
        },
        "preservation": preservation,
        "later_new_mfe_count": later,
        "actual_exit_count": len(actual_exits),
        "methodology": {
            "frozen_before_run": True,
            "tuning_grid": False,
            "date_separated_from_v38_dev": True,
            "globally_untouched": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, validated_rows)
    write_csv(SCORECARD_CSV, [baseline_score, v38_score])
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENTS CSV   :", EVENTS_CSV)
    print("SCORECARD    :", SCORECARD_CSV)
    print("REPORT JSON  :", REPORT_JSON)
    print("SUMMARY      :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
