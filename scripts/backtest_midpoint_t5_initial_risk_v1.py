#!/usr/bin/env python3
"""Strict T+5 unproved-trade policy comparison for Midpoint B/E and PM B/E.

Inputs are the immutable outputs of MIDPOINT_ENTRY_HEALTH_V1 and the causal
490-session good/bad feature study.  Every candidate uses a predeclared natural
zero condition.  No OOS or forward result is used to choose a threshold.

The counterfactual fill is the actual completed T+5 NIFTY close, represented by
the causal t5_close_progress field.  Existing proved-runner exits are preserved
unless the trade was still unproved at T+5 and the candidate would have exited.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_HEALTH = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-entry-health-490-v1/trade-health-features.csv"
)
DEFAULT_GOOD_BAD = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-good-bad-feature-study-490-v1/all-trade-features.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-t5-initial-risk-policy-v1"
)

POLICIES = (
    "CURRENT_POLICY",
    "T5_PRICE_NON_PROGRESS",
    "T5_DI_FAILURE_ZERO",
    "T5_COMBINED_EDGE_FAILURE_ZERO",
    "T5_PRICE_MOMENTUM_FAILURE",
    "T5_DI_AND_EDGE_FAILURE_ZERO",
    "T5_TWO_OF_THREE_FAILURE",
    "T5_DI_EDGE_VWAP_FAILURE_ZERO",
)


def finite(value) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def parse_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def trade_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row["session_date"]), str(row["segment"]), str(row["family"]),
        str(row["direction"]), str(row["entry_timestamp"]),
    )


def joined_rows(health_path: Path, good_bad_path: Path) -> list[dict]:
    health = read_csv(health_path)
    feature_rows = read_csv(good_bad_path)
    features = {trade_key(row): row for row in feature_rows}
    if len(features) != len(feature_rows):
        raise ValueError("duplicate trade key in good/bad features")
    output = []
    for row in health:
        key = trade_key(row)
        if key not in features:
            raise ValueError(f"missing good/bad feature row for {key}")
        merged = dict(features[key])
        merged.update(row)
        output.append(merged)
    if len(output) != len(feature_rows):
        raise ValueError(
            f"health/good-bad row mismatch: {len(output)} != {len(feature_rows)}"
        )
    return output


def t5_eligible(row: dict) -> bool:
    """True only when the trade exists and remains unproved at exact T+5."""
    if not parse_bool(row.get("t5_available")):
        return False
    t5_at = dt(row["entry_timestamp"]) + timedelta(minutes=5)
    exit_text = str(row.get("selected_exit_timestamp") or "")
    if exit_text and dt(exit_text) < t5_at:
        return False
    proof_text = str(row.get("plus20_timestamp") or "")
    if proof_text and dt(proof_text) <= t5_at:
        return False
    return finite(row.get("t5_close_progress")) is not None


def policy_trigger(policy: str, row: dict) -> bool:
    if policy == "CURRENT_POLICY" or not t5_eligible(row):
        return False
    progress = finite(row.get("t5_close_progress"))
    di_spread = finite(row.get("t5_directional_di_spread"))
    edge = finite(row.get("t5_combined_edge"))
    momentum = finite(row.get("t5_price_momentum_support"))
    vwap_change = finite(row.get("t5_directional_vwap_change"))
    if policy == "T5_PRICE_NON_PROGRESS":
        return progress is not None and progress <= 0
    if policy == "T5_DI_FAILURE_ZERO":
        return di_spread is not None and di_spread <= 0
    if policy == "T5_COMBINED_EDGE_FAILURE_ZERO":
        return edge is not None and edge <= 0
    if policy == "T5_PRICE_MOMENTUM_FAILURE":
        return momentum is not None and momentum <= 0
    if policy == "T5_DI_AND_EDGE_FAILURE_ZERO":
        return di_spread is not None and edge is not None and di_spread <= 0 and edge <= 0
    failures = (
        di_spread is not None and di_spread <= 0,
        edge is not None and edge <= 0,
        momentum is not None and momentum <= 0,
    )
    if policy == "T5_TWO_OF_THREE_FAILURE":
        return sum(failures) >= 2
    if policy == "T5_DI_EDGE_VWAP_FAILURE_ZERO":
        return (
            di_spread is not None and edge is not None and vwap_change is not None
            and di_spread <= 0 and edge <= 0 and vwap_change <= 0
        )
    raise ValueError(policy)


def current_points(row: dict) -> float | None:
    return finite(row.get("selected_exit_points"))


def policy_points(policy: str, row: dict) -> float | None:
    baseline = current_points(row)
    if baseline is None:
        return None
    return finite(row.get("t5_close_progress")) if policy_trigger(policy, row) else baseline


def profit_factor(points: list[float]) -> float | None:
    gross_win = sum(value for value in points if value > 0)
    gross_loss = -sum(value for value in points if value < 0)
    if gross_loss == 0:
        return None if gross_win else 0.0
    return gross_win / gross_loss


def session_returns(rows: list[dict], policy: str, sessions: list[str]) -> list[float]:
    by_day: dict[str, float] = defaultdict(float)
    for row in rows:
        value = policy_points(policy, row)
        if value is not None:
            by_day[row["session_date"]] += value
    return [by_day.get(day, 0.0) for day in sessions]


def max_drawdown(values: list[float]) -> float:
    equity = peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def session_sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    deviation = statistics.stdev(values)
    return statistics.mean(values) / deviation * math.sqrt(252) if deviation else None


def metric(rows: list[dict], policy: str, sessions: list[str]) -> dict:
    points = [policy_points(policy, row) for row in rows]
    clean = [float(value) for value in points if value is not None]
    daily = session_returns(rows, policy, sessions)
    return {
        "entries": len(rows), "completed": len(clean),
        "unresolved": len(rows) - len(clean),
        "sum_points": sum(clean),
        "mean_points": statistics.mean(clean) if clean else None,
        "median_points": statistics.median(clean) if clean else None,
        "positive": sum(value > 0 for value in clean),
        "zero": sum(value == 0 for value in clean),
        "negative": sum(value < 0 for value in clean),
        "win_rate_pct": 100.0 * sum(value > 0 for value in clean) / len(clean) if clean else None,
        "profit_factor": profit_factor(clean),
        "max_drawdown_points": max_drawdown(daily),
        "session_sharpe_annualized": session_sharpe(daily),
        "triggered": sum(policy_trigger(policy, row) for row in rows),
    }


def impact(rows: list[dict], policy: str) -> dict:
    changed = [row for row in rows if policy_trigger(policy, row)]
    comparable = [
        row for row in changed
        if current_points(row) is not None and finite(row.get("t5_close_progress")) is not None
    ]
    deltas = [
        float(row["t5_close_progress"]) - float(row["selected_exit_points"])
        for row in comparable
    ]
    good = [row for row in comparable if row["cohort"] == "GOOD_PLUS20_PROVED"]
    bad = [row for row in comparable if row["cohort"] == "BAD_UNPROVED_STRUCTURAL_LOSS"]
    return {
        "eligible": sum(t5_eligible(row) for row in rows),
        "changed": len(comparable),
        "delta_sum_points": sum(deltas),
        "delta_mean_changed": statistics.mean(deltas) if deltas else None,
        "improved": sum(value > 0 for value in deltas),
        "equal": sum(value == 0 for value in deltas),
        "harmed": sum(value < 0 for value in deltas),
        "bad_structural_triggered": len(bad),
        "bad_structural_recovery_points": sum(
            float(row["t5_close_progress"]) - float(row["selected_exit_points"])
            for row in bad
        ),
        "bad_structural_improved": sum(
            float(row["t5_close_progress"]) > float(row["selected_exit_points"])
            for row in bad
        ),
        "bad_structural_harmed": sum(
            float(row["t5_close_progress"]) < float(row["selected_exit_points"])
            for row in bad
        ),
        "later_plus20_winners_stopped": len(good),
        "later_plus20_winner_delta_points": sum(
            float(row["t5_close_progress"]) - float(row["selected_exit_points"])
            for row in good
        ),
    }


def session_universe(rows: list[dict]) -> dict[str, list[str]]:
    """Use the fixed split labels and include known zero-trade forward dates."""
    by_split: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_split[row["split"]].add(row["session_date"])
    # The source study writes only trade rows.  Its fixed split session counts
    # are enforced here; missing dates are represented by stable zero-day IDs.
    expected = {
        "IS_FROZEN_FIRST_70": 336,
        "OOS_FROZEN_LAST_30": 144,
        "FORWARD_LATEST_10": 10,
    }
    output = {}
    for split, count in expected.items():
        observed = sorted(by_split.get(split, set()))
        padding = [f"{split}:ZERO:{index:03d}" for index in range(count - len(observed))]
        if len(observed) > count:
            raise ValueError(f"{split} has more sessions than fixed universe")
        output[split] = sorted(observed + padding)
    output["ALL_490"] = (
        output["IS_FROZEN_FIRST_70"]
        + output["OOS_FROZEN_LAST_30"]
        + output["FORWARD_LATEST_10"]
    )
    return output


def selected_rows(rows: list[dict], split: str, segment=None, family=None, direction=None) -> list[dict]:
    return [
        row for row in rows
        if (split == "ALL_490" or row["split"] == split)
        and (segment is None or row["segment"] == segment)
        and (family is None or row["family"] == family)
        and (direction is None or row["direction"] == direction)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", type=Path, default=DEFAULT_HEALTH)
    parser.add_argument("--good-bad", type=Path, default=DEFAULT_GOOD_BAD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rows = joined_rows(args.health, args.good_bad)
    if len(rows) != 581:
        raise SystemExit(f"STOP: expected 581 trade rows, found {len(rows)}")
    universes = session_universe(rows)
    summary_rows = []
    impact_rows = []
    breakdown_rows = []
    for split in ("IS_FROZEN_FIRST_70", "OOS_FROZEN_LAST_30", "FORWARD_LATEST_10", "ALL_490"):
        members = selected_rows(rows, split)
        sessions = universes[split]
        for policy in POLICIES:
            summary_rows.append({"split": split, "policy": policy, **metric(members, policy, sessions)})
            impact_rows.append({"split": split, "policy": policy, **impact(members, policy)})
        groups = sorted({(row["segment"], row["family"], row["direction"]) for row in members})
        for segment, family, direction in groups:
            group = selected_rows(rows, split, segment, family, direction)
            for policy in POLICIES:
                breakdown_rows.append({
                    "split": split, "segment": segment, "family": family,
                    "direction": direction, "policy": policy,
                    **metric(group, policy, sessions), **impact(group, policy),
                })

    details = []
    for row in rows:
        detail = {
            key: row.get(key) for key in (
                "split", "segment", "session_date", "family", "direction",
                "entry_timestamp", "cohort", "plus20_timestamp",
                "selected_exit_policy", "selected_exit_timestamp",
                "selected_exit_points", "t5_timestamp", "t5_close_progress",
                "t5_directional_di_spread", "t5_combined_edge",
                "t5_price_momentum_support", "t5_directional_vwap_change",
            )
        }
        detail["t5_eligible"] = t5_eligible(row)
        for policy in POLICIES[1:]:
            detail[f"{policy}_trigger"] = policy_trigger(policy, row)
            detail[f"{policy}_points"] = policy_points(policy, row)
        details.append(detail)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "policy-summary.csv", summary_rows)
    write_csv(args.output_dir / "policy-impact.csv", impact_rows)
    write_csv(args.output_dir / "family-direction-breakdown.csv", breakdown_rows)
    write_csv(args.output_dir / "trade-level-decisions.csv", details)
    is_metrics = {row["policy"]: row for row in summary_rows if row["split"] == "IS_FROZEN_FIRST_70"}
    is_impacts = {row["policy"]: row for row in impact_rows if row["split"] == "IS_FROZEN_FIRST_70"}
    ranked = sorted(
        POLICIES[1:],
        key=lambda policy: is_impacts[policy]["delta_sum_points"],
        reverse=True,
    )
    report = {
        "model": "MIDPOINT_T5_INITIAL_RISK_POLICY_BACKTEST_V1",
        "trade_rows": len(rows),
        "fixed_session_universe": {"IS": 336, "OOS": 144, "FORWARD": 10, "ALL": 490},
        "eligibility": "active and unproved at exact completed T+5; +20 on/before T+5 bypasses candidate",
        "valuation": "actual completed T+5 NIFTY close via t5_close_progress",
        "policies": list(POLICIES),
        "is_ranking_by_net_delta": ranked,
        "is_current_policy": is_metrics["CURRENT_POLICY"],
        "is_candidate_metrics": {policy: is_metrics[policy] for policy in POLICIES[1:]},
        "is_candidate_impacts": {policy: is_impacts[policy] for policy in POLICIES[1:]},
        "interpretation": [
            "IS ranking is descriptive; no winner is automatically enabled.",
            "OOS and forward results are reported but never used to set a threshold.",
            "Good-trade damage includes trades unproved at T+5 that later reached +20.",
            "Profit factor, drawdown and Sharpe use underlying NIFTY points without costs.",
            "Session Sharpe and drawdown include fixed-universe zero-trade sessions.",
        ],
        "safety": {
            "research_only": True, "observation_only": True,
            "execution_enabled": False, "paper_order_enabled": False,
            "quantity": None, "order_sent": False, "live_modified": False,
        },
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("MIDPOINT T+5 INITIAL-RISK POLICY BACKTEST")
    print("Trades:", len(rows), "T+5 eligible:", sum(t5_eligible(row) for row in rows))
    for split in ("IS_FROZEN_FIRST_70", "OOS_FROZEN_LAST_30", "FORWARD_LATEST_10", "ALL_490"):
        print("\n", split)
        for policy in POLICIES:
            metric_row = next(row for row in summary_rows if row["split"] == split and row["policy"] == policy)
            impact_row = next(row for row in impact_rows if row["split"] == split and row["policy"] == policy)
            print(policy, {
                "sum": round(metric_row["sum_points"], 2),
                "win_rate": None if metric_row["win_rate_pct"] is None else round(metric_row["win_rate_pct"], 2),
                "profit_factor": None if metric_row["profit_factor"] is None else round(metric_row["profit_factor"], 4),
                "max_drawdown": round(metric_row["max_drawdown_points"], 2),
                "sharpe": None if metric_row["session_sharpe_annualized"] is None else round(metric_row["session_sharpe_annualized"], 4),
                "delta": round(impact_row["delta_sum_points"], 2),
                "bad_saved": impact_row["bad_structural_improved"],
                "later_winners_stopped": impact_row["later_plus20_winners_stopped"],
            })
    print("\nOutput:", args.output_dir / "report.json")
    print("Research only: live decisions, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
