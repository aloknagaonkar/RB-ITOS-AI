"""Frozen research candidate policy + transaction-cost sensitivity.

This module does not learn thresholds or timing from the input data.  It encodes
one provisional policy selected from OOS-E discovery evidence and evaluates it
on an OHLC backtest report:

BEARISH / PE:
  HIGH or VERY_HIGH confidence
  confirmation timing in T0, T+1, T+2

BULLISH / CE:
  HIGH or VERY_HIGH confidence
  confirmation timing in T+4/T+5

Entry/exit mechanics are inherited from the OHLC research path:
  entry: next-minute open
  target: +5%
  stop: -10%
  same-bar target+stop: assume stop first
  neither within 15m: exit at +15m close

The policy is a research candidate only. OOS-E was used to select it, therefore
OOS-E results are discovery evidence, not fresh validation. A later untouched
OOS set is required before promotion.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

POLICY_LABEL = "TARGET_5_STOP_10"
TARGET_PCT = 5.0
STOP_PCT = 10.0
CONFIDENCE_TIERS = {"HIGH", "VERY_HIGH"}
FROZEN_TIMING = {
    "BEARISH": {"T0", "T_PLUS_1", "T_PLUS_2"},
    "BULLISH": {"T_PLUS_4_5"},
}
DEFAULT_COST_SCENARIOS = (0.0, 0.25, 0.50, 1.00)


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


def _gross_realized(trade: dict[str, Any]) -> tuple[float | None, str]:
    result = trade.get("target_stop", {}).get(POLICY_LABEL, {}).get("result")
    if result == "TARGET_FIRST":
        return TARGET_PCT, "TARGET"
    if result == "STOP_FIRST":
        return -STOP_PCT, "STOP"
    if result == "AMBIGUOUS_SAME_BAR":
        return -STOP_PCT, "AMBIGUOUS_ASSUMED_STOP"
    if result == "NEITHER_WITHIN_15M":
        value = _finite_float(trade.get("returns_pct", {}).get("15m"))
        return value, "TIME_EXIT_15M" if value is not None else "UNAVAILABLE"
    return None, "UNAVAILABLE"


def _summarize(returns: list[float]) -> dict[str, Any]:
    positives = [x for x in returns if x > 0]
    negatives = [x for x in returns if x < 0]
    gross_profit = sum(positives)
    gross_loss = abs(sum(negatives))
    if gross_loss > 0:
        pf: float | None = gross_profit / gross_loss
    elif positives:
        pf = float("inf")
    else:
        pf = None
    return {
        "realized_count": len(returns),
        "positive_count": len(positives),
        "positive_pct": _pct(len(positives), len(returns)),
        "mean_return_pct": sum(returns) / len(returns) if returns else None,
        "median_return_pct": median(returns) if returns else None,
        "sum_return_pct_points": sum(returns),
        "profit_factor": pf,
        "best_return_pct": max(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
    }


def _matches_frozen_policy(trade: dict[str, Any], direction: str) -> bool:
    return (
        trade.get("direction") == direction
        and trade.get("confidence_tier") in CONFIDENCE_TIERS
        and trade.get("confirmation_offset_group") in FROZEN_TIMING[direction]
    )


def _direction_report(trades: list[dict[str, Any]], direction: str, costs: tuple[float, ...]) -> dict[str, Any]:
    selected = [t for t in trades if _matches_frozen_policy(t, direction)]
    gross_returns: list[float] = []
    exits: dict[str, int] = {}
    unavailable = 0
    by_timing: dict[str, list[float]] = {}

    for trade in selected:
        gross, exit_type = _gross_realized(trade)
        exits[exit_type] = exits.get(exit_type, 0) + 1
        if gross is None:
            unavailable += 1
            continue
        gross_returns.append(gross)
        timing = str(trade.get("confirmation_offset_group"))
        by_timing.setdefault(timing, []).append(gross)

    sensitivity = {}
    for cost in costs:
        net = [x - cost for x in gross_returns]
        sensitivity[f"ROUND_TRIP_COST_{cost:.2f}_PCT_POINTS"] = {
            "round_trip_cost_pct_points": cost,
            **_summarize(net),
        }

    return {
        "direction": direction,
        "option_side": "PE" if direction == "BEARISH" else "CE",
        "candidate_count": len(selected),
        "unavailable_count": unavailable,
        "allowed_confirmation_timings": sorted(FROZEN_TIMING[direction]),
        "exit_counts": dict(sorted(exits.items())),
        "gross": _summarize(gross_returns),
        "by_timing_gross": {k: _summarize(v) for k, v in sorted(by_timing.items())},
        "cost_sensitivity": sensitivity,
    }


def analyze(backtest_path: str | Path, costs: tuple[float, ...] = DEFAULT_COST_SCENARIOS) -> dict[str, Any]:
    source = json.loads(Path(backtest_path).read_text(encoding="utf-8"))
    if source.get("status") != "AVAILABLE":
        raise ValueError("OHLC backtest report is not AVAILABLE")
    if source.get("entry_rule") != "NEXT_MINUTE_OPEN":
        raise ValueError("expected NEXT_MINUTE_OPEN OHLC backtest")

    trades = list(source.get("trades", []))
    return {
        "status": "AVAILABLE",
        "source": str(backtest_path),
        "policy_status": "PROVISIONAL_FROZEN_RESEARCH_CANDIDATE",
        "validation_status": "REQUIRES_UNTOUCHED_FRESH_OOS",
        "selection_dataset_note": "OOS-E contributed to timing/exit selection; do not treat these results as fresh validation.",
        "entry_rule": "NEXT_MINUTE_OPEN",
        "candidate_filter": {
            "confidence_tiers": sorted(CONFIDENCE_TIERS),
            "bearish_confirmation_timings": sorted(FROZEN_TIMING["BEARISH"]),
            "bullish_confirmation_timings": sorted(FROZEN_TIMING["BULLISH"]),
        },
        "exit_rule": {
            "target_pct": TARGET_PCT,
            "stop_pct": STOP_PCT,
            "same_bar_ambiguity": "ASSUME_STOP_FIRST",
            "neither_within_15m": "EXIT_AT_PLUS_15M_CLOSE",
        },
        "cost_scenarios_pct_points": list(costs),
        "directions": {
            "bearish": _direction_report(trades, "BEARISH", costs),
            "bullish": _direction_report(trades, "BULLISH", costs),
        },
        "next_gate": {
            "required": True,
            "name": "FRESH_OOS_VALIDATION",
            "rule": "Apply this exact policy unchanged to an untouched session set before any promotion or further tuning.",
        },
    }


def _parse_costs(value: str) -> tuple[float, ...]:
    vals = tuple(float(x.strip()) for x in value.split(",") if x.strip())
    if not vals or any(x < 0 for x in vals):
        raise ValueError("cost scenarios must be non-negative comma-separated numbers")
    return vals


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate frozen PCR option candidate policy with cost sensitivity")
    parser.add_argument("--backtest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cost-scenarios", default="0,0.25,0.50,1.00")
    args = parser.parse_args()

    result = analyze(args.backtest, _parse_costs(args.cost_scenarios))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    compact = {
        "status": result["status"],
        "policy_status": result["policy_status"],
        "validation_status": result["validation_status"],
        "output": str(out),
        "bearish": result["directions"]["bearish"],
        "bullish": result["directions"]["bullish"],
    }
    print(json.dumps(compact, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
