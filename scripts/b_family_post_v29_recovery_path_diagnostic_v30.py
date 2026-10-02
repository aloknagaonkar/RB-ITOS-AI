#!/usr/bin/env python3
"""
B FAMILY — V30 POST-V29 RECOVERY PATH DIAGNOSTIC

Purpose
-------
Study what happens AFTER the frozen V29 exit signal on the 7 OOS
RUNNER_STRENGTHENING events from V29.

This is descriptive only.

Question
--------
Why did 6/7 V29 exits occur before a later new MFE, while 1/7 did not?

For every V29-triggered runner, measure causally after the V29 exit timestamp:
- time to next new MFE
- maximum further adverse move before recovery
- whether directional futures-VWAP recovers above the V29-exit level
- time to that VWAP recovery
- whether price retakes the V29 episode-start directional close level
- time to that price retake
- whether another joint-deterioration episode begins before the next new MFE
- number of additional joint-deterioration episode starts before next new MFE
- whether price/VWAP recovery occurs before next new MFE

No exit rule is defined.
No thresholds are tuned.
Family-B and V20 remain frozen.
V29 remains rejected.
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

OUTDIR = RESEARCH / "b-family-post-v29-recovery-path-v30"
EVENT_CSV = OUTDIR / "post-v29-recovery-events-v30.csv"
REPORT_JSON = OUTDIR / "report-v30.json"
SUMMARY_TXT = OUTDIR / "summary-v30.txt"


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


def adverse_price(direction, bar):
    return bar["low"] if direction == "BULLISH" else bar["high"]


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
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def analyze_event(ev, u, fut):
    direction = ev["direction"]
    entry = float(ev["entry_close"])
    exit_ts = ev["v29_exit_timestamp"]
    episode_start_ts = ev["v29_episode_start_timestamp"]
    invalid_ts = ev.get("structural_invalidation_timestamp") or None

    if not exit_ts:
        raise RuntimeError("V30 expects V29-triggered runner rows only")

    # Pre-exit running MFE through the exit candle.
    pre_exit_mfe = None
    for ts in sorted(u):
        if ts <= ev["entry_timestamp"]:
            continue
        if ts > exit_ts:
            break
        if invalid_ts and ts >= invalid_ts:
            break
        fav = directional(direction, entry, favorable_price(direction, u[ts]))
        pre_exit_mfe = fav if pre_exit_mfe is None else max(pre_exit_mfe, fav)

    exit_move = directional(direction, entry, u[exit_ts]["close"])

    exit_f = fut.get(exit_ts)
    exit_dvwap = None
    if exit_f:
        exit_dvwap = directional_vwap(
            direction, exit_f["close"], exit_f["vwap"]
        )

    episode_start_move = f(ev.get("v29_episode_start_move"))
    if episode_start_move is None and episode_start_ts in u:
        episode_start_move = directional(
            direction, entry, u[episode_start_ts]["close"]
        )

    # Scan after V29 exit until canonical structural invalidation.
    post = []
    running_mfe = pre_exit_mfe
    prev_dvwap = exit_dvwap
    prior_joint = False

    next_new_mfe_ts = None
    vwap_recovery_ts = None
    price_retake_ts = None
    worst_adverse_move = None
    extra_joint_starts = []

    for ts in sorted(u):
        if ts <= exit_ts:
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        bar = u[ts]

        fav = directional(direction, entry, favorable_price(direction, bar))
        close_move = directional(direction, entry, bar["close"])
        adverse_move = directional(direction, entry, adverse_price(direction, bar))

        if worst_adverse_move is None or adverse_move < worst_adverse_move:
            worst_adverse_move = adverse_move

        made_new_mfe = (
            running_mfe is not None and fav > running_mfe + 1e-9
        )
        if made_new_mfe and next_new_mfe_ts is None:
            next_new_mfe_ts = ts

        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        frow = fut.get(ts)
        dvwap = None
        if frow:
            dvwap = directional_vwap(
                direction, frow["close"], frow["vwap"]
            )

        if (
            vwap_recovery_ts is None
            and exit_dvwap is not None
            and dvwap is not None
            and dvwap > exit_dvwap
        ):
            vwap_recovery_ts = ts

        if (
            price_retake_ts is None
            and episode_start_move is not None
            and close_move > episode_start_move
        ):
            price_retake_ts = ts

        drawdown = None
        if running_mfe is not None:
            drawdown = running_mfe - close_move

        vwap_change_prior = None
        if dvwap is not None and prev_dvwap is not None:
            vwap_change_prior = dvwap - prev_dvwap

        joint = (
            drawdown is not None
            and drawdown > 0
            and vwap_change_prior is not None
            and vwap_change_prior < 0
        )

        if joint and not prior_joint:
            extra_joint_starts.append(ts)

        post.append({
            "timestamp": ts,
            "favorable_move": fav,
            "directional_close_move": close_move,
            "adverse_move": adverse_move,
            "running_mfe": running_mfe,
            "directional_vwap": dvwap,
            "joint": joint,
        })

        prior_joint = joint
        if dvwap is not None:
            prev_dvwap = dvwap

    # Restrict "before next new MFE" counts.
    extra_before_new_mfe = [
        ts for ts in extra_joint_starts
        if next_new_mfe_ts is None or ts < next_new_mfe_ts
    ]

    max_further_adverse_before_recovery = None
    horizon_ts = next_new_mfe_ts

    pre_recovery_rows = [
        x for x in post
        if horizon_ts is None or x["timestamp"] < horizon_ts
    ]

    if pre_recovery_rows:
        min_adverse = min(x["adverse_move"] for x in pre_recovery_rows)
        max_further_adverse_before_recovery = exit_move - min_adverse

    return {
        "validation_block": ev.get("validation_block"),
        "session_date": ev["session_date"],
        "direction": direction,
        "entry_timestamp": ev["entry_timestamp"],
        "classification_timestamp": ev.get("observation_end_timestamp"),
        "v29_episode_start_timestamp": episode_start_ts,
        "v29_exit_timestamp": exit_ts,
        "v29_exit_move": exit_move,
        "pre_exit_running_mfe": pre_exit_mfe,
        "post_exit_new_mfe": next_new_mfe_ts is not None,
        "next_new_mfe_timestamp": next_new_mfe_ts,
        "minutes_exit_to_next_new_mfe": (
            mins(exit_ts, next_new_mfe_ts)
            if next_new_mfe_ts else None
        ),
        "max_further_adverse_move_before_new_mfe": (
            max_further_adverse_before_recovery
        ),
        "exit_directional_vwap": exit_dvwap,
        "vwap_recovered_above_exit_level": vwap_recovery_ts is not None,
        "vwap_recovery_timestamp": vwap_recovery_ts,
        "minutes_exit_to_vwap_recovery": (
            mins(exit_ts, vwap_recovery_ts)
            if vwap_recovery_ts else None
        ),
        "price_retook_episode_start_level": price_retake_ts is not None,
        "price_retake_timestamp": price_retake_ts,
        "minutes_exit_to_price_retake": (
            mins(exit_ts, price_retake_ts)
            if price_retake_ts else None
        ),
        "additional_joint_episode_starts_before_new_mfe": len(
            extra_before_new_mfe
        ),
        "any_additional_joint_episode_before_new_mfe": (
            len(extra_before_new_mfe) > 0
        ),
        "vwap_recovery_before_new_mfe": (
            vwap_recovery_ts is not None
            and (
                next_new_mfe_ts is None
                or vwap_recovery_ts < next_new_mfe_ts
            )
        ),
        "price_retake_before_new_mfe": (
            price_retake_ts is not None
            and (
                next_new_mfe_ts is None
                or price_retake_ts < next_new_mfe_ts
            )
        ),
        "structural_invalidation_timestamp": invalid_ts,
    }


def main():
    print("B FAMILY — V30 POST-V29 RECOVERY PATH DIAGNOSTIC")
    print("=" * 118)

    runner_rows = load_csv(V29_RUNNERS)
    runner_rows = [r for r in runner_rows if b(r.get("v29_exit_triggered"))]

    if len(runner_rows) != 7:
        raise SystemExit(
            f"STOP: expected 7 V29-triggered runner rows, got {len(runner_rows)}"
        )

    underlying = load_underlying()
    futures = load_futures()

    rows = []

    for i, ev in enumerate(runner_rows, 1):
        d = ev["session_date"]

        if d not in underlying or d not in futures:
            raise SystemExit(f"STOP: missing raw data for {d}")

        row = analyze_event(ev, underlying[d], futures[d])
        rows.append(row)

        print(
            f"{i:2d}/7 {d} {row['direction']} "
            f"newMFE={row['post_exit_new_mfe']} "
            f"tNewMFE={fmt(row['minutes_exit_to_next_new_mfe'])}m "
            f"advBeforeRecovery={fmt(row['max_further_adverse_move_before_new_mfe'])} "
            f"vwapRecovery={row['vwap_recovered_above_exit_level']} "
            f"priceRetake={row['price_retook_episode_start_level']} "
            f"extraJoint={row['additional_joint_episode_starts_before_new_mfe']}"
        )

    recovered = [r for r in rows if r["post_exit_new_mfe"]]
    failed = [r for r in rows if not r["post_exit_new_mfe"]]

    t_new = stats(r["minutes_exit_to_next_new_mfe"] for r in recovered)
    adverse = stats(
        r["max_further_adverse_move_before_new_mfe"] for r in recovered
    )
    t_vwap = stats(
        r["minutes_exit_to_vwap_recovery"] for r in recovered
        if r["vwap_recovered_above_exit_level"]
    )
    t_price = stats(
        r["minutes_exit_to_price_retake"] for r in recovered
        if r["price_retook_episode_start_level"]
    )

    lines = [
        "B FAMILY — V30 POST-V29 RECOVERY PATH DIAGNOSTIC",
        "=" * 118,
        f"v29_triggered_runners={len(rows)}",
        f"later_new_mfe={len(recovered)}",
        f"no_later_new_mfe={len(failed)}",
        "",
        "FALSE-EXIT RECOVERY PATHS",
        "-" * 118,
        f"exit -> next new MFE: n={t_new['n']} median={fmt(t_new['median'])}m "
        f"mean={fmt(t_new['mean'])}m max={fmt(t_new['max'])}m",
        f"further adverse excursion before new MFE: n={adverse['n']} "
        f"median={fmt(adverse['median'])} mean={fmt(adverse['mean'])}",
        f"exit -> VWAP recovery: n={t_vwap['n']} median={fmt(t_vwap['median'])}m "
        f"mean={fmt(t_vwap['mean'])}m",
        f"exit -> price retake of episode-start level: n={t_price['n']} "
        f"median={fmt(t_price['median'])}m mean={fmt(t_price['mean'])}m",
        "",
        "RECOVERY EVENT COUNTS",
        "-" * 118,
        f"VWAP recovered above exit level: "
        f"{sum(r['vwap_recovered_above_exit_level'] for r in rows)}/{len(rows)}",
        f"Price retook episode-start level: "
        f"{sum(r['price_retook_episode_start_level'] for r in rows)}/{len(rows)}",
        f"VWAP recovery before next new MFE: "
        f"{sum(r['vwap_recovery_before_new_mfe'] for r in recovered)}/{len(recovered)}",
        f"Price retake before next new MFE: "
        f"{sum(r['price_retake_before_new_mfe'] for r in recovered)}/{len(recovered)}",
        f"At least one additional joint deterioration before next new MFE: "
        f"{sum(r['any_additional_joint_episode_before_new_mfe'] for r in recovered)}/{len(recovered)}",
        "",
        "EVENT DETAILS",
        "-" * 118,
    ]

    for r in rows:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"newMFE={r['post_exit_new_mfe']} "
            f"tNewMFE={fmt(r['minutes_exit_to_next_new_mfe'])}m "
            f"adv={fmt(r['max_further_adverse_move_before_new_mfe'])} "
            f"vwapRec={r['vwap_recovered_above_exit_level']} "
            f"tVwap={fmt(r['minutes_exit_to_vwap_recovery'])}m "
            f"priceRetake={r['price_retook_episode_start_level']} "
            f"tPrice={fmt(r['minutes_exit_to_price_retake'])}m "
            f"extraJoint={r['additional_joint_episode_starts_before_new_mfe']}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- V29 remains rejected.",
        "- V30 is descriptive only.",
        "- No recovery rule or exit state machine is defined.",
        "- No threshold search.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- Underlying NIFTY points only; not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_POST_V29_RECOVERY_PATH_DIAGNOSTIC_V30",
        "v29_triggered_runner_count": len(rows),
        "later_new_mfe_count": len(recovered),
        "no_later_new_mfe_count": len(failed),
        "recovery_stats": {
            "exit_to_next_new_mfe_minutes": t_new,
            "further_adverse_before_new_mfe": adverse,
            "exit_to_vwap_recovery_minutes": t_vwap,
            "exit_to_price_retake_minutes": t_price,
        },
        "events": rows,
        "guards": {
            "v29_status": "REJECTED",
            "new_exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_CSV, rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENT CSV   :", EVENT_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
