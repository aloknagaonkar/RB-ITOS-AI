#!/usr/bin/env python3
"""
B FAMILY — POST-PROOF TEMPORAL STABILITY DIAGNOSTIC V19

Purpose
-------
Test whether the descriptive post-+20 separation seen in V18 is stable through
time, WITHOUT creating thresholds or a production classifier.

Universe
--------
- Canonical 180-session Family-B universe.
- Frozen Family-B detector unchanged.
- Compare only B events that reach +20 before structural invalidation.
- Outcome labels:
    FUTURE_GE75_RUNNER
    FUTURE_LT75
- Fixed causal observation windows:
    +3m, +5m, +10m

Temporal views
--------------
1) THREE_60_SESSION_BLOCKS
   BLOCK_1 = first 60 framework sessions
   BLOCK_2 = middle 60
   BLOCK_3 = latest 60

2) OLDER_VS_LATEST60
   OLDER = first 120 sessions
   LATEST60 = last 60

Primary directional-separation features from V18:
- additional_favorable_after_proof      expected runner > nonrunner
- net_from_proof_to_window_end          expected runner > nonrunner
- directional_vwap_diff_change          expected runner > nonrunner
- atr_norm_additional_favorable         expected runner > nonrunner

Secondary context:
- max_pullback_from_proof               no strong expected separation
- advancing_close_pct
- confirmed_swing_count
- supportive_advancing_swing_count

No cutoff search.
No p-value fishing.
No exit model changes.
Underlying NIFTY points only; not option-premium P&L.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-post-proof-temporal-stability-v19"
)
EVENTS_CSV = OUTDIR / "post-proof-events-v19.csv"
BLOCK_SUMMARY_CSV = OUTDIR / "block-feature-summary-v19.csv"
DIRECTION_CSV = OUTDIR / "direction-consistency-v19.csv"
REPORT_JSON = OUTDIR / "report-v19.json"
SUMMARY_TXT = OUTDIR / "summary-v19.txt"

EXPECTED_B_TOTAL = 45
EXPECTED_SESSIONS = 180
PROOF_POINTS = 20.0
RUNNER_THRESHOLD = 75.0
WINDOWS = (3, 5, 10)

PRIMARY = (
    "additional_favorable_after_proof",
    "net_from_proof_to_window_end",
    "directional_vwap_diff_change",
    "atr_norm_additional_favorable",
)

SECONDARY = (
    "max_pullback_from_proof",
    "advancing_close_pct",
    "confirmed_swing_count",
    "supportive_advancing_swing_count",
)


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

    advancing = 0
    for (_, a), (_, b) in zip(pivots, pivots[1:]):
        if direction == "BULLISH" and b > a:
            advancing += 1
        elif direction == "BEARISH" and b < a:
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

    if not canon.is_trusted(end_ts):
        return {"complete": False, "incomplete_reason": "WINDOW_END_AFTER_TRUSTED_CUTOFF"}

    if invalid_ts and end_ts >= invalid_ts:
        return {"complete": False, "incomplete_reason": "STRUCTURAL_INVALIDATION_BEFORE_WINDOW_END"}

    expected = [minute_key(proof_dt + timedelta(minutes=i)) for i in range(0, minutes + 1)]
    missing = [ts for ts in expected if ts not in u]
    if missing:
        return {"complete": False, "incomplete_reason": f"MISSING_UNDERLYING_MINUTES:{len(missing)}"}

    rows = [(ts, u[ts]) for ts in expected]
    post_rows = rows[1:]
    proof_bar = u[proof_ts]
    end_bar = u[end_ts]

    max_fav = max([PROOF_POINTS] + [favorable_move(direction, entry, b) for _, b in post_rows])
    min_path = min(
        [adverse_side_move(direction, entry, proof_bar)]
        + [adverse_side_move(direction, entry, b) for _, b in post_rows]
    )

    additional_fav = max_fav - PROOF_POINTS
    max_pullback = max(0.0, PROOF_POINTS - min_path)
    net = directional_close(direction, entry, end_bar) - PROOF_POINTS

    advancing = 0
    prior = float(proof_bar["close"])
    for _, b in post_rows:
        cur = float(b["close"])
        if direction == "BULLISH":
            advancing += int(cur > prior)
        else:
            advancing += int(cur < prior)
        prior = cur

    pivot_count, supportive = confirmed_supportive_swing_count(direction, rows)

    proof_v = futures_directional_diff(direction, fut.get(proof_ts))
    end_v = futures_directional_diff(direction, fut.get(end_ts))
    vchg = (end_v - proof_v) if proof_v is not None and end_v is not None else None

    return {
        "complete": True,
        "incomplete_reason": None,
        "window_end_timestamp": end_ts,
        "additional_favorable_after_proof": additional_fav,
        "max_pullback_from_proof": max_pullback,
        "net_from_proof_to_window_end": net,
        "advancing_close_pct": 100.0 * advancing / minutes,
        "confirmed_swing_count": pivot_count,
        "supportive_advancing_swing_count": supportive,
        "directional_vwap_diff_change": vchg,
        "atr_norm_additional_favorable": (
            additional_fav / float(proof_atr)
            if proof_atr not in (None, 0)
            else None
        ),
    }


def qstats(values):
    xs = sorted(float(x) for x in values if x not in (None, ""))
    if not xs:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}

    def q(p):
        return xs[round((len(xs) - 1) * p)]

    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "p25": q(0.25),
        "p75": q(0.75),
    }


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


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def main():
    print("B FAMILY — POST-PROOF TEMPORAL STABILITY DIAGNOSTIC V19")
    print("=" * 118)

    c = import_module(CANON, "canonical_b_v19")
    r8 = import_module(V8_2, "risk_v8_2_v19")

    _, framework = c.load_framework()
    _, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    sessions = sorted({e["session_date"] for e in framework})
    if len(sessions) != EXPECTED_SESSIONS:
        raise SystemExit(f"STOP: session parity failed {len(sessions)} != {EXPECTED_SESSIONS}")

    session_pos = {d: i for i, d in enumerate(sessions)}

    events = []
    for e in framework:
        d = e["session_date"]
        b = c.family_b_for_event(e, underlying.get(d, {}), futures.get(d, {}))
        if b:
            events.append(c.measure_event(dict(b), underlying[d]))

    if len(events) != EXPECTED_B_TOTAL or dup_conflicts != 0:
        raise SystemExit(
            f"STOP: canonical parity failed events={len(events)} dup_conflicts={dup_conflicts}"
        )

    rows = []

    for ev in events:
        d = ev["session_date"]
        u = underlying[d]
        fut = futures.get(d, {})
        proof = first_proof_20(ev, u, c)
        if proof is None:
            continue

        idx = session_pos[d]
        if idx < 60:
            block60 = "BLOCK_1_FIRST60"
        elif idx < 120:
            block60 = "BLOCK_2_MIDDLE60"
        else:
            block60 = "BLOCK_3_LATEST60"

        older_latest = "OLDER120" if idx < 120 else "LATEST60"

        proof_atr = r8.causal_atr_1m(u, proof)
        outcome = (
            "FUTURE_GE75_RUNNER"
            if ev.get("mfe") is not None and float(ev["mfe"]) >= RUNNER_THRESHOLD
            else "FUTURE_LT75"
        )

        for w in WINDOWS:
            wr = build_window(ev, u, fut, proof, w, proof_atr, c)
            row = {
                "session_date": d,
                "session_index_0based": idx,
                "block60": block60,
                "older_latest": older_latest,
                "direction": ev["direction"],
                "entry_timestamp": ev["entry_timestamp"],
                "proof20_timestamp": proof,
                "window_minutes": w,
                "outcome_group": outcome,
                "future_runner_75": outcome == "FUTURE_GE75_RUNNER",
                "canonical_mfe": ev.get("mfe"),
                "canonical_mae": ev.get("mae"),
                **wr,
            }
            rows.append(row)

    print("Canonical B events       :", len(events))
    print("B events reaching +20    :", len({(r["session_date"], r["entry_timestamp"]) for r in rows}))
    print("Duplicate conflicts      :", dup_conflicts)
    print("Session range            :", sessions[0], "->", sessions[-1])
    print()

    views = {
        "THREE_60_SESSION_BLOCKS": ("block60", [
            "BLOCK_1_FIRST60",
            "BLOCK_2_MIDDLE60",
            "BLOCK_3_LATEST60",
        ]),
        "OLDER_VS_LATEST60": ("older_latest", [
            "OLDER120",
            "LATEST60",
        ]),
    }

    block_rows = []
    direction_rows = []
    report = {
        "version": "B_FAMILY_POST_PROOF_TEMPORAL_STABILITY_V19",
        "canonical_b_events": len(events),
        "session_count": len(sessions),
        "windows": WINDOWS,
        "primary_features": PRIMARY,
        "secondary_features": SECONDARY,
        "no_threshold_search": True,
        "views": {},
    }

    summary = [
        "B FAMILY — POST-PROOF TEMPORAL STABILITY DIAGNOSTIC V19",
        "=" * 118,
        f"Canonical B events : {len(events)}",
        f"Session count      : {len(sessions)}",
        f"Duplicate conflicts: {dup_conflicts}",
        "",
        "PRIMARY QUESTION:",
        "Does runner-minus-nonrunner separation keep the SAME DIRECTION through time?",
        "",
    ]

    for view_name, (field, groups) in views.items():
        summary += [view_name, "=" * 118]
        report["views"][view_name] = {}

        for w in WINDOWS:
            summary += [f"+{w} MIN WINDOW", "-" * 118]
            report["views"][view_name][str(w)] = {}

            for feat in PRIMARY + SECONDARY:
                diffs = []
                signs = []

                for group in groups:
                    subset = [
                        r for r in rows
                        if r["window_minutes"] == w
                        and r[field] == group
                        and r["complete"]
                    ]
                    run = [r for r in subset if r["future_runner_75"]]
                    non = [r for r in subset if not r["future_runner_75"]]

                    rs = qstats(r.get(feat) for r in run)
                    ns = qstats(r.get(feat) for r in non)

                    diff = (
                        rs["median"] - ns["median"]
                        if rs["median"] is not None and ns["median"] is not None
                        else None
                    )

                    sign = (
                        "POS" if diff is not None and diff > 0
                        else "NEG" if diff is not None and diff < 0
                        else "ZERO" if diff == 0
                        else "NA"
                    )

                    diffs.append(diff)
                    signs.append(sign)

                    block_rows.append({
                        "view": view_name,
                        "window_minutes": w,
                        "feature": feat,
                        "group": group,
                        "runner_n": rs["n"],
                        "runner_median": rs["median"],
                        "nonrunner_n": ns["n"],
                        "nonrunner_median": ns["median"],
                        "median_difference_runner_minus_nonrunner": diff,
                        "sign": sign,
                    })

                valid_signs = [s for s in signs if s != "NA"]
                nonzero = [s for s in valid_signs if s != "ZERO"]
                same_dir = len(set(nonzero)) <= 1 if nonzero else True
                all_groups_have_data = all(s != "NA" for s in signs)

                if all_groups_have_data and same_dir and nonzero:
                    consistency = f"CONSISTENT_{nonzero[0]}"
                elif all_groups_have_data and same_dir and not nonzero:
                    consistency = "CONSISTENT_ZERO"
                else:
                    consistency = "MIXED_OR_INCOMPLETE"

                direction_rows.append({
                    "view": view_name,
                    "window_minutes": w,
                    "feature": feat,
                    "group_signs": "|".join(f"{g}:{s}" for g, s in zip(groups, signs)),
                    "consistency": consistency,
                })

                report["views"][view_name][str(w)][feat] = {
                    "groups": {
                        g: {"median_diff_runner_minus_nonrunner": d, "sign": s}
                        for g, d, s in zip(groups, diffs, signs)
                    },
                    "consistency": consistency,
                }

                summary.append(
                    f"{feat:<38} "
                    + " | ".join(
                        f"{g.replace('BLOCK_','B').replace('_FIRST60','').replace('_MIDDLE60','').replace('_LATEST60','')} "
                        f"{fmt(d)}({s})"
                        for g, d, s in zip(groups, diffs, signs)
                    )
                    + f" => {consistency}"
                )

            summary.append("")

    # Primary-only compact score: how many primary features preserve positive
    # direction per window in both temporal views. This is descriptive, not a model score.
    summary += [
        "PRIMARY FEATURE DIRECTION CONSISTENCY",
        "=" * 118,
    ]

    for w in WINDOWS:
        for view_name in views:
            subset = [
                r for r in direction_rows
                if r["view"] == view_name
                and r["window_minutes"] == w
                and r["feature"] in PRIMARY
            ]
            pos = sum(r["consistency"] == "CONSISTENT_POS" for r in subset)
            mixed = sum(r["consistency"] == "MIXED_OR_INCOMPLETE" for r in subset)
            summary.append(
                f"{view_name:<28} +{w:2d}m: "
                f"primary consistent-positive={pos}/{len(PRIMARY)} "
                f"mixed/incomplete={mixed}/{len(PRIMARY)}"
            )

    summary += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Positive consistency means runner median > nonrunner median in every temporal block with data.",
        "- This is descriptive stability, not statistical proof.",
        "- Small block counts can make medians noisy.",
        "- Do not convert any observed difference into a live threshold here.",
        "- Do not choose 3m/5m/10m solely because it looks strongest on this same history.",
        "- Any runner-management candidate must be specified once, frozen, then tested on future sessions.",
        "- Underlying NIFTY points only; not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, rows)
    write_csv(BLOCK_SUMMARY_CSV, block_rows)
    write_csv(DIRECTION_CSV, direction_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(summary))

    print("\n".join(summary))
    print()
    print("EVENTS CSV   :", EVENTS_CSV)
    print("BLOCK CSV    :", BLOCK_SUMMARY_CSV)
    print("DIRECTION CSV:", DIRECTION_CSV)
    print("REPORT JSON  :", REPORT_JSON)
    print("SUMMARY      :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
