"""Deep validation of the single frozen Midpoint V3.2 exit candidate.

Frozen candidate
----------------
SL5_BE5_TRAIL3_AFTER10_TIME15

This module does NOT search or compare alternative policies. It validates the
single TRAIN-nominated policy produced by
MIDPOINT_V3_2_EXIT_MANAGEMENT_RESEARCH_V1.

Validation goals
----------------
- TRAIN separately.
- Pooled OOS_A/B/C/D.
- Per-OOS block.
- Direction split.
- BREAK_AND_GO vs BASE_THEN_GO vs OTHER.
- T+1 observation state.
- OI quality.
- Winner/loss distribution.
- Average winner / average loser.
- Payoff ratio.
- Profit factor.
- Maximum consecutive losses.
- Maximum drawdown in cumulative net percentage points.
- Largest-winner contribution.
- Structural false-positive contribution, diagnostic only.

No new thresholds. No new exits. No OOS_E/F/G/H. OOS-H remains pristine.
No live orders.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_FROZEN_EXIT_VALIDATION_V1"
SOURCE_VERSION = "MIDPOINT_V3_2_EXIT_MANAGEMENT_RESEARCH_V1"
FROZEN_POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
OOS_BLOCKS = {"OOS_A", "OOS_B", "OOS_C", "OOS_D"}

def load_json(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError("JSON root must be an object")
    return x

def finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def normalize_block(v: Any) -> str:
    return str(v).strip().upper().replace("-", "_")

def validate_source(x: dict[str, Any]) -> None:
    if x.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {x.get('research_version')!r}"
        )
    if x.get("train_only_nominated_policy") != FROZEN_POLICY_ID:
        raise ValueError(
            f"expected nominated policy {FROZEN_POLICY_ID}, got "
            f"{x.get('train_only_nominated_policy')!r}"
        )
    guard = x.get("leakage_guard") or {}
    if guard.get("policy_nomination_uses_train_only") is not True:
        raise ValueError("source does not prove TRAIN-only policy nomination")
    if guard.get("oos_a_b_c_d_used_for_policy_nomination") is not False:
        raise ValueError("source does not prove A-D excluded from nomination")
    if guard.get("oos_e_f_g_h_used") is not False:
        raise ValueError("source does not prove E/F/G/H excluded")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove H excluded")

def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None
    return gains / losses

def max_consecutive_losses(values: Sequence[float]) -> int:
    best = 0
    cur = 0
    for v in values:
        if v <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best

def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return max_dd

def largest_winner_contribution(values: Sequence[float], top_n: int) -> dict[str, Any]:
    positives = sorted((v for v in values if v > 0), reverse=True)
    total_positive = sum(positives)
    top = positives[:top_n]
    return {
        "top_n": top_n,
        "winner_count": len(positives),
        "top_n_sum_pct_points": sum(top),
        "all_winner_sum_pct_points": total_positive,
        "share_of_all_positive_pnl_pct": (
            sum(top) / total_positive * 100.0 if total_positive > 0 else None
        ),
    }

def chronology_key(r: dict[str, Any]) -> tuple[str, str]:
    return (str(r.get("session_date") or ""), str(r.get("direction") or ""))

def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=chronology_key)
    vals = [finite(r.get("net_return_pct")) for r in ordered]
    vals = [v for v in vals if v is not None]

    winners = [v for v in vals if v > 0]
    losers = [v for v in vals if v <= 0]

    avg_win = sum(winners) / len(winners) if winners else None
    avg_loss = sum(losers) / len(losers) if losers else None
    payoff = (
        avg_win / abs(avg_loss)
        if avg_win is not None and avg_loss is not None and avg_loss != 0
        else None
    )

    cumulative = []
    running = 0.0
    for r in ordered:
        v = finite(r.get("net_return_pct"))
        if v is None:
            continue
        running += v
        cumulative.append({
            "session_date": r.get("session_date"),
            "block": r.get("block"),
            "direction": r.get("direction"),
            "net_return_pct": v,
            "cumulative_net_pct_points": running,
        })

    return {
        "trade_count": len(vals),
        "winner_count": len(winners),
        "loser_or_flat_count": len(losers),
        "win_rate_pct": len(winners) / len(vals) * 100.0 if vals else None,
        "mean_net_pct": sum(vals) / len(vals) if vals else None,
        "median_net_pct": median(vals) if vals else None,
        "profit_factor": profit_factor(vals) if vals else None,
        "average_winner_pct": avg_win,
        "average_loser_pct": avg_loss,
        "payoff_ratio_avg_win_to_avg_loss": payoff,
        "best_trade_pct": max(vals) if vals else None,
        "worst_trade_pct": min(vals) if vals else None,
        "max_consecutive_losses": max_consecutive_losses(vals),
        "max_drawdown_pct_points": max_drawdown(vals),
        "largest_winner_contribution_top1": largest_winner_contribution(vals, 1),
        "largest_winner_contribution_top3": largest_winner_contribution(vals, 3),
        "largest_winner_contribution_top5": largest_winner_contribution(vals, 5),
        "cumulative_path": cumulative,
    }

def segmented(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(field) or "UNAVAILABLE")].append(r)
    return {k: summarize(v) for k, v in sorted(groups.items())}

def robustness_flags(train: dict[str, Any], oos: dict[str, Any]) -> dict[str, Any]:
    return {
        "train_profitable": (
            train.get("mean_net_pct") is not None
            and train["mean_net_pct"] > 0
            and train.get("profit_factor") is not None
            and train["profit_factor"] > 1
        ),
        "pooled_oos_profitable": (
            oos.get("mean_net_pct") is not None
            and oos["mean_net_pct"] > 0
            and oos.get("profit_factor") is not None
            and oos["profit_factor"] > 1
        ),
        "pooled_oos_payoff_ratio_gt_1": (
            oos.get("payoff_ratio_avg_win_to_avg_loss") is not None
            and oos["payoff_ratio_avg_win_to_avg_loss"] > 1
        ),
        "pooled_oos_positive_expectancy_with_sub_50_win_rate": (
            oos.get("mean_net_pct") is not None
            and oos["mean_net_pct"] > 0
            and oos.get("win_rate_pct") is not None
            and oos["win_rate_pct"] < 50
        ),
    }

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)

    rows = [
        r for r in source.get("rows", [])
        if r.get("policy_id") == FROZEN_POLICY_ID
        and r.get("status") == "EXITED"
        and normalize_block(r.get("block")) in ALLOWED_BLOCKS
    ]

    for r in rows:
        r["block"] = normalize_block(r.get("block"))

    train = [r for r in rows if r["block"] == "TRAIN"]
    oos = [r for r in rows if r["block"] in OOS_BLOCKS]

    train_summary = summarize(train)
    oos_summary = summarize(oos)

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "frozen_policy_id": FROZEN_POLICY_ID,
        "promotion_status": "NOT_PROMOTED",
        "train_summary": train_summary,
        "pooled_oos_a_d_summary": oos_summary,
        "oos_block_summaries": {
            block: summarize([r for r in rows if r["block"] == block])
            for block in ("OOS_A", "OOS_B", "OOS_C", "OOS_D")
        },
        "direction_summaries": {
            d: summarize([r for r in rows if r.get("direction") == d])
            for d in ("BEARISH", "BULLISH")
        },
        "segments": {
            "outcome_family": segmented(rows, "outcome_family"),
            "t1_observation_state": segmented(rows, "t1_observation_state"),
            "oi_quality": segmented(rows, "oi_quality"),
        },
        "robustness_flags": robustness_flags(train_summary, oos_summary),
        "governance": {
            "single_frozen_policy_only": True,
            "alternative_exit_search_performed": False,
            "train_negative_blocks_promotion": True,
            "oos_positive_does_not_override_negative_train": True,
            "oos_h_reserved_for_final_fresh_test": True,
        },
        "leakage_guard": {
            "entry_state_machine_modified": False,
            "exit_policy_modified": False,
            "new_threshold_selected": False,
            "new_exit_policy_selected": False,
            "oos_a_b_c_d_used_for_validation_only": True,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_only": True,
            "research_emits_trade_order": False,
        },
    }

    # Structural false-positive economics if outcome_family OTHER exists.
    result["structural_false_positive_diagnostic"] = summarize([
        r for r in rows if str(r.get("outcome_family")) == "OTHER"
    ])

    return result

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    result = analyze(load_json(Path(a.source)))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    compact = dict(result)
    compact["train_summary"] = {
        k: v for k, v in result["train_summary"].items()
        if k != "cumulative_path"
    }
    compact["pooled_oos_a_d_summary"] = {
        k: v for k, v in result["pooled_oos_a_d_summary"].items()
        if k != "cumulative_path"
    }
    for group in ("oos_block_summaries", "direction_summaries"):
        compact[group] = {
            name: {k: v for k, v in summary.items() if k != "cumulative_path"}
            for name, summary in result[group].items()
        }
    compact.pop("segments", None)

    print(json.dumps(compact, indent=2))

if __name__ == "__main__":
    main()
