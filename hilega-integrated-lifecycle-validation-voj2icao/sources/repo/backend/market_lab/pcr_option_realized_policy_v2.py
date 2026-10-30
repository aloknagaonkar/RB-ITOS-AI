"""Frozen realized-exit evaluator for PCR Research Methodology v2.

This module intentionally applies ONE predeclared policy to every candidate in
an OHLC backtest produced by ``pcr_option_ohlc_backtest_v2``.  It does not
filter by confirmation timing and does not inspect outcome labels to select
trades.

Frozen policy v1 for Methodology v2:
- candidate universe: all HIGH/VERY_HIGH candidates emitted by backtest v2
- entry: NEXT_MINUTE_OPEN (validated from source backtest)
- contract: exact T0 ATM instrument, no substitution (validated from source)
- target: +5%
- stop: -10%
- if target and stop are both touched in one 1-minute candle: assume STOP first
- if neither is touched within 15 minutes: exit at +15m close
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

POLICY_ID = "PCR_OPTION_REALIZED_POLICY_V2_FROZEN_5_10_15"
TARGET_STOP_LABEL = "TARGET_5_STOP_10"
TARGET_RETURN_PCT = 5.0
STOP_RETURN_PCT = -10.0
TIME_EXIT_MINUTES = 15
COSTS_PCT_POINTS = (0.0, 0.25, 0.50, 1.00)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return float("inf") if gains > 0 else None
    return gains / losses


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "realized_count": 0,
            "positive_count": 0,
            "positive_pct": None,
            "mean_return_pct": None,
            "median_return_pct": None,
            "sum_return_pct_points": None,
            "profit_factor": None,
            "best_return_pct": None,
            "worst_return_pct": None,
        }
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    med = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    pos = sum(v > 0 for v in values)
    return {
        "realized_count": n,
        "positive_count": pos,
        "positive_pct": 100.0 * pos / n,
        "mean_return_pct": sum(values) / n,
        "median_return_pct": med,
        "sum_return_pct_points": sum(values),
        "profit_factor": _profit_factor(values),
        "best_return_pct": max(values),
        "worst_return_pct": min(values),
    }


def _realize_trade(trade: dict[str, Any]) -> dict[str, Any]:
    ts = trade.get("target_stop", {}).get(TARGET_STOP_LABEL, {})
    result = ts.get("result")

    if result == "TARGET_FIRST":
        return {"exit_type": "TARGET", "realized_return_pct": TARGET_RETURN_PCT}
    if result == "STOP_FIRST":
        return {"exit_type": "STOP", "realized_return_pct": STOP_RETURN_PCT}
    if result == "AMBIGUOUS_SAME_BAR":
        return {"exit_type": "AMBIGUOUS_ASSUMED_STOP", "realized_return_pct": STOP_RETURN_PCT}
    if result == "NEITHER_WITHIN_15M":
        ret15 = _num(trade.get("returns_pct", {}).get("15m"))
        if ret15 is None:
            return {"exit_type": "UNAVAILABLE", "realized_return_pct": None}
        return {"exit_type": "TIME_EXIT_15M", "realized_return_pct": ret15}
    return {"exit_type": "UNAVAILABLE", "realized_return_pct": None}


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exits = Counter(str(r["exit_type"]) for r in rows)
    gross = [float(r["realized_return_pct"]) for r in rows if r.get("realized_return_pct") is not None]
    costs: dict[str, Any] = {}
    for c in COSTS_PCT_POINTS:
        net = [v - c for v in gross]
        costs[f"ROUND_TRIP_COST_{c:.2f}_PCT_POINTS"] = {
            "round_trip_cost_pct_points": c,
            **_stats(net),
        }
    return {
        "candidate_count": len(rows),
        "realized_count": len(gross),
        "unavailable_count": len(rows) - len(gross),
        "exit_counts": dict(sorted(exits.items())),
        "gross": _stats(gross),
        "cost_sensitivity": costs,
    }


def analyze(backtest_path: str | Path) -> dict[str, Any]:
    src = json.loads(Path(backtest_path).read_text(encoding="utf-8"))
    if src.get("status") != "AVAILABLE":
        raise ValueError("backtest must have status AVAILABLE")
    if src.get("methodology_version") != "PCR_RESEARCH_METHODOLOGY_V2":
        raise ValueError("backtest must be PCR_RESEARCH_METHODOLOGY_V2")
    if src.get("entry_rule") != "NEXT_MINUTE_OPEN":
        raise ValueError("unexpected entry rule; frozen policy requires NEXT_MINUTE_OPEN")
    if src.get("contract_selection_rule") != "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION":
        raise ValueError("unexpected contract selection rule")
    if src.get("confidence_profile") != "FROZEN_D5_D15":
        raise ValueError("primary frozen policy requires FROZEN_D5_D15")

    realized_trades: list[dict[str, Any]] = []
    for trade in src.get("trades", []):
        r = _realize_trade(trade)
        realized_trades.append({
            "session_date": trade.get("session_date"),
            "stage2_timestamp": trade.get("stage2_timestamp"),
            "direction": trade.get("direction"),
            "option_side": trade.get("option_side"),
            "confidence_tier": trade.get("confidence_tier"),
            "confirmation_offset_minutes": trade.get("confirmation_offset_minutes"),
            "confirmation_offset_group": trade.get("confirmation_offset_group"),
            "instrument_key": trade.get("instrument_key"),
            "entry_timestamp": trade.get("entry_timestamp"),
            "entry_premium": trade.get("entry_premium"),
            **r,
        })

    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        rows = [r for r in realized_trades if r.get("direction") == direction]
        directions[direction.lower()] = {
            "direction": direction,
            "option_side": "PE" if direction == "BEARISH" else "CE",
            "timing_filter": "NONE_ALL_FIRST_CONFIRMATIONS_T0_TO_TPLUS5",
            **_summarize(rows),
        }

    all_summary = _summarize(realized_trades)
    return {
        "status": "AVAILABLE",
        "policy_id": POLICY_ID,
        "policy_status": "FROZEN_FOR_UNTOUCHED_OOS_G",
        "methodology_version": "PCR_RESEARCH_METHODOLOGY_V2",
        "confidence_profile": "FROZEN_D5_D15",
        "source_backtest": str(backtest_path),
        "entry_rule": "NEXT_MINUTE_OPEN",
        "contract_selection_rule": "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION",
        "timing_filter": "NONE_ALL_FIRST_CONFIRMATIONS_T0_TO_TPLUS5",
        "target_pct": TARGET_RETURN_PCT,
        "stop_pct": abs(STOP_RETURN_PCT),
        "time_exit_minutes": TIME_EXIT_MINUTES,
        "ambiguous_same_bar_policy": "ASSUME_STOP_FIRST",
        "neither_policy": "EXIT_AT_PLUS_15M_CLOSE",
        "directions": directions,
        "combined": all_summary,
        "trades": realized_trades,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Frozen realized-exit policy evaluator for PCR Methodology v2")
    p.add_argument("--backtest", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = analyze(args.backtest)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "policy_id": result["policy_id"],
        "policy_status": result["policy_status"],
        "bearish": result["directions"]["bearish"],
        "bullish": result["directions"]["bullish"],
        "combined": result["combined"],
        "output": str(out),
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
