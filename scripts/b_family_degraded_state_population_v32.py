#!/usr/bin/env python3
"""
B FAMILY — V32 MULTI-BLOCK DEGRADED-STATE POPULATION STUDY

Purpose
-------
Expand the V31 degraded-state analysis across existing historical blocks
without tuning thresholds.

Frozen semantics retained
-------------------------
Family-B entry: unchanged.
V20 runner classifier: unchanged.
V29 exit: remains REJECTED.
V29-type signal: used only as DEGRADED-state trigger.

For every RUNNER_STRENGTHENING event in available historical blocks:
1. detect the first V29-type degraded trigger after V20 classification:
   drawdown_from_running_MFE_close > 0
   AND prior-minute directional futures-VWAP change < 0

2. follow the degraded path until:
   A) price retakes the degradation episode-start directional close level
      -> RECOVERED
   B) canonical structural invalidation occurs first
      -> FAILED_RECOVERY

3. measure:
   - degraded duration
   - worst damage points
   - worst damage / running MFE
   - recovery-attempt count
   - best recovery attempt
   - smallest gap to episode-start target
   - directional VWAP minimum/median
   - improving vs weakening attempts

No threshold search.
No exit rule.
No production code changes.

Expected blocks
---------------
This script discovers compatible historical event CSVs already present in the
repository and studies only events containing the frozen V20 classification
fields required for RUNNER_STRENGTHENING.

Raw underlying/futures sidecars are resolved by session date across known
historical datasets.
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

OUTDIR = RESEARCH / "b-family-degraded-state-population-v32"
PATH_CSV = OUTDIR / "degraded-state-population-v32.csv"
BLOCK_CSV = OUTDIR / "block-summary-v32.csv"
ATTEMPT_CSV = OUTDIR / "recovery-attempts-v32.csv"
REPORT_JSON = OUTDIR / "report-v32.json"
SUMMARY_TXT = OUTDIR / "summary-v32.txt"

# Known candidate event files from prior B-family research.
EVENT_CANDIDATES = [
    RESEARCH / "b-family-v29-runner-exit-oos-100" / "b-events-v29.csv",
    RESEARCH / "b-family-runner-strength-classifier-v24" / "b-events-v24.csv",
    RESEARCH / "b-family-runner-strength-classifier-v23" / "b-events-v23.csv",
    RESEARCH / "b-family-runner-strength-classifier-v22" / "b-events-v22.csv",
    RESEARCH / "b-family-runner-tempo-v17" / "b-events-v17.csv",
]

# Known raw historical datasets. Additional matching CSVs are auto-discovered.
UNDERLYING_PATTERNS = [
    ROOT / "b-v29-pre-v23-100-underlying.csv",
]
FUTURES_PATTERNS = [
    ROOT / "b-v29-pre-v23-100-futures-vwap.csv",
]


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
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


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


def discover_event_files():
    found = []
    seen = set()

    for p in EVENT_CANDIDATES:
        if p.exists() and p not in seen:
            found.append(p)
            seen.add(p)

    for p in RESEARCH.rglob("*.csv"):
        name = p.name.lower()
        if "b-event" in name or "b_events" in name or name.startswith("b-events"):
            if p not in seen:
                found.append(p)
                seen.add(p)

    return found


def discover_raw_files():
    u = []
    fts = []

    for p in UNDERLYING_PATTERNS:
        if p.exists():
            u.append(p)

    for p in FUTURES_PATTERNS:
        if p.exists():
            fts.append(p)

    for p in ROOT.rglob("*.csv"):
        name = p.name.lower()
        if "underlying" in name and p not in u:
            u.append(p)
        if ("futures" in name and "vwap" in name) and p not in fts:
            fts.append(p)

    return u, fts


def load_underlying(files):
    by = defaultdict(dict)
    source = defaultdict(dict)

    for path in files:
        try:
            rows = load_csv(path)
        except Exception:
            continue

        needed = {"session_date", "timestamp", "open", "high", "low", "close"}
        if not rows or not needed.issubset(rows[0].keys()):
            continue

        for r in rows:
            d = r["session_date"]
            ts = r["timestamp"]
            rec = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            by[d][ts] = rec
            source[d][ts] = str(path)

    return dict(by), source


def load_futures(files):
    by = defaultdict(dict)
    source = defaultdict(dict)

    for path in files:
        try:
            rows = load_csv(path)
        except Exception:
            continue

        if not rows:
            continue

        keys = rows[0].keys()
        if not {"session_date", "timestamp", "close"}.issubset(keys):
            continue
        if "session_vwap" not in keys:
            continue

        for r in rows:
            if r.get("session_vwap") in ("", None):
                continue
            d = r["session_date"]
            ts = r["timestamp"]
            by[d][ts] = {
                "close": float(r["close"]),
                "vwap": float(r["session_vwap"]),
            }
            source[d][ts] = str(path)

    return dict(by), source


def extract_runner_events(event_files):
    out = []
    seen = set()

    for path in event_files:
        try:
            rows = load_csv(path)
        except Exception:
            continue

        for r in rows:
            if r.get("classification") != "RUNNER_STRENGTHENING":
                continue

            required = [
                "session_date",
                "direction",
                "entry_timestamp",
                "entry_close",
                "observation_end_timestamp",
            ]
            if any(r.get(k) in ("", None) for k in required):
                continue

            key = (
                r["session_date"],
                r["direction"],
                r["entry_timestamp"],
            )
            if key in seen:
                continue
            seen.add(key)

            rr = dict(r)
            rr["_event_source"] = str(path)
            out.append(rr)

    out.sort(key=lambda x: (x["session_date"], x["entry_timestamp"], x["direction"]))
    return out


def attempt_peaks(path_rows, target_level):
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
        if peak["directional_close_move"] >= target_level:
            continue

        out.append({
            "attempt_number": n,
            "start_timestamp": start["timestamp"],
            "peak_timestamp": peak["timestamp"],
            "start_move": start["directional_close_move"],
            "peak_move": peak["directional_close_move"],
            "recovery_gain": peak["directional_close_move"] - start["directional_close_move"],
            "gap_to_target_at_peak": target_level - peak["directional_close_move"],
        })

    return out


def detect_first_degraded(ev, u, fut):
    direction = ev["direction"]
    entry = float(ev["entry_close"])
    class_ts = ev["observation_end_timestamp"]
    invalid_ts = ev.get("structural_invalidation_timestamp") or None

    timestamps = [
        ts for ts in sorted(u)
        if ts >= class_ts and (not invalid_ts or ts < invalid_ts)
    ]

    running_mfe = None
    prev_dvwap = None
    prior_joint = False

    # Seed running MFE from entry through classification.
    for ts in sorted(u):
        if ts <= ev["entry_timestamp"]:
            continue
        if ts > class_ts:
            break
        fav = directional(direction, entry, favorable_price(direction, u[ts]))
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        frow = fut.get(ts)
        if frow:
            prev_dvwap = directional_vwap(direction, frow["close"], frow["vwap"])

    for ts in timestamps:
        bar = u[ts]
        fav = directional(direction, entry, favorable_price(direction, bar))
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        close_move = directional(direction, entry, bar["close"])
        drawdown = running_mfe - close_move

        frow = fut.get(ts)
        dvwap = None
        if frow:
            dvwap = directional_vwap(direction, frow["close"], frow["vwap"])

        vwap_change_prior = None
        if dvwap is not None and prev_dvwap is not None:
            vwap_change_prior = dvwap - prev_dvwap

        joint = (
            drawdown > 0
            and vwap_change_prior is not None
            and vwap_change_prior < 0
        )

        if joint and not prior_joint:
            return {
                "degraded_timestamp": ts,
                "episode_start_directional_close_level": close_move,
                "running_mfe_at_degraded": running_mfe,
            }

        prior_joint = joint
        if dvwap is not None:
            prev_dvwap = dvwap

    return None


def analyze_path(ev, degraded, u, fut):
    direction = ev["direction"]
    entry = float(ev["entry_close"])
    degraded_ts = degraded["degraded_timestamp"]
    target = degraded["episode_start_directional_close_level"]
    invalid_ts = ev.get("structural_invalidation_timestamp") or None

    running_mfe = degraded["running_mfe_at_degraded"]
    path = []
    recovered_ts = None

    for ts in sorted(u):
        if ts < degraded_ts:
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        bar = u[ts]
        close_move = directional(direction, entry, bar["close"])
        fav = directional(direction, entry, favorable_price(direction, bar))
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        damage = running_mfe - close_move
        damage_frac = None if running_mfe in (None, 0) else damage / running_mfe

        frow = fut.get(ts)
        dvwap = None
        if frow:
            dvwap = directional_vwap(direction, frow["close"], frow["vwap"])

        path.append({
            "timestamp": ts,
            "directional_close_move": close_move,
            "running_mfe": running_mfe,
            "damage_from_running_mfe": damage,
            "damage_fraction_of_running_mfe": damage_frac,
            "directional_vwap": dvwap,
        })

        if close_move > target:
            recovered_ts = ts
            break

    resolution = "RECOVERED" if recovered_ts else "FAILED_RECOVERY"
    terminal_ts = recovered_ts or invalid_ts

    attempts = attempt_peaks(path, target)
    attempt_rows = []
    prev_peak_ts = None
    prev_gap = None

    for a in attempts:
        spacing = None if prev_peak_ts is None else mins(prev_peak_ts, a["peak_timestamp"])
        improvement = None if prev_gap is None else prev_gap - a["gap_to_target_at_peak"]

        attempt_rows.append({
            "session_date": ev["session_date"],
            "direction": direction,
            "entry_timestamp": ev["entry_timestamp"],
            "resolution": resolution,
            "degraded_timestamp": degraded_ts,
            **a,
            "minutes_from_degraded_to_peak": mins(degraded_ts, a["peak_timestamp"]),
            "minutes_since_prior_attempt_peak": spacing,
            "gap_improvement_vs_prior_attempt": improvement,
        })

        prev_peak_ts = a["peak_timestamp"]
        prev_gap = a["gap_to_target_at_peak"]

    damage = stats(r["damage_from_running_mfe"] for r in path)
    frac = stats(r["damage_fraction_of_running_mfe"] for r in path)
    vwap = stats(r["directional_vwap"] for r in path)

    highest_attempt = max((a["peak_move"] for a in attempts), default=None)
    smallest_gap = min((a["gap_to_target_at_peak"] for a in attempts), default=None)

    improving = sum(
        1 for a in attempt_rows
        if a["gap_improvement_vs_prior_attempt"] is not None
        and a["gap_improvement_vs_prior_attempt"] > 0
    )
    weakening = sum(
        1 for a in attempt_rows
        if a["gap_improvement_vs_prior_attempt"] is not None
        and a["gap_improvement_vs_prior_attempt"] < 0
    )

    return {
        "session_date": ev["session_date"],
        "direction": direction,
        "entry_timestamp": ev["entry_timestamp"],
        "classification_timestamp": ev["observation_end_timestamp"],
        "event_source": ev["_event_source"],
        "degraded_timestamp": degraded_ts,
        "episode_start_directional_close_level": target,
        "resolution": resolution,
        "recovery_timestamp": recovered_ts,
        "structural_invalidation_timestamp": invalid_ts,
        "terminal_timestamp": terminal_ts,
        "degraded_duration_minutes": (
            mins(degraded_ts, terminal_ts) if terminal_ts else None
        ),
        "path_rows": len(path),
        "worst_damage_points": damage["max"],
        "median_damage_points": damage["median"],
        "worst_damage_fraction": frac["max"],
        "median_damage_fraction": frac["median"],
        "directional_vwap_min": vwap["min"],
        "directional_vwap_median": vwap["median"],
        "directional_vwap_max": vwap["max"],
        "recovery_attempt_count": len(attempt_rows),
        "highest_recovery_attempt_move": highest_attempt,
        "smallest_gap_to_episode_start_target": smallest_gap,
        "improving_attempt_count": improving,
        "weakening_attempt_count": weakening,
    }, attempt_rows


def block_name(source):
    p = Path(source)
    return p.parent.name


def main():
    print("B FAMILY — V32 MULTI-BLOCK DEGRADED-STATE POPULATION STUDY")
    print("=" * 118)

    event_files = discover_event_files()
    raw_u_files, raw_f_files = discover_raw_files()

    print(f"event_files_discovered={len(event_files)}")
    print(f"underlying_files_discovered={len(raw_u_files)}")
    print(f"futures_files_discovered={len(raw_f_files)}")

    if not event_files:
        raise SystemExit("STOP: no compatible B-event CSV files discovered")

    underlying, _ = load_underlying(raw_u_files)
    futures, _ = load_futures(raw_f_files)

    runners = extract_runner_events(event_files)
    print(f"runner_strengthening_events_discovered={len(runners)}")

    if not runners:
        raise SystemExit("STOP: no RUNNER_STRENGTHENING events discovered")

    population = []
    attempts_all = []
    skipped_missing_raw = []
    skipped_no_degraded = []

    for i, ev in enumerate(runners, 1):
        d = ev["session_date"]

        if d not in underlying or d not in futures:
            skipped_missing_raw.append({
                "session_date": d,
                "direction": ev["direction"],
                "entry_timestamp": ev["entry_timestamp"],
                "event_source": ev["_event_source"],
            })
            continue

        degraded = detect_first_degraded(ev, underlying[d], futures[d])
        if degraded is None:
            skipped_no_degraded.append({
                "session_date": d,
                "direction": ev["direction"],
                "entry_timestamp": ev["entry_timestamp"],
                "event_source": ev["_event_source"],
            })
            continue

        row, attempts = analyze_path(
            ev, degraded, underlying[d], futures[d]
        )
        row["block"] = block_name(ev["_event_source"])
        population.append(row)

        for a in attempts:
            a["block"] = row["block"]
            attempts_all.append(a)

        print(
            f"{i:3d}/{len(runners)} {d} {row['direction']} "
            f"block={row['block']} "
            f"{row['resolution']} "
            f"dur={fmt(row['degraded_duration_minutes'])}m "
            f"damageFrac={fmt(row['worst_damage_fraction'])} "
            f"attempts={row['recovery_attempt_count']}"
        )

    if not population:
        raise SystemExit(
            "STOP: no degraded-state paths could be reconstructed. "
            "Check historical raw sidecars."
        )

    recovered = [r for r in population if r["resolution"] == "RECOVERED"]
    failed = [r for r in population if r["resolution"] == "FAILED_RECOVERY"]

    blocks = sorted(set(r["block"] for r in population))
    block_rows = []

    for block in blocks:
        rr = [r for r in population if r["block"] == block]
        rec = [r for r in rr if r["resolution"] == "RECOVERED"]
        fail = [r for r in rr if r["resolution"] == "FAILED_RECOVERY"]

        block_rows.append({
            "block": block,
            "paths": len(rr),
            "recovered": len(rec),
            "failed_recovery": len(fail),
            "recovered_duration_median": stats(
                r["degraded_duration_minutes"] for r in rec
            )["median"],
            "failed_duration_median": stats(
                r["degraded_duration_minutes"] for r in fail
            )["median"],
            "recovered_worst_damage_fraction_median": stats(
                r["worst_damage_fraction"] for r in rec
            )["median"],
            "failed_worst_damage_fraction_median": stats(
                r["worst_damage_fraction"] for r in fail
            )["median"],
            "recovered_attempt_count_median": stats(
                r["recovery_attempt_count"] for r in rec
            )["median"],
            "failed_attempt_count_median": stats(
                r["recovery_attempt_count"] for r in fail
            )["median"],
        })

    lines = [
        "B FAMILY — V32 MULTI-BLOCK DEGRADED-STATE POPULATION STUDY",
        "=" * 118,
        f"runner_strengthening_events_discovered={len(runners)}",
        f"degraded_paths_reconstructed={len(population)}",
        f"recovered_paths={len(recovered)}",
        f"failed_recovery_paths={len(failed)}",
        f"skipped_missing_raw={len(skipped_missing_raw)}",
        f"skipped_no_degraded_trigger={len(skipped_no_degraded)}",
        "",
        "OVERALL POPULATION",
        "-" * 118,
    ]

    for label, rows in (("RECOVERED", recovered), ("FAILED_RECOVERY", failed)):
        dur = stats(r["degraded_duration_minutes"] for r in rows)
        dmg = stats(r["worst_damage_points"] for r in rows)
        frac = stats(r["worst_damage_fraction"] for r in rows)
        att = stats(r["recovery_attempt_count"] for r in rows)
        gap = stats(r["smallest_gap_to_episode_start_target"] for r in rows)

        lines.append(
            f"{label}: n={len(rows)} "
            f"duration_med={fmt(dur['median'])}m "
            f"damage_med={fmt(dmg['median'])} "
            f"damageFrac_med={fmt(frac['median'])} "
            f"attempts_med={fmt(att['median'])} "
            f"smallestGap_med={fmt(gap['median'])}"
        )

    lines += [
        "",
        "BLOCK SUMMARY",
        "-" * 118,
    ]

    for r in block_rows:
        lines.append(
            f"{r['block']}: paths={r['paths']} "
            f"recovered={r['recovered']} "
            f"failed={r['failed_recovery']} "
            f"recDurMed={fmt(r['recovered_duration_median'])} "
            f"failDurMed={fmt(r['failed_duration_median'])} "
            f"recFracMed={fmt(r['recovered_worst_damage_fraction_median'])} "
            f"failFracMed={fmt(r['failed_worst_damage_fraction_median'])}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Multi-block descriptive population study only.",
        "- No threshold search.",
        "- No failed-recovery exit rule selected.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- V29 remains rejected as an exit.",
        "- V29-type signal is used only as a DEGRADED-state trigger.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_DEGRADED_STATE_POPULATION_V32",
        "runner_strengthening_events_discovered": len(runners),
        "degraded_paths_reconstructed": len(population),
        "recovered_paths": len(recovered),
        "failed_recovery_paths": len(failed),
        "skipped_missing_raw": skipped_missing_raw,
        "skipped_no_degraded_trigger": skipped_no_degraded,
        "blocks": block_rows,
        "guards": {
            "threshold_search": False,
            "exit_rule_defined": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "v29_status": "REJECTED_AS_EXIT",
            "v29_signal_role": "DEGRADED_STATE_TRIGGER_ONLY",
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(PATH_CSV, population)
    write_csv(BLOCK_CSV, block_rows)
    write_csv(ATTEMPT_CSV, attempts_all)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("PATH CSV    :", PATH_CSV)
    print("BLOCK CSV   :", BLOCK_CSV)
    print("ATTEMPT CSV :", ATTEMPT_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
