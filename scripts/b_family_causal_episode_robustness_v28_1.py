#!/usr/bin/env python3
"""
B FAMILY — V28.1 CAUSAL EPISODE ROBUSTNESS / CORRECTION

Purpose
-------
Correct the V28 persistence interpretation and add runner-level robustness.

This remains descriptive only.

Corrections / additions
-----------------------
1. Correct same-episode persistence:
   At +1/+3/+5, explicitly distinguish:
   - SAME_EPISODE_ACTIVE
   - ORIGINAL_EPISODE_ENDED_NO_NEW_JOINT
   - ORIGINAL_EPISODE_ENDED_NEW_JOINT_ACTIVE
   - ORIGINAL_EPISODE_ENDED_NO_JOINT_ACTIVE

2. Preserve causal checkpoint features:
   - drawdown / running MFE
   - drawdown points
   - cumulative directional VWAP change from episode start
   - price recovery from worst directional close since episode start

3. Add runner-level equal weighting:
   For each of 11 runners, compare recovered vs nonrecovered episode medians
   and compute within-runner differences.

4. Add leave-one-runner-out stability:
   Repeat recovered vs nonrecovered median differences 11 times, each time
   excluding one runner.

No thresholds.
No exit rule.
No Family-B change.
No V20 change.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median, mean

ROOT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1")

V26_TIMELINE = (
    ROOT / "b-family-runner-deterioration-diagnostic-v26"
    / "runner-minute-timeline-v26.csv"
)

V27_EPISODES = (
    ROOT / "b-family-runner-persistence-recovery-diagnostic-v27"
    / "runner-joint-deterioration-episodes-v27.csv"
)

OUTDIR = ROOT / "b-family-causal-episode-robustness-v28_1"

CHECKPOINT_CSV = OUTDIR / "episode-checkpoints-v28_1.csv"
RUNNER_CSV = OUTDIR / "runner-level-differences-v28_1.csv"
LOO_CSV = OUTDIR / "leave-one-runner-out-v28_1.csv"
REPORT_JSON = OUTDIR / "report-v28_1.json"
SUMMARY_TXT = OUTDIR / "summary-v28_1.txt"

CHECKPOINTS = (0, 1, 3, 5)
FEATURES = (
    "drawdown_fraction_of_running_mfe",
    "drawdown_from_running_mfe_close",
    "cumulative_vwap_change_from_episode_start",
    "price_recovery_from_episode_worst_close",
)


def load_csv(path: Path):
    if not path.exists():
        raise SystemExit(f"STOP: missing input: {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in (None, ""):
        return None
    return float(v)


def b(v):
    return str(v).strip().lower() == "true"


def med(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    return median(xs) if xs else None


def avg(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    return mean(xs) if xs else None


def fmt(x):
    return "-" if x is None else f"{float(x):+.3f}"


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


def timeline_key(r):
    return (r["session_date"], r["direction"])


def build_joint_intervals(session_rows):
    """
    Return contiguous joint-deterioration intervals over the whole timeline.
    Joint deterioration:
      drawdown > 0 AND prior-minute directional VWAP change < 0
    """
    intervals = []
    start = None
    end = None

    for row in session_rows:
        joint = (
            f(row["drawdown_from_running_mfe_close"]) is not None
            and f(row["drawdown_from_running_mfe_close"]) > 0
            and f(row["vwap_change_vs_prior_minute"]) is not None
            and f(row["vwap_change_vs_prior_minute"]) < 0
        )
        if joint:
            if start is None:
                start = row["timestamp"]
            end = row["timestamp"]
        else:
            if start is not None:
                intervals.append((start, end))
            start = None
            end = None

    if start is not None:
        intervals.append((start, end))

    return intervals


def state_at_checkpoint(ep_start, ep_end, cp_ts, intervals):
    if cp_ts <= ep_end:
        return "SAME_EPISODE_ACTIVE"

    new_joint = any(
        s <= cp_ts <= e and s > ep_end
        for s, e in intervals
    )

    if new_joint:
        return "ORIGINAL_EPISODE_ENDED_NEW_JOINT_ACTIVE"
    return "ORIGINAL_EPISODE_ENDED_NO_JOINT_ACTIVE"


def build_checkpoint(ep, rows, intervals, cp):
    start_ts = ep["start_timestamp"]
    end_ts = ep["end_timestamp"]

    start_idx = next(
        (i for i, r in enumerate(rows) if r["timestamp"] == start_ts),
        None
    )
    if start_idx is None:
        raise RuntimeError(
            f"Start not found: {ep['session_date']} ep={ep['episode_number']}"
        )

    idx = start_idx + cp
    if idx >= len(rows):
        return None

    row = rows[idx]
    cp_ts = row["timestamp"]
    start_row = rows[start_idx]

    rmfe = f(row["running_mfe"])
    dd = f(row["drawdown_from_running_mfe_close"])
    dd_frac = None
    if rmfe not in (None, 0):
        dd_frac = dd / rmfe

    start_vwap = f(start_row["directional_futures_vwap_diff"])
    cur_vwap = f(row["directional_futures_vwap_diff"])
    vwap_change = None
    if start_vwap is not None and cur_vwap is not None:
        vwap_change = cur_vwap - start_vwap

    scope = rows[start_idx: idx + 1]
    close_moves = [f(x["directional_close_move"]) for x in scope]
    close_moves = [x for x in close_moves if x is not None]
    cur_close = f(row["directional_close_move"])
    worst = min(close_moves) if close_moves else None
    price_recovery = None
    if cur_close is not None and worst is not None:
        price_recovery = cur_close - worst

    state = state_at_checkpoint(start_ts, end_ts, cp_ts, intervals)

    return {
        "validation_block": ep.get("validation_block"),
        "session_date": ep["session_date"],
        "direction": ep["direction"],
        "runner_id": f"{ep['session_date']}|{ep['direction']}",
        "episode_number": int(ep["episode_number"]),
        "episode_start_timestamp": start_ts,
        "episode_end_timestamp": end_ts,
        "checkpoint_minutes": cp,
        "checkpoint_timestamp": cp_ts,
        "outcome_group": "RECOVERED" if b(ep["new_mfe_after_episode"]) else "NONRECOVERED",
        "same_episode_state": state,
        "same_episode_active": state == "SAME_EPISODE_ACTIVE",
        "running_mfe": rmfe,
        "drawdown_from_running_mfe_close": dd,
        "drawdown_fraction_of_running_mfe": dd_frac,
        "cumulative_vwap_change_from_episode_start": vwap_change,
        "price_recovery_from_episode_worst_close": price_recovery,
    }


def group_medians(rows, cp, outcome):
    subset = [
        r for r in rows
        if r["checkpoint_minutes"] == cp
        and r["outcome_group"] == outcome
    ]
    out = {"checkpoint_minutes": cp, "outcome_group": outcome, "n": len(subset)}
    for feat in FEATURES:
        out[f"{feat}_median"] = med(r[feat] for r in subset)
    return out


def runner_level(rows):
    by_runner = defaultdict(list)
    for r in rows:
        by_runner[r["runner_id"]].append(r)

    out = []
    for runner_id, rr in sorted(by_runner.items()):
        session_date, direction = runner_id.split("|")
        for cp in CHECKPOINTS:
            rec = [
                r for r in rr
                if r["checkpoint_minutes"] == cp
                and r["outcome_group"] == "RECOVERED"
            ]
            non = [
                r for r in rr
                if r["checkpoint_minutes"] == cp
                and r["outcome_group"] == "NONRECOVERED"
            ]
            if not rec or not non:
                continue

            row = {
                "runner_id": runner_id,
                "session_date": session_date,
                "direction": direction,
                "checkpoint_minutes": cp,
                "recovered_n": len(rec),
                "nonrecovered_n": len(non),
            }
            for feat in FEATURES:
                rec_med = med(r[feat] for r in rec)
                non_med = med(r[feat] for r in non)
                row[f"{feat}_recovered_median"] = rec_med
                row[f"{feat}_nonrecovered_median"] = non_med
                row[f"{feat}_difference_non_minus_rec"] = (
                    None if rec_med is None or non_med is None
                    else non_med - rec_med
                )
            out.append(row)
    return out


def leave_one_runner_out(rows):
    runner_ids = sorted(set(r["runner_id"] for r in rows))
    out = []

    for excluded in runner_ids:
        kept = [r for r in rows if r["runner_id"] != excluded]

        for cp in CHECKPOINTS:
            rec = [
                r for r in kept
                if r["checkpoint_minutes"] == cp
                and r["outcome_group"] == "RECOVERED"
            ]
            non = [
                r for r in kept
                if r["checkpoint_minutes"] == cp
                and r["outcome_group"] == "NONRECOVERED"
            ]
            row = {
                "excluded_runner_id": excluded,
                "checkpoint_minutes": cp,
                "recovered_n": len(rec),
                "nonrecovered_n": len(non),
            }
            for feat in FEATURES:
                rec_med = med(r[feat] for r in rec)
                non_med = med(r[feat] for r in non)
                row[f"{feat}_difference_non_minus_rec"] = (
                    None if rec_med is None or non_med is None
                    else non_med - rec_med
                )
            out.append(row)

    return out


def main():
    print("B FAMILY — V28.1 CAUSAL EPISODE ROBUSTNESS / CORRECTION")
    print("=" * 118)

    timeline = load_csv(V26_TIMELINE)
    episodes = load_csv(V27_EPISODES)

    by_session = defaultdict(list)
    for row in timeline:
        by_session[timeline_key(row)].append(row)
    for key in by_session:
        by_session[key].sort(key=lambda x: x["timestamp"])

    if len(episodes) != 619:
        raise SystemExit(f"STOP: expected 619 episodes, got {len(episodes)}")

    interval_map = {
        key: build_joint_intervals(rows)
        for key, rows in by_session.items()
    }

    checkpoints = []
    for i, ep in enumerate(episodes, 1):
        key = (ep["session_date"], ep["direction"])
        rows = by_session[key]
        intervals = interval_map[key]

        for cp in CHECKPOINTS:
            x = build_checkpoint(ep, rows, intervals, cp)
            if x is not None:
                checkpoints.append(x)

        if i % 100 == 0 or i == len(episodes):
            print(f"processed {i}/{len(episodes)} episodes")

    group_rows = []
    for cp in CHECKPOINTS:
        for outcome in ("RECOVERED", "NONRECOVERED"):
            group_rows.append(group_medians(checkpoints, cp, outcome))

    runner_rows = runner_level(checkpoints)
    loo_rows = leave_one_runner_out(checkpoints)

    lines = [
        "B FAMILY — V28.1 CAUSAL EPISODE ROBUSTNESS / CORRECTION",
        "=" * 118,
        f"episodes={len(episodes)}",
        f"checkpoint_rows={len(checkpoints)}",
        f"runner_ids={len(set(r['runner_id'] for r in checkpoints))}",
        "",
        "CORRECTED SAME-EPISODE STATE COUNTS",
        "-" * 118,
    ]

    for cp in CHECKPOINTS:
        subset = [r for r in checkpoints if r["checkpoint_minutes"] == cp]
        counts = defaultdict(int)
        for r in subset:
            counts[r["same_episode_state"]] += 1
        lines.append(
            f"+{cp}m "
            + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )

    lines += [
        "",
        "RECOVERED VS NONRECOVERED MEDIANS",
        "-" * 118,
    ]

    for cp in CHECKPOINTS:
        rec = next(
            r for r in group_rows
            if r["checkpoint_minutes"] == cp and r["outcome_group"] == "RECOVERED"
        )
        non = next(
            r for r in group_rows
            if r["checkpoint_minutes"] == cp and r["outcome_group"] == "NONRECOVERED"
        )
        lines.append(f"CHECKPOINT +{cp}m")
        lines.append(
            f"  ddFrac recovered={fmt(rec['drawdown_fraction_of_running_mfe_median'])} "
            f"nonrecovered={fmt(non['drawdown_fraction_of_running_mfe_median'])}"
        )
        lines.append(
            f"  ddPts  recovered={fmt(rec['drawdown_from_running_mfe_close_median'])} "
            f"nonrecovered={fmt(non['drawdown_from_running_mfe_close_median'])}"
        )
        lines.append(
            f"  vwapChg recovered={fmt(rec['cumulative_vwap_change_from_episode_start_median'])} "
            f"nonrecovered={fmt(non['cumulative_vwap_change_from_episode_start_median'])}"
        )
        lines.append(
            f"  recovery recovered={fmt(rec['price_recovery_from_episode_worst_close_median'])} "
            f"nonrecovered={fmt(non['price_recovery_from_episode_worst_close_median'])}"
        )

    # Runner-level sign consistency.
    lines += [
        "",
        "RUNNER-LEVEL SIGN CONSISTENCY (NONRECOVERED MINUS RECOVERED)",
        "-" * 118,
    ]

    for cp in CHECKPOINTS:
        rr = [r for r in runner_rows if r["checkpoint_minutes"] == cp]
        lines.append(f"CHECKPOINT +{cp}m runners_with_both_groups={len(rr)}")
        for feat in FEATURES:
            vals = [
                r[f"{feat}_difference_non_minus_rec"]
                for r in rr
                if r[f"{feat}_difference_non_minus_rec"] is not None
            ]
            if feat in (
                "drawdown_fraction_of_running_mfe",
                "drawdown_from_running_mfe_close",
            ):
                expected_positive = sum(v > 0 for v in vals)
                label = "positive_expected"
            else:
                # For VWAP change and price recovery, nonrecovered is expected lower.
                expected_positive = sum(v < 0 for v in vals)
                label = "direction_expected"
            lines.append(
                f"  {feat}: {label}={expected_positive}/{len(vals)} "
                f"median_diff={fmt(med(vals))}"
            )

    lines += [
        "",
        "LEAVE-ONE-RUNNER-OUT STABILITY",
        "-" * 118,
    ]

    for cp in CHECKPOINTS:
        lr = [r for r in loo_rows if r["checkpoint_minutes"] == cp]
        lines.append(f"CHECKPOINT +{cp}m")
        for feat in FEATURES:
            vals = [
                r[f"{feat}_difference_non_minus_rec"]
                for r in lr
                if r[f"{feat}_difference_non_minus_rec"] is not None
            ]
            lines.append(
                f"  {feat}: "
                f"min_diff={fmt(min(vals) if vals else None)} "
                f"median_diff={fmt(med(vals))} "
                f"max_diff={fmt(max(vals) if vals else None)}"
            )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Corrected same-episode persistence interpretation.",
        "- Runner-level equal-weight diagnostic added.",
        "- Leave-one-runner-out diagnostic added.",
        "- No threshold search.",
        "- No exit rule created.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_CAUSAL_EPISODE_ROBUSTNESS_V28_1",
        "episode_count": len(episodes),
        "checkpoint_row_count": len(checkpoints),
        "runner_count": len(set(r["runner_id"] for r in checkpoints)),
        "group_summary": group_rows,
        "runner_level": runner_rows,
        "leave_one_runner_out": loo_rows,
        "guards": {
            "exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(CHECKPOINT_CSV, checkpoints)
    write_csv(RUNNER_CSV, runner_rows)
    write_csv(LOO_CSV, loo_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("CHECKPOINT CSV :", CHECKPOINT_CSV)
    print("RUNNER CSV     :", RUNNER_CSV)
    print("LOO CSV        :", LOO_CSV)
    print("REPORT JSON    :", REPORT_JSON)
    print("SUMMARY        :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
