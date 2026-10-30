"""Exact option P&L backtest for promoted midpoint continuation arms.

Promoted, frozen decision arms:
1. RED_BEARISH_CONTINUATION -> exact ATM PE
2. GREEN_BULLISH_CONTINUATION -> exact ATM CE

Consumes MIDPOINT_FOUR_ARM_DECISION_RESEARCH_V1 output. Only TRADE_NOW rows
from the two primary continuation arms are eligible.

Execution model:
- selected strike/contract = exact moving ATM at decision timestamp;
- entry = next exact 1-minute option OPEN;
- same exact contract for all subsequent marks;
- no strike/contract substitution;
- gross close returns at +1/+3/+5/+10/+15 minutes;
- net returns subtract a fixed 0.50 percentage-point round-trip cost;
- 15m MFE/MAE;
- descriptive target/stop matrix;
- no exit rule is selected by this module.

This is backtest research only; no order is emitted.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_PRIMARY_CONTINUATION_OPTION_BACKTEST_V1"
SOURCE_VERSION = "MIDPOINT_FOUR_ARM_DECISION_RESEARCH_V1"

PROMOTED_ARMS = {
    "RED_BEARISH_CONTINUATION": {
        "option_side": "PE",
        "instrument_field": "pe_instrument_key",
    },
    "GREEN_BULLISH_CONTINUATION": {
        "option_side": "CE",
        "instrument_field": "ce_instrument_key",
    },
}

ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
RETURN_HORIZONS = (1, 3, 5, 10, 15)
TARGETS_PCT = (5.0, 10.0, 15.0)
STOPS_PCT = (5.0, 10.0)
ROUND_TRIP_COST_PCT = 0.50


def _dt(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


def _median(values: Sequence[float]) -> float | None:
    return median(values) if values else None


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_positioning(path: Path) -> dict[tuple[str, datetime], list[dict[str, str]]]:
    result: dict[tuple[str, datetime], list[dict[str, str]]] = {}
    for row in _load_csv(path):
        result.setdefault((row["session_date"], _dt(row["timestamp"])), []).append(row)
    return result


def _load_ohlc(path: Path) -> dict[tuple[str, str, datetime], dict[str, str]]:
    idx: dict[tuple[str, str, datetime], dict[str, str]] = {}
    for row in _load_csv(path):
        idx[(row["session_date"], row["instrument_key"], _dt(row["timestamp"]))] = row
    return idx


def _atm_row(rows: Sequence[dict[str, str]]) -> dict[str, str] | None:
    exact = [row for row in rows if _finite(row.get("strike_offset")) == 0.0]
    if len(exact) == 1:
        return exact[0]
    # Do not substitute another strike. Ambiguous or missing exact ATM is unavailable.
    return None


def _ret(price: float | None, entry: float | None) -> float | None:
    if price is None or entry is None or entry <= 0:
        return None
    return 100.0 * (price - entry) / entry


def _net(gross: float | None) -> float | None:
    return gross - ROUND_TRIP_COST_PCT if gross is not None else None


def _target_stop_result(
    bars: Sequence[tuple[int, dict[str, str]]],
    *,
    entry: float,
    target_pct: float,
    stop_pct: float,
) -> dict[str, Any]:
    target_px = entry * (1.0 + target_pct / 100.0)
    stop_px = entry * (1.0 - stop_pct / 100.0)

    for minute, row in bars:
        high = _finite(row.get("high"))
        low = _finite(row.get("low"))
        if high is None or low is None:
            continue
        target_hit = high >= target_px
        stop_hit = low <= stop_px
        if target_hit and stop_hit:
            return {"result": "AMBIGUOUS_SAME_BAR", "minute": minute}
        if target_hit:
            return {"result": "TARGET_FIRST", "minute": minute}
        if stop_hit:
            return {"result": "STOP_FIRST", "minute": minute}
    return {"result": "NEITHER_WITHIN_15M", "minute": None}


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _return_summary(values: Sequence[float]) -> dict[str, Any]:
    vals = list(values)
    return {
        "available_count": len(vals),
        "positive_count": sum(x > 0 for x in vals),
        "positive_pct": _pct(sum(x > 0 for x in vals), len(vals)),
        "mean_pct": sum(vals) / len(vals) if vals else None,
        "median_pct": _median(vals),
        "profit_factor": _profit_factor(vals),
    }


def _summarize(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "trade_candidate_count": len(trades),
        "instrument_available_count": sum(bool(x.get("instrument_key")) for x in trades),
        "entry_available_count": sum(x.get("entry_premium") is not None for x in trades),
        "complete_15m_path_count": sum(
            x.get("gross_returns_pct", {}).get("15m") is not None for x in trades
        ),
    }

    for horizon in RETURN_HORIZONS:
        key = f"{horizon}m"
        gross = [
            float(x["gross_returns_pct"][key])
            for x in trades
            if x.get("gross_returns_pct", {}).get(key) is not None
        ]
        net = [
            float(x["net_returns_pct"][key])
            for x in trades
            if x.get("net_returns_pct", {}).get(key) is not None
        ]
        result[f"gross_return_{key}"] = _return_summary(gross)
        result[f"net_return_{key}"] = _return_summary(net)

    mfe = [float(x["mfe_pct_15m"]) for x in trades if x.get("mfe_pct_15m") is not None]
    mae = [float(x["mae_pct_15m"]) for x in trades if x.get("mae_pct_15m") is not None]
    result["intrabar_excursion_15m"] = {
        "available_count": len(mfe),
        "median_mfe_pct": _median(mfe),
        "median_mae_pct": _median(mae),
    }

    matrix: dict[str, Any] = {}
    for target in TARGETS_PCT:
        for stop in STOPS_PCT:
            label = f"TARGET_{int(target)}_STOP_{int(stop)}"
            outcomes = [
                x.get("target_stop", {}).get(label, {}).get("result")
                for x in trades
            ]
            outcomes = [x for x in outcomes if x]
            counts = Counter(outcomes)
            decisive = counts["TARGET_FIRST"] + counts["STOP_FIRST"]
            matrix[label] = {
                "available_count": len(outcomes),
                "target_first": counts["TARGET_FIRST"],
                "stop_first": counts["STOP_FIRST"],
                "ambiguous_same_bar": counts["AMBIGUOUS_SAME_BAR"],
                "neither_within_15m": counts["NEITHER_WITHIN_15M"],
                "target_first_pct_of_decisive": _pct(
                    counts["TARGET_FIRST"], decisive
                ),
            }
    result["target_stop_matrix"] = matrix
    return result


def _parse_block(value: str) -> tuple[str, Path, Path]:
    parts = value.split("|")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "--block must be NAME|POSITIONING_CSV|OPTION_OHLC_CSV"
        )
    name = parts[0].upper().replace("-", "_")
    if name not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(f"unsupported/forbidden block {name}")
    return name, Path(parts[1]), Path(parts[2])


def _validate_source(payload: dict[str, Any]) -> None:
    if payload.get("status") != "AVAILABLE":
        raise ValueError("decision source must be AVAILABLE")
    if payload.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {payload.get('research_version')!r}"
        )
    guard = payload.get("leakage_guard") or {}
    required = {
        "thresholds_derived_from_train_only": True,
        "score_cutoffs_derived_from_train_only": True,
        "oos_a_b_c_d_used_for_threshold_selection": False,
        "oos_e_f_g_h_used": False,
        "oos_h_used": False,
        "pnl_used_for_rule_selection": False,
    }
    for key, expected in required.items():
        if guard.get(key) is not expected:
            raise ValueError(f"decision leakage guard failed: {key}")


def analyze(
    decision_path: Path,
    blocks: Sequence[tuple[str, Path, Path]],
) -> dict[str, Any]:
    decisions = json.loads(decision_path.read_text(encoding="utf-8"))
    _validate_source(decisions)

    supplied = {name for name, _, _ in blocks}
    if supplied != ALLOWED_BLOCKS:
        raise ValueError(
            "requires exactly TRAIN, OOS_A, OOS_B, OOS_C, OOS_D; "
            "E/F/G/H are forbidden"
        )

    resources: dict[str, tuple[
        dict[tuple[str, datetime], list[dict[str, str]]],
        dict[tuple[str, str, datetime], dict[str, str]],
    ]] = {}
    for name, positioning_path, ohlc_path in blocks:
        resources[name] = (
            _load_positioning(positioning_path),
            _load_ohlc(ohlc_path),
        )

    trades: list[dict[str, Any]] = []

    for arm_name, arm_cfg in PROMOTED_ARMS.items():
        arm = decisions.get("arms", {}).get(arm_name)
        if not arm:
            raise ValueError(f"missing promoted arm {arm_name}")

        for row in arm.get("rows", []):
            if row.get("decision") != "TRADE_NOW":
                continue

            block = str(row.get("block"))
            if block not in resources:
                raise ValueError(f"missing block resources for {block}")

            positioning, ohlc = resources[block]
            session = str(row["session_date"])
            decision_ts = _dt(str(row["decision_time"]))

            atm = _atm_row(positioning.get((session, decision_ts), []))
            instrument_key = (
                atm.get(arm_cfg["instrument_field"])
                if atm is not None
                else None
            )
            strike = _finite(atm.get("strike")) if atm is not None else None
            moving_atm = _finite(atm.get("moving_atm")) if atm is not None else None

            entry_ts = decision_ts + timedelta(minutes=1)
            entry_row = (
                ohlc.get((session, instrument_key, entry_ts))
                if instrument_key
                else None
            )
            entry = _finite(entry_row.get("open")) if entry_row else None

            bars: list[tuple[int, dict[str, str]]] = []
            if instrument_key:
                for minute in range(0, 16):
                    bar = ohlc.get(
                        (session, instrument_key, entry_ts + timedelta(minutes=minute))
                    )
                    if bar is not None:
                        bars.append((minute, bar))

            gross_returns: dict[str, float | None] = {}
            net_returns: dict[str, float | None] = {}
            for horizon in RETURN_HORIZONS:
                mark = (
                    ohlc.get(
                        (
                            session,
                            instrument_key,
                            entry_ts + timedelta(minutes=horizon),
                        )
                    )
                    if instrument_key
                    else None
                )
                gross = _ret(_finite(mark.get("close")) if mark else None, entry)
                gross_returns[f"{horizon}m"] = gross
                net_returns[f"{horizon}m"] = _net(gross)

            highs = [_finite(bar.get("high")) for _, bar in bars]
            lows = [_finite(bar.get("low")) for _, bar in bars]
            highs = [x for x in highs if x is not None]
            lows = [x for x in lows if x is not None]
            mfe = _ret(max(highs), entry) if highs else None
            mae = _ret(min(lows), entry) if lows else None

            target_stop: dict[str, Any] = {}
            if entry is not None and entry > 0:
                for target in TARGETS_PCT:
                    for stop in STOPS_PCT:
                        label = f"TARGET_{int(target)}_STOP_{int(stop)}"
                        target_stop[label] = _target_stop_result(
                            bars,
                            entry=entry,
                            target_pct=target,
                            stop_pct=stop,
                        )

            trades.append({
                "session_date": session,
                "block": block,
                "arm": arm_name,
                "setup_type": row.get("setup_type"),
                "option_side": arm_cfg["option_side"],
                "decision_time": decision_ts.isoformat(),
                "decision_score": row.get("score"),
                "decision_score_max": row.get("score_max"),
                "decision_evidence_score_pct": row.get("evidence_score_pct"),
                "reason_codes": row.get("reason_codes"),
                "actual_structural_outcome": row.get("actual_outcome"),
                "atm_rule": "EXACT_MOVING_ATM_AT_DECISION_TIME",
                "atm_strike": strike,
                "moving_atm": moving_atm,
                "instrument_key": instrument_key,
                "entry_rule": "NEXT_EXACT_1M_OPEN",
                "entry_timestamp": entry_ts.isoformat(),
                "entry_premium": entry,
                "gross_returns_pct": gross_returns,
                "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
                "net_returns_pct": net_returns,
                "mfe_pct_15m": mfe,
                "mae_pct_15m": mae,
                "target_stop": target_stop,
            })

    by_arm = {
        arm: _summarize([x for x in trades if x["arm"] == arm])
        for arm in PROMOTED_ARMS
    }
    by_block = {
        block: _summarize([x for x in trades if x["block"] == block])
        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")
    }
    by_arm_and_block = {
        arm: {
            block: _summarize([
                x for x in trades if x["arm"] == arm and x["block"] == block
            ])
            for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")
        }
        for arm in PROMOTED_ARMS
    }

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_research_version": SOURCE_VERSION,
        "research_status": "EXACT_ATM_OPTION_ECONOMICS_RESEARCH",
        "promoted_arms": list(PROMOTED_ARMS),
        "execution_model": {
            "strike_selection": "exact moving ATM at T+3 decision timestamp",
            "entry": "next exact 1-minute option OPEN",
            "contract_policy": "same exact selected contract; no substitution",
            "return_horizons_minutes": list(RETURN_HORIZONS),
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "target_grid_pct": list(TARGETS_PCT),
            "stop_grid_pct": list(STOPS_PCT),
            "target_stop_grid_is_descriptive_only": True,
        },
        "overall_summary": _summarize(trades),
        "arm_summaries": by_arm,
        "block_summaries": by_block,
        "arm_block_summaries": by_arm_and_block,
        "leakage_guard": {
            "decision_rules_changed_after_pnl": False,
            "red_bearish_cutoff_changed": False,
            "green_bullish_cutoff_changed": False,
            "reclaim_arms_backtested": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "same_contract_after_entry": True,
            "strike_substitution_allowed": False,
            "backtest_emits_trade_order": False,
        },
        "trades": trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exact option backtest for promoted midpoint continuation arms"
    )
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--block", action="append", required=True, type=_parse_block)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = analyze(Path(args.decisions), args.block)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": RESEARCH_VERSION,
        "overall_summary": result["overall_summary"],
        "arm_summaries": result["arm_summaries"],
        "block_summaries": result["block_summaries"],
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
