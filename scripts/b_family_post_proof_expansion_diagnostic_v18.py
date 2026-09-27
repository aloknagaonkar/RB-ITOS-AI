#!/usr/bin/env python3
"""
B FAMILY — POST-PROOF EXPANSION DIAGNOSTIC V18

Purpose
-------
Study whether causal information available shortly AFTER Family-B first proves
itself at +20 points differs between:

  A) B events that later reach >= +75 canonical MFE
  B) B events that reach +20 but never reach +75

This is descriptive research only.

IMPORTANT
---------
- Frozen canonical Family-B entry is unchanged.
- No exit rule is changed.
- No threshold search is performed.
- Future >=75 label is used ONLY as an outcome label after features are built.
- Features use only data available in fixed windows after +20:
    +3 minutes
    +5 minutes
    +10 minutes
- Windows that run past structural invalidation/session cutoff are marked
  INCOMPLETE and are not silently truncated into the complete-window comparison.
- Underlying NIFTY points only; not CE/PE premium P&L.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-post-proof-expansion-diagnostic-v18"
)
EVENTS_CSV = OUTDIR / "post-proof-events-v18.csv"
WINDOWS_CSV = OUTDIR / "post-proof-windows-v18.csv"
SUMMARY_CSV = OUTDIR / "post-proof-group-summary-v18.csv"
REPORT_JSON = OUTDIR / "report-v18.json"
SUMMARY_TXT = OUTDIR / "summary-v18.txt"

EXPECTED_B_TOTAL = 45
PROOF_POINTS = 20.0
RUNNER_THRESHOLD = 75.0
WINDOWS = (3, 5, 10)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_dt(ts):
    from datetime import datetime
    return datetime.fromisoformat(ts)


def minute_key(dt):
    return dt.isoformat()


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable_move(direction, entry, bar):
    px = float(bar["high"]) if direction == "BULLISH" else float(bar["low"])
    return directional(direction, entry, px)


def adverse_side_move(direction, entry, bar):
    px = float(bar["low"]) if direction == "BULLISH" else float(bar["high"])
    return directional(direction, entry, px)


def directional_close(direction, entry, bar):
    return directional(direction, entry, float(bar["close"]))


def first_proof_20(ev, u, canon):
    """
    First post-entry trusted 1m bar whose favorable intrabar excursion from entry
    reaches +20, stopping before structural invalidation.
    """
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    direction = ev["direction"]
    invalid_ts = ev.get("structural_invalidation_timestamp")

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not canon.is_trusted(ts):
            continue
        if invalid_ts and ts >= invalid_ts:
            break
        if favorable_move(direction, entry, u[ts]) >= PROOF_POINTS:
            return ts
    return None


def confirmed_supportive_swing_count(direction, rows):
    """
    Descriptive causal radius-1 supportive swing count inside the window.

    Bullish: confirmed swing lows; count those higher than previous confirmed low.
    Bearish: confirmed swing highs; count those lower than previous confirmed high.

    A pivot at i is confirmed only once the next bar is present.
    """
    pivots = []

    for i in range(1, len(rows) - 1):
        _, prev = rows[i - 1]
        ts, cur = rows[i]
        _, nxt = rows[i + 1]

        if direction == "BULLISH":
            p = float(cur["low"])
            if p < float(prev["low"]) and p < float(nxt["low"]):
                pivots.append((ts, p))
        else:
            p = float(cur["high"])
            if p > float(prev["high"]) and p > float(nxt["high"]):
                pivots.append((ts, p))

    if not pivots:
        return 0, 0

    advancing = 0
    for (_, prior), (_, current) in zip(pivots, pivots[1:]):
        if direction == "BULLISH" and current > prior:
            advancing += 1
        elif direction == "BEARISH" and current < prior:
            advancing += 1

    return len(pivots), advancing


def futures_directional_diff(direction, fut_row):
    if not fut_row:
        return None
    d = fut_row.get("diff")
    if d is None:
        return None
    d = float(d)
    return d if direction == "BULLISH" else -d


def build_window(ev, u, fut, proof_ts, minutes, proof_atr, canon):
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    direction = ev["direction"]
    invalid_ts = ev.get("structural_invalidation_timestamp")

    proof_dt = parse_dt(proof_ts)
    end_ts = minute_key(proof_dt + timedelta(minutes=minutes))

    # Complete-window gate.
    if not canon.is_trusted(end_ts):
        return {
            "window_minutes": minutes,
            "complete": False,
            "incomplete_reason": "WINDOW_END_AFTER_TRUSTED_CUTOFF",
        }

    if invalid_ts and end_ts >= invalid_ts:
        return {
            "window_minutes": minutes,
            "complete": False,
            "incomplete_reason": "STRUCTURAL_INVALIDATION_BEFORE_WINDOW_END",
        }

    expected = [
        minute_key(proof_dt + timedelta(minutes=i))
        for i in range(0, minutes + 1)
    ]
    missing = [ts for ts in expected if ts not in u]
    if missing:
        return {
            "window_minutes": minutes,
            "complete": False,
            "incomplete_reason": f"MISSING_UNDERLYING_MINUTES:{len(missing)}",
        }

    rows = [(ts, u[ts]) for ts in expected]
    post_rows = rows[1:]  # strictly after proof bar

    proof_bar = u[proof_ts]
    end_bar = u[end_ts]

    proof_close_move = directional_close(direction, entry, proof_bar)
    end_close_move = directional_close(direction, entry, end_bar)

    max_fav = max(
        [PROOF_POINTS]
        + [favorable_move(direction, entry, bar) for _, bar in post_rows]
    )
    min_path = min(
        [adverse_side_move(direction, entry, proof_bar)]
        + [adverse_side_move(direction, entry, bar) for _, bar in post_rows]
    )

    # Pullback relative to the +20 proof level. This is not a stop rule.
    max_pullback_from_proof = max(0.0, PROOF_POINTS - min_path)
    additional_favorable = max_fav - PROOF_POINTS
    net_from_proof_close = end_close_move - PROOF_POINTS

    advancing_closes = 0
    prior_close = float(proof_bar["close"])
    for _, bar in post_rows:
        cur = float(bar["close"])
        if direction == "BULLISH":
            advancing_closes += int(cur > prior_close)
        else:
            advancing_closes += int(cur < prior_close)
        prior_close = cur

    pivot_count, supportive_advancing_swings = confirmed_supportive_swing_count(
        direction, rows
    )

    proof_vwap = futures_directional_diff(direction, fut.get(proof_ts))
    end_vwap = futures_directional_diff(direction, fut.get(end_ts))
    vwap_change = (
        end_vwap - proof_vwap
        if proof_vwap is not None and end_vwap is not None
        else None
    )

    atr_norm_additional = (
        additional_favorable / float(proof_atr)
        if proof_atr not in (None, 0)
        else None
    )
    atr_norm_pullback = (
        max_pullback_from_proof / float(proof_atr)
        if proof_atr not in (None, 0)
        else None
    )

    return {
        "window_minutes": minutes,
        "complete": True,
        "incomplete_reason": None,
        "proof_timestamp": proof_ts,
        "window_end_timestamp": end_ts,
        "proof_close_move": proof_close_move,
        "end_close_move": end_close_move,
        "additional_favorable_after_proof": additional_favorable,
        "max_pullback_from_proof": max_pullback_from_proof,
        "net_from_proof_to_window_end": net_from_proof_close,
        "advancing_closes": advancing_closes,
        "advancing_close_pct": 100.0 * advancing_closes / minutes,
        "confirmed_swing_count": pivot_count,
        "supportive_advancing_swing_count": supportive_advancing_swings,
        "proof_directional_vwap_diff": proof_vwap,
        "end_directional_vwap_diff": end_vwap,
        "directional_vwap_diff_change": vwap_change,
        "proof_atr": proof_atr,
        "atr_norm_additional_favorable": atr_norm_additional,
        "atr_norm_pullback": atr_norm_pullback,
    }


def qstats(values):
    xs = sorted(float(x) for x in values if x not in (None, ""))
    if not xs:
        return {
            "n": 0, "mean": None, "median": None,
            "p25": None, "p75": None, "min": None, "max": None,
        }

    def q(p):
        return xs[round((len(xs) - 1) * p)]

    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "p25": q(0.25),
        "p75": q(0.75),
        "min": xs[0],
        "max": xs[-1],
    }


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


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def main():
    print("B FAMILY — POST-PROOF EXPANSION DIAGNOSTIC V18")
    print("=" * 118)

    c = import_module(CANON, "canonical_b_v18")
    r8 = import_module(V8_2, "risk_v8_2_v18")

    _, framework = c.load_framework()
    _, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    events = []
    for e in framework:
        d = e["session_date"]
        b = c.family_b_for_event(
            e,
            underlying.get(d, {}),
            futures.get(d, {}),
        )
        if b:
            events.append(c.measure_event(dict(b), underlying[d]))

    if len(events) != EXPECTED_B_TOTAL or dup_conflicts != 0:
        raise SystemExit(
            f"STOP: canonical parity failed "
            f"events={len(events)} dup_conflicts={dup_conflicts}"
        )

    event_rows = []
    window_rows = []

    for ev in events:
        d = ev["session_date"]
        u = underlying[d]
        fut = futures.get(d, {})

        proof_ts = first_proof_20(ev, u, c)
        reached_20 = proof_ts is not None
        future_runner_75 = (
            ev.get("mfe") is not None and float(ev["mfe"]) >= RUNNER_THRESHOLD
        )

        proof_atr = (
            r8.causal_atr_1m(u, proof_ts)
            if proof_ts is not None
            else None
        )

        event_row = {
            "session_date": d,
            "direction": ev["direction"],
            "entry_timestamp": ev["entry_timestamp"],
            "origin_timestamp": ev["origin_timestamp"],
            "delay_minutes": ev["delay_minutes"],
            "entry_close": ev.get("entry_close"),
            "canonical_mfe": ev.get("mfe"),
            "canonical_mae": ev.get("mae"),
            "structural_invalidation_timestamp": ev.get(
                "structural_invalidation_timestamp"
            ),
            "reached_plus20": reached_20,
            "proof20_timestamp": proof_ts,
            "proof_atr": proof_atr,
            "future_runner_75": future_runner_75,
            "outcome_group": (
                "FUTURE_GE75_RUNNER"
                if future_runner_75
                else "FUTURE_LT75"
            ),
        }
        event_rows.append(event_row)

        if proof_ts is None:
            continue

        for w in WINDOWS:
            wr = build_window(
                ev,
                u,
                fut,
                proof_ts,
                w,
                proof_atr,
                c,
            )
            wr.update({
                "session_date": d,
                "direction": ev["direction"],
                "entry_timestamp": ev["entry_timestamp"],
                "canonical_mfe": ev.get("mfe"),
                "canonical_mae": ev.get("mae"),
                "future_runner_75": future_runner_75,
                "outcome_group": (
                    "FUTURE_GE75_RUNNER"
                    if future_runner_75
                    else "FUTURE_LT75"
                ),
            })
            window_rows.append(wr)

    plus20_events = [r for r in event_rows if r["reached_plus20"]]
    plus20_runners = [r for r in plus20_events if r["future_runner_75"]]
    plus20_nonrunners = [r for r in plus20_events if not r["future_runner_75"]]

    print("Canonical B events        :", len(events))
    print("B events reaching +20     :", len(plus20_events))
    print("  future >=75 runners     :", len(plus20_runners))
    print("  future <75              :", len(plus20_nonrunners))
    print("Duplicate conflicts       :", dup_conflicts)
    print()

    metrics = (
        "additional_favorable_after_proof",
        "max_pullback_from_proof",
        "net_from_proof_to_window_end",
        "advancing_close_pct",
        "confirmed_swing_count",
        "supportive_advancing_swing_count",
        "proof_directional_vwap_diff",
        "end_directional_vwap_diff",
        "directional_vwap_diff_change",
        "atr_norm_additional_favorable",
        "atr_norm_pullback",
    )

    group_summary_rows = []
    report_windows = {}

    summary = [
        "B FAMILY — POST-PROOF EXPANSION DIAGNOSTIC V18",
        "=" * 118,
        f"Canonical B events    : {len(events)}",
        f"B events reaching +20 : {len(plus20_events)}",
        f"  future >=75 runners : {len(plus20_runners)}",
        f"  future <75          : {len(plus20_nonrunners)}",
        f"Duplicate conflicts   : {dup_conflicts}",
        "",
        "NO OPTIMIZATION. FUTURE >=75 IS AN OUTCOME LABEL ONLY.",
        "",
    ]

    for w in WINDOWS:
        rows_w = [r for r in window_rows if r["window_minutes"] == w]
        complete = [r for r in rows_w if r["complete"]]
        incomplete = [r for r in rows_w if not r["complete"]]

        runner = [r for r in complete if r["future_runner_75"]]
        nonrunner = [r for r in complete if not r["future_runner_75"]]

        summary += [
            f"+{w} MINUTES AFTER +20 PROOF",
            "-" * 118,
            f"complete={len(complete)} incomplete={len(incomplete)} "
            f"runner_complete={len(runner)} nonrunner_complete={len(nonrunner)}",
        ]

        report_windows[str(w)] = {
            "complete_count": len(complete),
            "incomplete_count": len(incomplete),
            "runner_complete_count": len(runner),
            "nonrunner_complete_count": len(nonrunner),
            "metrics": {},
        }

        for metric in metrics:
            rs = qstats(r.get(metric) for r in runner)
            ns = qstats(r.get(metric) for r in nonrunner)

            group_summary_rows.append({
                "window_minutes": w,
                "metric": metric,
                "runner_n": rs["n"],
                "runner_mean": rs["mean"],
                "runner_median": rs["median"],
                "runner_p25": rs["p25"],
                "runner_p75": rs["p75"],
                "nonrunner_n": ns["n"],
                "nonrunner_mean": ns["mean"],
                "nonrunner_median": ns["median"],
                "nonrunner_p25": ns["p25"],
                "nonrunner_p75": ns["p75"],
                "median_difference_runner_minus_nonrunner": (
                    rs["median"] - ns["median"]
                    if rs["median"] is not None and ns["median"] is not None
                    else None
                ),
            })

            report_windows[str(w)]["metrics"][metric] = {
                "runner": rs,
                "nonrunner": ns,
            }

            summary.append(
                f"{metric:<38} "
                f"RUN med={fmt(rs['median'])} mean={fmt(rs['mean'])} n={rs['n']:<2} | "
                f"NON med={fmt(ns['median'])} mean={fmt(ns['mean'])} n={ns['n']:<2} | "
                f"medDiff={fmt(
                    rs['median'] - ns['median']
                    if rs['median'] is not None and ns['median'] is not None
                    else None
                )}"
            )

        if incomplete:
            reasons = {}
            for r in incomplete:
                reasons[r["incomplete_reason"]] = reasons.get(r["incomplete_reason"], 0) + 1
            summary.append(
                "incomplete_reasons: "
                + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
            )

        summary.append("")

    summary += [
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- This run asks whether early post-proof behavior differs descriptively.",
        "- It does NOT create a fast/slow classifier.",
        "- Do not select a 3m/5m/10m cutoff based on whichever looks best here.",
        "- Do not derive a production trail threshold from these same 45 events.",
        "- Any future causal runner-management architecture must be defined once, frozen, then tested forward.",
        "- Same historical 180-session universe; not independent validation.",
        "- Underlying NIFTY points only, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_POST_PROOF_EXPANSION_DIAGNOSTIC_V18",
        "canonical_b_events": len(events),
        "plus20_event_count": len(plus20_events),
        "future_ge75_count_among_plus20": len(plus20_runners),
        "future_lt75_count_among_plus20": len(plus20_nonrunners),
        "windows_minutes": WINDOWS,
        "proof_points": PROOF_POINTS,
        "runner_outcome_threshold": RUNNER_THRESHOLD,
        "no_optimization": True,
        "future_label_not_used_in_feature_construction": True,
        "window_results": report_windows,
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, event_rows)
    write_csv(WINDOWS_CSV, window_rows)
    write_csv(SUMMARY_CSV, group_summary_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(summary))

    print("\n".join(summary))
    print()
    print("EVENTS CSV :", EVENTS_CSV)
    print("WINDOWS CSV:", WINDOWS_CSV)
    print("GROUP CSV  :", SUMMARY_CSV)
    print("REPORT JSON:", REPORT_JSON)
    print("SUMMARY    :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
