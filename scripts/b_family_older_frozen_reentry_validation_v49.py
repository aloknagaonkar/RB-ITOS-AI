#!/usr/bin/env python3
"""
B FAMILY — V49 OLDER 100-SESSION FROZEN RE-ENTRY VALIDATION

Goal
----
Validate the frozen Family B candidate on the most recent 100 dual-valid
historical sessions strictly BEFORE 2024-08-16.

Frozen candidate:
    PRIMARY_OFF + CAP20
    + ONE post-rescue re-entry when, within 20 minutes:
        1m CLOSE retakes degraded-start target
        AND directional futures-VWAP > rescue-time directional futures-VWAP
    Re-entry second leg exits only at original structural/session terminal.
    No second rescue. No repeated re-entry.

V49 performs NO tuning.

The script automatically:
1) discovers all underlying/futures sessions before 2024-08-16,
2) takes the most recent 100 dual-valid sessions,
3) discovers canonical B/event rows by schema,
4) reconstructs RUNNER_STRENGTHENING,
5) compares:
      BASELINE
      PRIMARY_OFF + CAP20
      PRIMARY_OFF + CAP20 + FROZEN REENTRY

Underlying NIFTY directional points only.
"""

from __future__ import annotations

import csv, json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

CUTOFF_DATE = "2024-08-16"
TARGET_SESSIONS = 100
REENTRY_WINDOW_MIN = 20
MILESTONES = (30, 40, 50, 75, 100)
SECOND_LEG_MILESTONES = (20, 30, 50, 75, 100)

OUTDIR = RESEARCH / "b-family-older-frozen-reentry-validation-v49"
EVENTS_CSV = OUTDIR / "events-v49.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v49.csv"
REPORT_JSON = OUTDIR / "report-v49.json"
SUMMARY_TXT = OUTDIR / "summary-v49.txt"

ALIASES = {
    "session_date": ("session_date", "date", "trade_date"),
    "direction": ("direction", "side", "signal_direction"),
    "entry_timestamp": ("entry_timestamp", "entry_time", "entry_ts"),
    "entry_close": ("entry_close", "entry_price", "entry_underlying_close"),
    "structural_invalidation_timestamp": (
        "structural_invalidation_timestamp",
        "invalidation_timestamp",
        "structural_exit_timestamp",
        "exit_timestamp",
    ),
    "plus20_timestamp": (
        "plus20_timestamp",
        "plus_20_timestamp",
        "p20_timestamp",
    ),
}


def load_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    return None if v in ("", None) else float(v)


def parse_dt(s):
    return datetime.fromisoformat(s)


def plus_minutes(ts, n):
    return (parse_dt(ts) + timedelta(minutes=n)).isoformat()


def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


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
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0, total=None, mean=None, median=None, min=None, max=None)
    return dict(
        n=len(xs), total=sum(xs), mean=mean(xs), median=median(xs),
        min=min(xs), max=max(xs)
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


def first_present(row, names):
    for n in names:
        if n in row and row.get(n) not in ("", None):
            return row.get(n)
    return None


def normalize_event_row(raw):
    r = dict(raw)
    for canon, aliases in ALIASES.items():
        v = first_present(raw, aliases)
        if v not in ("", None):
            r[canon] = v

    d = r.get("session_date")
    direction = str(r.get("direction", "")).upper()
    ets = r.get("entry_timestamp")

    if not d or not ets or direction not in ("BULLISH", "BEARISH"):
        return None

    r["direction"] = direction
    return r


def discover_underlying_all():
    by = defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows or not {
            "session_date", "timestamp", "open", "high", "low", "close"
        }.issubset(rows[0]):
            continue

        for r in rows:
            d = r["session_date"]
            if d < CUTOFF_DATE:
                by[d][r["timestamp"]] = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
    return dict(by)


def discover_futures_all():
    by = defaultdict(dict)
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
        }.issubset(rows[0]):
            continue

        for r in rows:
            d = r["session_date"]
            if d < CUTOFF_DATE and r.get("session_vwap") not in ("", None):
                by[d][r["timestamp"]] = {
                    "close": float(r["close"]),
                    "vwap": float(r["session_vwap"]),
                }
    return dict(by)


def discover_events(valid_dates):
    found = {}

    for p in RESEARCH.rglob("*.csv"):
        if "v49" in str(p).lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows:
            continue

        headers = set(rows[0])
        if not any(x in headers for x in ALIASES["session_date"]):
            continue
        if not any(x in headers for x in ALIASES["direction"]):
            continue
        if not any(x in headers for x in ALIASES["entry_timestamp"]):
            continue

        for raw in rows:
            r = normalize_event_row(raw)
            if not r or r["session_date"] not in valid_dates:
                continue

            event_like = any(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "plus20_timestamp",
                    "mfe", "mae", "candidate", "event_type", "setup_family",
                )
            )
            name_like = any(
                token in p.name.lower()
                for token in ("event", "candidate", "setup", "family", "canonical")
            )
            if not event_like and not name_like:
                continue

            k = (r["session_date"], r["direction"], r["entry_timestamp"])
            richness = sum(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "plus20_timestamp",
                    "mfe", "mae",
                    "observation_end_timestamp", "classification",
                )
            )

            if k not in found or richness > found[k][0]:
                found[k] = (richness, r, str(p))

    return {k: (v[1], v[2]) for k, v in found.items()}


def terminal_for_event(event, u):
    ets = event["entry_timestamp"]
    entry = f(event.get("entry_close"))

    if entry is None:
        if ets not in u:
            return None
        entry = u[ets]["close"]

    invalid = event.get("structural_invalidation_timestamp") or None
    trusted = sorted(u)

    if invalid and invalid in u:
        terminal = invalid
        terminal_type = "STRUCTURAL_INVALIDATION"
    else:
        terminal = trusted[-1]
        terminal_type = "SESSION_CUTOFF"

    baseline = directional(
        event["direction"], entry, u[terminal]["close"]
    )

    return {
        "entry_close": entry,
        "terminal_timestamp": terminal,
        "terminal_type": terminal_type,
        "baseline_points": baseline,
    }


def find_plus20(event, u, terminal, entry):
    src = event.get("plus20_timestamp")
    if src and src in u and src < terminal:
        return src

    for ts in sorted(u):
        if ts <= event["entry_timestamp"]:
            continue
        if ts >= terminal:
            break
        if directional(
            event["direction"], entry, favorable(event["direction"], u[ts])
        ) >= 20:
            return ts
    return None


def classify_runner(event, p20, u, fut, entry, terminal):
    cts = plus_minutes(p20, 10)
    if cts >= terminal or p20 not in u or cts not in u:
        return None
    if p20 not in fut or cts not in fut:
        return None

    d = event["direction"]
    net = (
        directional(d, entry, u[cts]["close"])
        - directional(d, entry, u[p20]["close"])
    )
    dv = (
        directional_vwap(d, fut[cts])
        - directional_vwap(d, fut[p20])
    )

    return {
        "classification_timestamp": cts,
        "net_progress_10m": net,
        "directional_vwap_change_10m": dv,
        "runner_strengthening": net > 0 and dv > 0,
    }


def first_degraded(event, cts, u, fut, entry, terminal):
    d = event["direction"]
    running = None
    prevdv = None
    prior_joint = False

    for ts in sorted(u):
        if ts <= event["entry_timestamp"]:
            continue
        if ts > cts or ts >= terminal:
            break
        move = directional(d, entry, u[ts]["close"])
        running = move if running is None else max(running, move)
        dv = directional_vwap(d, fut.get(ts))
        if dv is not None:
            prevdv = dv

    for ts in sorted(u):
        if ts <= cts:
            continue
        if ts >= terminal:
            break

        move = directional(d, entry, u[ts]["close"])
        running = move if running is None else max(running, move)
        dd = running - move

        dv = directional_vwap(d, fut.get(ts))
        dvc = None if dv is None or prevdv is None else dv - prevdv
        joint = dd > 0 and dvc is not None and dvc < 0

        if joint and not prior_joint:
            return {
                "degraded_timestamp": ts,
                "target_move": move,
            }

        prior_joint = joint
        if dv is not None:
            prevdv = dv

    return None


def first_recovery(degraded, event, u, entry, terminal):
    target = degraded["target_move"]
    dts = degraded["degraded_timestamp"]

    for ts in sorted(u):
        if ts <= dts:
            continue
        if ts >= terminal:
            break

        move = directional(event["direction"], entry, u[ts]["close"])
        if move > target:
            return ts

    return None


def cap20_rescue(degraded, recovery_ts, event, u, entry, terminal):
    target = degraded["target_move"]

    for ts in sorted(u):
        if ts <= recovery_ts:
            continue
        if ts >= terminal:
            break

        if mins(recovery_ts, ts) < 10:
            continue

        move = directional(event["direction"], entry, u[ts]["close"])
        if move < target:
            return ts if move <= 20 else None

    return None


def frozen_reentry(degraded, rescue_ts, event, u, fut, entry, terminal):
    rescue_dv = directional_vwap(
        event["direction"], fut.get(rescue_ts)
    )
    if rescue_dv is None:
        return None

    target = degraded["target_move"]

    for ts in sorted(u):
        if ts <= rescue_ts:
            continue
        if ts >= terminal:
            break

        age = mins(rescue_ts, ts)
        if age > REENTRY_WINDOW_MIN:
            break

        move = directional(
            event["direction"], entry, u[ts]["close"]
        )
        dv = directional_vwap(
            event["direction"], fut.get(ts)
        )

        if (
            move > target
            and dv is not None
            and dv > rescue_dv
        ):
            return ts

    return None


def second_leg_mfe(direction, reentry_price, reentry_ts, terminal, u):
    best = None

    for ts in sorted(u):
        if ts <= reentry_ts:
            continue
        if ts >= terminal:
            break

        fav = directional(
            direction,
            reentry_price,
            favorable(direction, u[ts]),
        )
        best = fav if best is None else max(best, fav)

    return best


def main():
    print("B FAMILY — V49 OLDER 100-SESSION FROZEN RE-ENTRY VALIDATION")
    print("=" * 118)

    uall = discover_underlying_all()
    fall = discover_futures_all()

    dual = sorted(set(uall).intersection(fall))
    if len(dual) < TARGET_SESSIONS:
        raise SystemExit(
            f"STOP: need {TARGET_SESSIONS} dual-valid sessions before "
            f"{CUTOFF_DATE}, found {len(dual)}"
        )

    selected = dual[-TARGET_SESSIONS:]
    selected_set = set(selected)

    print(f"available_dual_sessions_before_cutoff={len(dual)}")
    print(f"selected_sessions={len(selected)}")
    print(f"selected_range={selected[0]}..{selected[-1]}")

    events = discover_events(selected_set)
    print(f"discovered_event_keys={len(events)}")

    if not events:
        raise SystemExit("STOP: no event rows discovered in selected block")

    validated = []
    b_count = p20_count = class_count = rs_count = 0

    for _, (event, source) in sorted(
        events.items(),
        key=lambda kv: (kv[0][0], kv[0][2], kv[0][1]),
    ):
        d = event["session_date"]
        if d not in selected_set:
            continue

        u = uall[d]
        fut = fall[d]

        base = terminal_for_event(event, u)
        if base is None:
            continue

        b_count += 1
        entry = base["entry_close"]
        terminal = base["terminal_timestamp"]

        p20 = find_plus20(event, u, terminal, entry)
        if not p20:
            continue
        p20_count += 1

        cls = classify_runner(
            event, p20, u, fut, entry, terminal
        )
        if cls is None:
            continue
        class_count += 1

        if not cls["runner_strengthening"]:
            continue
        rs_count += 1

        degraded = first_degraded(
            event,
            cls["classification_timestamp"],
            u, fut, entry, terminal,
        )

        cap20_points = base["baseline_points"]
        rescue_ts = None
        reentry_ts = None
        reentry_points = 0.0
        second_mfe = None

        if degraded:
            recovery = first_recovery(
                degraded, event, u, entry, terminal
            )

            if recovery:
                rescue_ts = cap20_rescue(
                    degraded,
                    recovery,
                    event,
                    u,
                    entry,
                    terminal,
                )

            if rescue_ts:
                cap20_points = directional(
                    event["direction"],
                    entry,
                    u[rescue_ts]["close"],
                )

                reentry_ts = frozen_reentry(
                    degraded,
                    rescue_ts,
                    event,
                    u,
                    fut,
                    entry,
                    terminal,
                )

                if reentry_ts:
                    reentry_price = u[reentry_ts]["close"]
                    terminal_price = u[terminal]["close"]

                    reentry_points = directional(
                        event["direction"],
                        reentry_price,
                        terminal_price,
                    )

                    second_mfe = second_leg_mfe(
                        event["direction"],
                        reentry_price,
                        reentry_ts,
                        terminal,
                        u,
                    )

        combined_points = cap20_points + reentry_points

        row = {
            "session_date": d,
            "direction": event["direction"],
            "entry_timestamp": event["entry_timestamp"],
            "event_source": source,
            "baseline_points": base["baseline_points"],
            "cap20_points": cap20_points,
            "rescue_timestamp": rescue_ts,
            "reentry_timestamp": reentry_ts,
            "reentry_minutes_after_rescue": (
                mins(rescue_ts, reentry_ts)
                if rescue_ts and reentry_ts else None
            ),
            "second_leg_points": (
                reentry_points if reentry_ts else None
            ),
            "second_leg_mfe": second_mfe,
            "combined_points": combined_points,
            "delta_cap20_vs_baseline": (
                cap20_points - base["baseline_points"]
            ),
            "delta_reentry_vs_cap20": reentry_points,
            "delta_combined_vs_baseline": (
                combined_points - base["baseline_points"]
            ),
        }

        for m in SECOND_LEG_MILESTONES:
            row[f"second_leg_reached_plus{m}"] = bool(
                second_mfe is not None and second_mfe >= m
            )

        validated.append(row)

    if not validated:
        raise SystemExit(
            "STOP: no RUNNER_STRENGTHENING events validated"
        )

    baseline_vals = [r["baseline_points"] for r in validated]
    cap20_vals = [r["cap20_points"] for r in validated]
    combined_vals = [r["combined_points"] for r in validated]

    sb = stats(baseline_vals)
    sc = stats(cap20_vals)
    sr = stats(combined_vals)

    dcap = stats([
        c - b for c, b in zip(cap20_vals, baseline_vals)
    ])
    dre = stats([
        r - c for r, c in zip(combined_vals, cap20_vals)
    ])
    dcomb = stats([
        r - b for r, b in zip(combined_vals, baseline_vals)
    ])

    rescues = [r for r in validated if r["rescue_timestamp"]]
    reentries = [r for r in validated if r["reentry_timestamp"]]

    milestone_counts = {}
    for m in SECOND_LEG_MILESTONES:
        milestone_counts[m] = sum(
            r[f"second_leg_reached_plus{m}"]
            for r in reentries
        )

    lines = [
        "B FAMILY — V49 OLDER 100-SESSION FROZEN RE-ENTRY VALIDATION",
        "=" * 118,
        f"selected_range={selected[0]}..{selected[-1]}",
        f"selected_sessions={len(selected)}",
        f"B/event-like rows accepted={b_count}",
        f"events_reaching_plus20={p20_count}",
        f"events_with_complete_V20_classifier={class_count}",
        f"RUNNER_STRENGTHENING_events={rs_count}",
        f"validated_policy_events={len(validated)}",
        "",
        "SCORECARD",
        "-" * 118,
        f"BASELINE total={fmt(sb['total'])} "
        f"mean={fmt(sb['mean'])} median={fmt(sb['median'])} "
        f"worst={fmt(sb['min'])} maxDD={fmt(maxdd(baseline_vals))}",
        f"PRIMARY_OFF+CAP20 total={fmt(sc['total'])} "
        f"Δbase={fmt(dcap['total'])} "
        f"mean={fmt(sc['mean'])} median={fmt(sc['median'])} "
        f"worst={fmt(sc['min'])} maxDD={fmt(maxdd(cap20_vals))}",
        f"+ FROZEN REENTRY total={fmt(sr['total'])} "
        f"Δbase={fmt(dcomb['total'])} "
        f"ΔvsCAP20={fmt(dre['total'])} "
        f"mean={fmt(sr['mean'])} median={fmt(sr['median'])} "
        f"worst={fmt(sr['min'])} maxDD={fmt(maxdd(combined_vals))}",
        "",
        "EXIT / RE-ENTRY MIX",
        "-" * 118,
        f"CAP20_rescues={len(rescues)}",
        f"frozen_reentries={len(reentries)}",
        "",
        "RE-ENTRY SECOND-LEG MILESTONES",
        "-" * 118,
    ]

    for m in SECOND_LEG_MILESTONES:
        lines.append(
            f"+{m}: {milestone_counts[m]}/{len(reentries)}"
            if reentries else f"+{m}: no reentries"
        )

    lines += [
        "",
        "PER RE-ENTRY EVENT",
        "-" * 118,
    ]

    for r in reentries:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"reentryAfter={fmt(r['reentry_minutes_after_rescue'])}m "
            f"secondLeg={fmt(r['second_leg_points'])} "
            f"secondLegMFE={fmt(r['second_leg_mfe'])} "
            f"ΔvsCAP20={fmt(r['delta_reentry_vs_cap20'])}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- V49 performs no tuning.",
        "- The re-entry rule is frozen from V47/V48.",
        "- This block is older and date-separated from V47 and V48.",
        "- It may still overlap earlier broad B-family research, so do not call it globally pristine OOS.",
        "- Forward validation beginning 2026-09-29 remains the strongest untouched check.",
        "- Underlying NIFTY directional points only.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, validated)
    write_csv(SCORECARD_CSV, [
        {
            "policy": "BASELINE",
            "n": len(validated),
            "total_points": sb["total"],
            "mean_points": sb["mean"],
            "median_points": sb["median"],
            "worst_points": sb["min"],
            "max_drawdown_points": maxdd(baseline_vals),
        },
        {
            "policy": "PRIMARY_OFF_CAP20",
            "n": len(validated),
            "total_points": sc["total"],
            "mean_points": sc["mean"],
            "median_points": sc["median"],
            "worst_points": sc["min"],
            "max_drawdown_points": maxdd(cap20_vals),
            "delta_vs_baseline_total": dcap["total"],
        },
        {
            "policy": "PRIMARY_OFF_CAP20_PLUS_FROZEN_REENTRY",
            "n": len(validated),
            "total_points": sr["total"],
            "mean_points": sr["mean"],
            "median_points": sr["median"],
            "worst_points": sr["min"],
            "max_drawdown_points": maxdd(combined_vals),
            "delta_vs_baseline_total": dcomb["total"],
            "delta_vs_cap20_total": dre["total"],
        },
    ])

    REPORT_JSON.write_text(json.dumps({
        "version": "V49",
        "cutoff_date": CUTOFF_DATE,
        "selected_range": {
            "start": selected[0],
            "end": selected[-1],
        },
        "selected_sessions": len(selected),
        "validated_events": len(validated),
        "rescue_count": len(rescues),
        "reentry_count": len(reentries),
        "reentry_window_minutes": REENTRY_WINDOW_MIN,
        "scorecard": {
            "baseline": sb,
            "cap20": sc,
            "combined": sr,
            "delta_cap20_vs_baseline": dcap,
            "delta_reentry_vs_cap20": dre,
            "delta_combined_vs_baseline": dcomb,
        },
        "second_leg_milestones": milestone_counts,
        "methodology": {
            "tuning_grid": False,
            "reentry_rule_frozen_before_run": True,
            "globally_pristine_oos": False,
        },
    }, indent=2))

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENTS CSV  :", EVENTS_CSV)
    print("SCORECARD   :", SCORECARD_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
