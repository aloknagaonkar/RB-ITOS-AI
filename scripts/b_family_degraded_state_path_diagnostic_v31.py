#!/usr/bin/env python3
"""
B FAMILY — V31 DEGRADED-STATE / FAILED-RECOVERY DIAGNOSTIC

Purpose
-------
Descriptive follow-up to V30.

We reinterpret a V29-type deterioration signal as a DEGRADED-state trigger,
not as an exit.

For each of the 7 OOS V29-triggered RUNNER_STRENGTHENING events, start the
DEGRADED state at the V29 exit timestamp and follow the path until either:

  A) price retakes the V29 deterioration episode-start directional close level
     -> RECOVERED path

or

  B) canonical structural invalidation occurs before such a retake
     -> FAILED_RECOVERY path

This script does NOT define a production exit rule.
It does NOT tune thresholds.
It does NOT modify Family-B or V20 logic.

Measures during the degraded path:
- degraded-state duration
- worst directional close move
- maximum normalized damage relative to running MFE
- directional VWAP path
- number of failed price-retake attempts
- highest recovery attempt before terminal resolution
- time spacing between recovery attempts
- whether recovery attempts improve or weaken
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

V29_RUNNERS = (
    RESEARCH / "b-family-v29-runner-exit-oos-100"
    / "runner-exit-validation-v29.csv"
)

UNDERLYING = ROOT / "b-v29-pre-v23-100-underlying.csv"
FUTURES = ROOT / "b-v29-pre-v23-100-futures-vwap.csv"

OUTDIR = RESEARCH / "b-family-degraded-state-path-diagnostic-v31"
PATH_CSV = OUTDIR / "degraded-state-paths-v31.csv"
ATTEMPT_CSV = OUTDIR / "degraded-recovery-attempts-v31.csv"
REPORT_JSON = OUTDIR / "report-v31.json"
SUMMARY_TXT = OUTDIR / "summary-v31.txt"


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def f(v):
    if v in (None, ""):
        return None
    return float(v)


def b(v):
    return str(v).strip().lower() == "true"


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def directional_vwap(direction, close, vwap):
    raw = close - vwap
    return raw if direction == "BULLISH" else -raw


def favorable_price(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def load_csv(path):
    if not path.exists():
        raise SystemExit(f"STOP: missing input: {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def load_underlying():
    by = defaultdict(dict)
    for r in load_csv(UNDERLYING):
        by[r["session_date"]][r["timestamp"]] = {
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
    return dict(by)


def load_futures():
    by = defaultdict(dict)
    for r in load_csv(FUTURES):
        if r.get("session_vwap") in ("", None):
            continue
        by[r["session_date"]][r["timestamp"]] = {
            "close": float(r["close"]),
            "vwap": float(r["session_vwap"]),
        }
    return dict(by)


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


def attempt_peaks(path_rows, target_level):
    """
    Descriptive recovery attempts:
    contiguous local rises in directional close move while still below the
    episode-start target level.

    No magnitude threshold is used.
    """
    attempts = []

    if len(path_rows) < 2:
        return attempts

    in_rise = False
    start_idx = None
    peak_idx = None

    for i in range(1, len(path_rows)):
        prev = path_rows[i - 1]["directional_close_move"]
        cur = path_rows[i]["directional_close_move"]

        rising = cur > prev

        if rising and not in_rise:
            in_rise = True
            start_idx = i - 1
            peak_idx = i

        elif rising and in_rise:
            if cur >= path_rows[peak_idx]["directional_close_move"]:
                peak_idx = i

        elif not rising and in_rise:
            attempts.append((start_idx, peak_idx))
            in_rise = False
            start_idx = None
            peak_idx = None

    if in_rise:
        attempts.append((start_idx, peak_idx))

    out = []
    for n, (s, p) in enumerate(attempts, 1):
        start = path_rows[s]
        peak = path_rows[p]

        # Ignore a "recovery attempt" that already achieved the target.
        if peak["directional_close_move"] >= target_level:
            continue

        out.append({
            "attempt_number": n,
            "start_timestamp": start["timestamp"],
            "peak_timestamp": peak["timestamp"],
            "start_move": start["directional_close_move"],
            "peak_move": peak["directional_close_move"],
            "recovery_gain": (
                peak["directional_close_move"] - start["directional_close_move"]
            ),
            "gap_to_target_at_peak": target_level - peak["directional_close_move"],
        })
    return out


def analyze_event(ev, u, fut):
    direction = ev["direction"]
    entry = float(ev["entry_close"])
    degraded_ts = ev["v29_exit_timestamp"]
    episode_start_ts = ev["v29_episode_start_timestamp"]
    invalid_ts = ev.get("structural_invalidation_timestamp") or None

    if not degraded_ts:
        raise RuntimeError("V31 requires a V29-triggered event")

    episode_start_level = f(ev.get("v29_episode_start_move"))
    if episode_start_level is None:
        episode_start_level = directional(
            direction, entry, u[episode_start_ts]["close"]
        )

    # Running MFE through degraded-state start.
    running_mfe = None
    for ts in sorted(u):
        if ts <= ev["entry_timestamp"]:
            continue
        if ts > degraded_ts:
            break
        if invalid_ts and ts >= invalid_ts:
            break

        fav = directional(
            direction,
            entry,
            favorable_price(direction, u[ts]),
        )
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

    path = []
    recovered_ts = None

    for ts in sorted(u):
        if ts < degraded_ts:
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        bar = u[ts]
        close_move = directional(direction, entry, bar["close"])
        fav = directional(
            direction,
            entry,
            favorable_price(direction, bar),
        )
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        damage = running_mfe - close_move
        damage_frac = None
        if running_mfe not in (None, 0):
            damage_frac = damage / running_mfe

        frow = fut.get(ts)
        dvwap = None
        if frow:
            dvwap = directional_vwap(
                direction, frow["close"], frow["vwap"]
            )

        row = {
            "timestamp": ts,
            "directional_close_move": close_move,
            "running_mfe": running_mfe,
            "damage_from_running_mfe": damage,
            "damage_fraction_of_running_mfe": damage_frac,
            "directional_vwap": dvwap,
        }
        path.append(row)

        if close_move > episode_start_level:
            recovered_ts = ts
            break

    resolution = (
        "RECOVERED"
        if recovered_ts is not None
        else "FAILED_RECOVERY"
    )

    # For failed path, canonical invalidation is terminal boundary.
    terminal_ts = recovered_ts or invalid_ts
    terminal_move = None
    if terminal_ts and terminal_ts in u:
        terminal_move = directional(
            direction, entry, u[terminal_ts]["close"]
        )

    attempts = attempt_peaks(path, episode_start_level)

    # Enrich attempts with spacing and progression.
    attempt_rows = []
    prev_peak_ts = None
    prev_gap = None

    for a in attempts:
        spacing = None
        if prev_peak_ts is not None:
            spacing = mins(prev_peak_ts, a["peak_timestamp"])

        improvement = None
        if prev_gap is not None:
            improvement = prev_gap - a["gap_to_target_at_peak"]

        attempt_rows.append({
            "session_date": ev["session_date"],
            "direction": direction,
            "resolution": resolution,
            "degraded_timestamp": degraded_ts,
            **a,
            "minutes_from_degraded_to_peak": mins(
                degraded_ts, a["peak_timestamp"]
            ),
            "minutes_since_prior_attempt_peak": spacing,
            "gap_improvement_vs_prior_attempt": improvement,
        })

        prev_peak_ts = a["peak_timestamp"]
        prev_gap = a["gap_to_target_at_peak"]

    damage_stats = stats(
        r["damage_from_running_mfe"] for r in path
    )
    damage_frac_stats = stats(
        r["damage_fraction_of_running_mfe"] for r in path
    )
    vwap_stats = stats(
        r["directional_vwap"] for r in path
    )

    highest_attempt = (
        max(
            (a["peak_move"] for a in attempts),
            default=None,
        )
    )
    smallest_gap = (
        min(
            (a["gap_to_target_at_peak"] for a in attempts),
            default=None,
        )
    )

    improving_attempts = sum(
        1
        for a in attempt_rows
        if a["gap_improvement_vs_prior_attempt"] is not None
        and a["gap_improvement_vs_prior_attempt"] > 0
    )
    weakening_attempts = sum(
        1
        for a in attempt_rows
        if a["gap_improvement_vs_prior_attempt"] is not None
        and a["gap_improvement_vs_prior_attempt"] < 0
    )

    return {
        "validation_block": ev.get("validation_block"),
        "session_date": ev["session_date"],
        "direction": direction,
        "entry_timestamp": ev["entry_timestamp"],
        "classification_timestamp": ev.get("observation_end_timestamp"),
        "degraded_timestamp": degraded_ts,
        "episode_start_timestamp": episode_start_ts,
        "episode_start_directional_close_level": episode_start_level,
        "resolution": resolution,
        "recovery_timestamp": recovered_ts,
        "structural_invalidation_timestamp": invalid_ts,
        "terminal_timestamp": terminal_ts,
        "degraded_duration_minutes": (
            mins(degraded_ts, terminal_ts)
            if terminal_ts else None
        ),
        "terminal_directional_close_move": terminal_move,
        "path_rows": len(path),
        "worst_damage_points": damage_stats["max"],
        "median_damage_points": damage_stats["median"],
        "worst_damage_fraction": damage_frac_stats["max"],
        "median_damage_fraction": damage_frac_stats["median"],
        "directional_vwap_min": vwap_stats["min"],
        "directional_vwap_median": vwap_stats["median"],
        "directional_vwap_max": vwap_stats["max"],
        "recovery_attempt_count": len(attempt_rows),
        "highest_recovery_attempt_move": highest_attempt,
        "smallest_gap_to_episode_start_target": smallest_gap,
        "improving_attempt_count": improving_attempts,
        "weakening_attempt_count": weakening_attempts,
    }, attempt_rows


def main():
    print("B FAMILY — V31 DEGRADED-STATE / FAILED-RECOVERY DIAGNOSTIC")
    print("=" * 118)

    v29 = load_csv(V29_RUNNERS)
    v29 = [r for r in v29 if b(r.get("v29_exit_triggered"))]

    if len(v29) != 7:
        raise SystemExit(
            f"STOP: expected 7 V29-triggered runners, got {len(v29)}"
        )

    underlying = load_underlying()
    futures = load_futures()

    path_rows = []
    attempt_rows = []

    for i, ev in enumerate(v29, 1):
        d = ev["session_date"]

        if d not in underlying or d not in futures:
            raise SystemExit(f"STOP: missing raw data for {d}")

        path, attempts = analyze_event(
            ev, underlying[d], futures[d]
        )
        path_rows.append(path)
        attempt_rows.extend(attempts)

        print(
            f"{i:2d}/7 {d} {path['direction']} "
            f"resolution={path['resolution']} "
            f"duration={fmt(path['degraded_duration_minutes'])}m "
            f"worstDamage={fmt(path['worst_damage_points'])} "
            f"worstFrac={fmt(path['worst_damage_fraction'])} "
            f"attempts={path['recovery_attempt_count']} "
            f"improving={path['improving_attempt_count']} "
            f"weakening={path['weakening_attempt_count']}"
        )

    recovered = [r for r in path_rows if r["resolution"] == "RECOVERED"]
    failed = [r for r in path_rows if r["resolution"] == "FAILED_RECOVERY"]

    rec_duration = stats(r["degraded_duration_minutes"] for r in recovered)
    fail_duration = stats(r["degraded_duration_minutes"] for r in failed)

    rec_damage = stats(r["worst_damage_points"] for r in recovered)
    fail_damage = stats(r["worst_damage_points"] for r in failed)

    rec_frac = stats(r["worst_damage_fraction"] for r in recovered)
    fail_frac = stats(r["worst_damage_fraction"] for r in failed)

    rec_attempts = stats(r["recovery_attempt_count"] for r in recovered)
    fail_attempts = stats(r["recovery_attempt_count"] for r in failed)

    lines = [
        "B FAMILY — V31 DEGRADED-STATE / FAILED-RECOVERY DIAGNOSTIC",
        "=" * 118,
        f"degraded_paths={len(path_rows)}",
        f"recovered_paths={len(recovered)}",
        f"failed_recovery_paths={len(failed)}",
        "",
        "DEGRADED-STATE PATH COMPARISON",
        "-" * 118,
        f"Recovered duration: n={rec_duration['n']} median={fmt(rec_duration['median'])}m "
        f"mean={fmt(rec_duration['mean'])}m",
        f"Failed duration: n={fail_duration['n']} median={fmt(fail_duration['median'])}m "
        f"mean={fmt(fail_duration['mean'])}m",
        f"Recovered worst damage pts: median={fmt(rec_damage['median'])} "
        f"mean={fmt(rec_damage['mean'])}",
        f"Failed worst damage pts: median={fmt(fail_damage['median'])} "
        f"mean={fmt(fail_damage['mean'])}",
        f"Recovered worst damage fraction: median={fmt(rec_frac['median'])} "
        f"mean={fmt(rec_frac['mean'])}",
        f"Failed worst damage fraction: median={fmt(fail_frac['median'])} "
        f"mean={fmt(fail_frac['mean'])}",
        f"Recovered recovery-attempt count: median={fmt(rec_attempts['median'])} "
        f"mean={fmt(rec_attempts['mean'])}",
        f"Failed recovery-attempt count: median={fmt(fail_attempts['median'])} "
        f"mean={fmt(fail_attempts['mean'])}",
        "",
        "EVENT DETAILS",
        "-" * 118,
    ]

    for r in path_rows:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"{r['resolution']} "
            f"duration={fmt(r['degraded_duration_minutes'])}m "
            f"worstDamage={fmt(r['worst_damage_points'])} "
            f"worstFrac={fmt(r['worst_damage_fraction'])} "
            f"VWAPmin={fmt(r['directional_vwap_min'])} "
            f"attempts={r['recovery_attempt_count']} "
            f"bestAttempt={fmt(r['highest_recovery_attempt_move'])} "
            f"smallestGap={fmt(r['smallest_gap_to_episode_start_target'])} "
            f"improving={r['improving_attempt_count']} "
            f"weakening={r['weakening_attempt_count']}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- V29 remains rejected as an exit.",
        "- V29-type deterioration is treated only as a DEGRADED-state trigger.",
        "- V31 is descriptive only.",
        "- No failed-recovery exit rule is defined.",
        "- No duration / damage / attempt-count threshold is selected.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- Underlying NIFTY points only; not option-premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_DEGRADED_STATE_PATH_DIAGNOSTIC_V31",
        "degraded_path_count": len(path_rows),
        "recovered_path_count": len(recovered),
        "failed_recovery_path_count": len(failed),
        "paths": path_rows,
        "attempts": attempt_rows,
        "guards": {
            "v29_status": "REJECTED_AS_EXIT",
            "v29_type_signal_role": "DEGRADED_STATE_TRIGGER_ONLY",
            "new_exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(PATH_CSV, path_rows)
    write_csv(ATTEMPT_CSV, attempt_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("PATH CSV    :", PATH_CSV)
    print("ATTEMPT CSV :", ATTEMPT_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
