"""Realized exit-policy evaluation for PCR option candidates.

Consumes the OHLC backtest report and turns the descriptive target/stop matrix into
an explicit, conservative trade-exit simulation:
- target first -> +target%
- stop first -> -stop%
- target+stop in same 1m bar -> assume stop first (conservative)
- neither within 15m -> exit at +15m close

No execution costs are applied; this remains research evidence only.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

POLICIES = (
    (5.0, 5.0),
    (5.0, 10.0),
    (10.0, 5.0),
    (10.0, 10.0),
    (15.0, 5.0),
    (15.0, 10.0),
)
TIMING_GROUPS = ("T0", "T_PLUS_1", "T_PLUS_2", "T_PLUS_3", "T_PLUS_4_5")
CONFIDENCE_TIERS = ("HIGH", "VERY_HIGH")


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(n: int, d: int) -> float | None:
    return (100.0 * n / d) if d else None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _policy_label(target: float, stop: float) -> str:
    return f"TARGET_{int(target)}_STOP_{int(stop)}"


def _realized_trade_return(trade: dict[str, Any], target: float, stop: float) -> tuple[float | None, str]:
    label = _policy_label(target, stop)
    result = trade.get("target_stop", {}).get(label, {}).get("result")
    if result == "TARGET_FIRST":
        return target, "TARGET"
    if result == "STOP_FIRST":
        return -stop, "STOP"
    if result == "AMBIGUOUS_SAME_BAR":
        # Minute OHLC cannot determine ordering. Conservative assumption avoids
        # manufacturing optimistic fills.
        return -stop, "AMBIGUOUS_ASSUMED_STOP"
    if result == "NEITHER_WITHIN_15M":
        time_exit = _finite_float(trade.get("returns_pct", {}).get("15m"))
        return time_exit, "TIME_EXIT_15M" if time_exit is not None else "UNAVAILABLE"
    return None, "UNAVAILABLE"


def _summarize_policy(trades: list[dict[str, Any]], target: float, stop: float) -> dict[str, Any]:
    realized: list[float] = []
    exit_counts: Counter[str] = Counter()
    for trade in trades:
        ret, exit_type = _realized_trade_return(trade, target, stop)
        exit_counts[exit_type] += 1
        if ret is not None:
            realized.append(ret)

    positives = [x for x in realized if x > 0]
    negatives = [x for x in realized if x < 0]
    gross_profit = sum(positives)
    gross_loss_abs = abs(sum(negatives))
    return {
        "candidate_count": len(trades),
        "realized_count": len(realized),
        "unavailable_count": len(trades) - len(realized),
        "exit_counts": dict(sorted(exit_counts.items())),
        "positive_count": len(positives),
        "positive_pct": _pct(len(positives), len(realized)),
        "mean_realized_return_pct": (sum(realized) / len(realized)) if realized else None,
        "median_realized_return_pct": _median(realized),
        "best_realized_return_pct": max(realized) if realized else None,
        "worst_realized_return_pct": min(realized) if realized else None,
        "profit_factor_gross": (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else (None if not positives else float("inf")),
        "sum_realized_return_pct_points": sum(realized),
        "breakeven_target_first_pct_if_all_resolve_at_target_or_stop": 100.0 * stop / (target + stop),
        "ambiguous_policy": "ASSUME_STOP_FIRST",
        "neither_policy": "EXIT_AT_PLUS_15M_CLOSE",
    }


def _policy_bundle(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        _policy_label(target, stop): _summarize_policy(trades, target, stop)
        for target, stop in POLICIES
    }


def analyze(backtest_path: str | Path) -> dict[str, Any]:
    source = json.loads(Path(backtest_path).read_text(encoding="utf-8"))
    if source.get("status") != "AVAILABLE":
        raise ValueError("OHLC backtest report is not AVAILABLE")
    if source.get("entry_rule") != "NEXT_MINUTE_OPEN":
        raise ValueError("expected NEXT_MINUTE_OPEN OHLC backtest")

    trades = list(source.get("trades", []))
    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        rows = [t for t in trades if t.get("direction") == direction]
        by_timing = {
            group: _policy_bundle([t for t in rows if t.get("confirmation_offset_group") == group])
            for group in TIMING_GROUPS
        }
        by_confidence = {
            tier: _policy_bundle([t for t in rows if t.get("confidence_tier") == tier])
            for tier in CONFIDENCE_TIERS
        }
        directions[direction.lower()] = {
            "direction": direction,
            "option_side": "PE" if direction == "BEARISH" else "CE",
            "candidate_count": len(rows),
            "overall": _policy_bundle(rows),
            "by_confirmation_timing": by_timing,
            "by_confidence_tier": by_confidence,
        }

    return {
        "status": "AVAILABLE",
        "source": str(backtest_path),
        "entry_rule": "NEXT_MINUTE_OPEN",
        "exit_horizon_minutes": 15,
        "same_bar_ambiguity_rule": "ASSUME_STOP_FIRST",
        "neither_hit_rule": "EXIT_AT_PLUS_15M_CLOSE",
        "policies": [
            {
                "label": _policy_label(target, stop),
                "target_pct": target,
                "stop_pct": stop,
                "breakeven_target_first_pct_if_binary": 100.0 * stop / (target + stop),
            }
            for target, stop in POLICIES
        ],
        "directions": directions,
        "methodology": [
            "Consumes candidate trades from the NEXT_MINUTE_OPEN OHLC backtest; no PCR thresholds are relearned.",
            "When the target is hit first, realized return is exactly the target percentage.",
            "When the stop is hit first, realized return is exactly minus the stop percentage.",
            "When both target and stop are touched in the same one-minute candle, the simulation conservatively assumes the stop occurred first.",
            "When neither level is touched within 15 minutes, the trade exits at the option close at +15 minutes.",
        ],
        "limitations": [
            "No brokerage, fees, taxes, bid/ask spread, slippage, execution latency, or quantity sizing is included.",
            "The same-bar conservative assumption can understate performance, but avoids optimistic ordering that one-minute OHLC cannot prove.",
            "This evaluates only OOS-E candidate trades already selected by HIGH/VERY_HIGH PCR confidence and positioning confirmation; sample sizes in timing subgroups are small.",
            "Policy comparisons are research evidence, not a promoted live trading rule.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate realized target/stop/time-exit policies for PCR option candidates")
    parser.add_argument("--backtest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = analyze(args.backtest)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    preferred = "TARGET_5_STOP_10"
    compact = {
        "status": result["status"],
        "output": str(out),
        "reference_policy": preferred,
        "bearish": result["directions"]["bearish"]["overall"][preferred],
        "bullish": result["directions"]["bullish"]["overall"][preferred],
    }
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
