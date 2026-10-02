#!/usr/bin/env python3
"""
B FAMILY — V28 CAUSAL EPISODE CHECKPOINT DIAGNOSTIC

Purpose
-------
Compare recovered vs non-recovered joint-deterioration episodes using only
information available at fixed causal checkpoints:

  episode start
  +1 minute
  +3 minutes
  +5 minutes

This is descriptive research only.

It does NOT:
- define an exit
- tune a threshold
- change Family-B
- change V20 runner classification
- change production/runtime/order code

Episode source
--------------
V27:
  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-runner-persistence-recovery-diagnostic-v27/
  runner-joint-deterioration-episodes-v27.csv

Minute source
-------------
V26:
  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-runner-deterioration-diagnostic-v26/
  runner-minute-timeline-v26.csv

Causal checkpoint features
--------------------------
At each checkpoint, using data up to that minute only:
- drawdown_from_running_mfe_close
- drawdown_fraction_of_running_mfe
- directional_futures_vwap_diff
- cumulative_vwap_change_from_episode_start
- price_recovery_from_episode_worst_close
- current directional_close_move
- current running_mfe
- whether price is still below running MFE
- whether VWAP change vs prior minute is still negative
- whether price+VWAP joint deterioration is still active

No threshold search is performed.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence/hilega-pcr-oi-support-research-v1")

V26_TIMELINE = (
    ROOT / "b-family-runner-deterioration-diagnostic-v26"
    / "runner-minute-timeline-v26.csv"
)

V27_EPISODES = (
    ROOT / "b-family-runner-persistence-recovery-diagnostic-v27"
    / "runner-joint-deterioration-episodes-v27.csv"
)

OUTDIR = ROOT / "b-family-causal-episode-checkpoint-diagnostic-v28"
CHECKPOINT_CSV = OUTDIR / "episode-checkpoints-v28.csv"
GROUP_CSV = OUTDIR / "checkpoint-group-summary-v28.csv"
REPORT_JSON = OUTDIR / "report-v28.json"
SUMMARY_TXT = OUTDIR / "summary-v28.txt"

CHECKPOINTS = (0, 1, 3, 5)


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


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


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


def episode_key(r):
    return (
        r["session_date"],
        r["direction"],
        int(r["episode_number"]),
    )


def timeline_key(r):
    return (r["session_date"], r["direction"])


def build_episode_checkpoint(ep, session_rows, checkpoint):
    start_ts = ep["start_timestamp"]
    end_ts = ep["end_timestamp"]

    start_idx = None
    for i, row in enumerate(session_rows):
        if row["timestamp"] == start_ts:
            start_idx = i
            break

    if start_idx is None:
        raise RuntimeError(
            f"Episode start not found in timeline: "
            f"{ep['session_date']} {ep['episode_number']} {start_ts}"
        )

    idx = start_idx + checkpoint
    if idx >= len(session_rows):
        return None

    row = session_rows[idx]

    # Must remain within the episode's causal horizon.
    # For checkpoint analysis, we intentionally allow checkpoints after the
    # episode ended only if the corresponding minute exists in the same runner
    # lifecycle, because the question is what is knowable N minutes after the
    # episode began. We record whether the episode is still active.
    start_row = session_rows[start_idx]

    running_mfe = f(row["running_mfe"])
    drawdown = f(row["drawdown_from_running_mfe_close"])
    dd_fraction = None
    if running_mfe not in (None, 0):
        dd_fraction = drawdown / running_mfe

    start_vwap = f(start_row["directional_futures_vwap_diff"])
    cur_vwap = f(row["directional_futures_vwap_diff"])
    cumulative_vwap_change = None
    if start_vwap is not None and cur_vwap is not None:
        cumulative_vwap_change = cur_vwap - start_vwap

    # Worst directional close move observed from episode start through checkpoint.
    scope = session_rows[start_idx: idx + 1]
    close_moves = [f(x["directional_close_move"]) for x in scope]
    close_moves = [x for x in close_moves if x is not None]

    cur_close_move = f(row["directional_close_move"])
    worst_close_move = min(close_moves) if close_moves else None
    price_recovery = None
    if cur_close_move is not None and worst_close_move is not None:
        price_recovery = cur_close_move - worst_close_move

    prior_vwap_change = f(row["vwap_change_vs_prior_minute"])
    price_below_running_mfe = (
        drawdown is not None and drawdown > 0
    )
    vwap_still_weakening = (
        prior_vwap_change is not None and prior_vwap_change < 0
    )
    joint_active = price_below_running_mfe and vwap_still_weakening

    episode_still_active = row["timestamp"] <= end_ts

    return {
        "validation_block": ep.get("validation_block"),
        "session_date": ep["session_date"],
        "direction": ep["direction"],
        "episode_number": int(ep["episode_number"]),
        "episode_start_timestamp": start_ts,
        "episode_end_timestamp": end_ts,
        "checkpoint_minutes": checkpoint,
        "checkpoint_timestamp": row["timestamp"],
        "episode_still_active": episode_still_active,
        "new_mfe_after_episode": b(ep["new_mfe_after_episode"]),
        "outcome_group": (
            "RECOVERED"
            if b(ep["new_mfe_after_episode"])
            else "NONRECOVERED"
        ),
        "running_mfe": running_mfe,
        "directional_close_move": cur_close_move,
        "drawdown_from_running_mfe_close": drawdown,
        "drawdown_fraction_of_running_mfe": dd_fraction,
        "directional_futures_vwap_diff": cur_vwap,
        "cumulative_vwap_change_from_episode_start": cumulative_vwap_change,
        "price_recovery_from_episode_worst_close": price_recovery,
        "price_below_running_mfe": price_below_running_mfe,
        "vwap_still_weakening": vwap_still_weakening,
        "joint_deterioration_still_active": joint_active,
    }


def summarize_group(rows, checkpoint, outcome):
    subset = [
        r for r in rows
        if r["checkpoint_minutes"] == checkpoint
        and r["outcome_group"] == outcome
    ]

    return {
        "checkpoint_minutes": checkpoint,
        "outcome_group": outcome,
        "n": len(subset),
        "drawdown_fraction_median": stats(
            r["drawdown_fraction_of_running_mfe"] for r in subset
        )["median"],
        "drawdown_fraction_mean": stats(
            r["drawdown_fraction_of_running_mfe"] for r in subset
        )["mean"],
        "drawdown_points_median": stats(
            r["drawdown_from_running_mfe_close"] for r in subset
        )["median"],
        "vwap_change_median": stats(
            r["cumulative_vwap_change_from_episode_start"] for r in subset
        )["median"],
        "vwap_change_mean": stats(
            r["cumulative_vwap_change_from_episode_start"] for r in subset
        )["mean"],
        "price_recovery_median": stats(
            r["price_recovery_from_episode_worst_close"] for r in subset
        )["median"],
        "price_recovery_mean": stats(
            r["price_recovery_from_episode_worst_close"] for r in subset
        )["mean"],
        "episode_still_active_count": sum(
            bool(r["episode_still_active"]) for r in subset
        ),
        "joint_still_active_count": sum(
            bool(r["joint_deterioration_still_active"]) for r in subset
        ),
    }


def main():
    print("B FAMILY — V28 CAUSAL EPISODE CHECKPOINT DIAGNOSTIC")
    print("=" * 118)

    timeline = load_csv(V26_TIMELINE)
    episodes = load_csv(V27_EPISODES)

    by_session = defaultdict(list)
    for row in timeline:
        by_session[timeline_key(row)].append(row)

    for key in by_session:
        by_session[key].sort(key=lambda x: x["timestamp"])

    if len(episodes) != 619:
        raise SystemExit(
            f"STOP: expected 619 V27 episodes, got {len(episodes)}"
        )

    checkpoint_rows = []

    for i, ep in enumerate(episodes, 1):
        key = (ep["session_date"], ep["direction"])
        session_rows = by_session.get(key)
        if not session_rows:
            raise SystemExit(
                f"STOP: no timeline rows for {ep['session_date']} {ep['direction']}"
            )

        for cp in CHECKPOINTS:
            row = build_episode_checkpoint(ep, session_rows, cp)
            if row is not None:
                checkpoint_rows.append(row)

        if i % 100 == 0 or i == len(episodes):
            print(f"processed {i}/{len(episodes)} episodes")

    group_rows = []
    for cp in CHECKPOINTS:
        for outcome in ("RECOVERED", "NONRECOVERED"):
            group_rows.append(
                summarize_group(checkpoint_rows, cp, outcome)
            )

    lines = [
        "B FAMILY — V28 CAUSAL EPISODE CHECKPOINT DIAGNOSTIC",
        "=" * 118,
        f"episodes={len(episodes)}",
        f"checkpoint_rows={len(checkpoint_rows)}",
        "",
        "RECOVERED VS NONRECOVERED — FIXED CAUSAL CHECKPOINTS",
        "-" * 118,
    ]

    for cp in CHECKPOINTS:
        lines.append(f"CHECKPOINT +{cp}m")
        for outcome in ("RECOVERED", "NONRECOVERED"):
            g = next(
                r for r in group_rows
                if r["checkpoint_minutes"] == cp
                and r["outcome_group"] == outcome
            )
            lines.append(
                f"  {outcome:<12} n={g['n']} "
                f"ddFrac_med={fmt(g['drawdown_fraction_median'])} "
                f"ddPts_med={fmt(g['drawdown_points_median'])} "
                f"vwapChg_med={fmt(g['vwap_change_median'])} "
                f"priceRecovery_med={fmt(g['price_recovery_median'])} "
                f"episodeActive={g['episode_still_active_count']}/{g['n']} "
                f"jointActive={g['joint_still_active_count']}/{g['n']}"
            )
        lines.append("")

    lines += [
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Fixed checkpoints only: 0, +1, +3, +5 minutes.",
        "- No threshold search.",
        "- No classification rule is created.",
        "- Recovered/nonrecovered is determined by V27 future outcome only for analysis labels.",
        "- Features at each checkpoint use only information available by that checkpoint.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- No runner exit is defined.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_CAUSAL_EPISODE_CHECKPOINT_DIAGNOSTIC_V28",
        "episode_count": len(episodes),
        "checkpoint_row_count": len(checkpoint_rows),
        "checkpoints": list(CHECKPOINTS),
        "group_summary": group_rows,
        "guards": {
            "exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(CHECKPOINT_CSV, checkpoint_rows)
    write_csv(GROUP_CSV, group_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("CHECKPOINT CSV :", CHECKPOINT_CSV)
    print("GROUP CSV      :", GROUP_CSV)
    print("REPORT JSON    :", REPORT_JSON)
    print("SUMMARY        :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
