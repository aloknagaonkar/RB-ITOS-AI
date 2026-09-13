from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from market_lab.midpoint_v3_2_oos_h_freeze_contract_v1 import (
    CONTRACT_RULE,
    ENTRY_RULE,
    EXIT_POLICY_ID,
    FROZEN_EXIT,
    ROUND_TRIP_COST_PCT_POINTS,
    load_json,
    verify_contract_files,
)

RESEARCH_VERSION = "MIDPOINT_V3_2_OOS_H_FROZEN_EXIT_REPLAY_V1"
EXPECTED_BLOCK = "OOS_H"


def parse_dt(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("missing timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def finite(value: Any, field: str) -> float:
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing {field}")
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"non-finite {field}")
    return x


def pct_return(entry: float, exit_price: float) -> float:
    if entry <= 0:
        raise ValueError("entry premium must be positive")
    return ((exit_price / entry) - 1.0) * 100.0


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def max_consecutive_losses(values: Sequence[float]) -> int:
    best = current = 0
    for value in values:
        if value <= 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def max_drawdown_pct_points(values: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return worst


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_return_pct"]) for row in rows]
    if not values:
        return {
            "trade_count": 0,
            "winner_count": 0,
            "win_rate_pct": None,
            "mean_net_pct": None,
            "median_net_pct": None,
            "profit_factor": None,
        }
    winners = [v for v in values if v > 0]
    losers = [v for v in values if v <= 0]
    return {
        "trade_count": len(values),
        "winner_count": len(winners),
        "loser_or_flat_count": len(losers),
        "win_rate_pct": 100.0 * len(winners) / len(values),
        "mean_net_pct": statistics.fmean(values),
        "median_net_pct": statistics.median(values),
        "profit_factor": profit_factor(values),
        "average_winner_pct": statistics.fmean(winners) if winners else None,
        "average_loser_pct": statistics.fmean(losers) if losers else None,
        "payoff_ratio_avg_win_to_avg_loss": (
            statistics.fmean(winners) / abs(statistics.fmean(losers))
            if winners and losers and statistics.fmean(losers) != 0
            else None
        ),
        "best_trade_pct": max(values),
        "worst_trade_pct": min(values),
        "max_consecutive_losses": max_consecutive_losses(values),
        "max_drawdown_pct_points": max_drawdown_pct_points(values),
        "sum_net_pct_points": sum(values),
        "exit_reasons": dict(Counter(row["exit_reason"] for row in rows)),
    }


def load_ohlc(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"session_date", "instrument_key", "timestamp", "open", "high", "low", "close"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"OHLC CSV missing columns: {sorted(missing)}")
        for raw in reader:
            row = dict(raw)
            row["open"] = finite(row["open"], "open")
            row["high"] = finite(row["high"], "high")
            row["low"] = finite(row["low"], "low")
            row["close"] = finite(row["close"], "close")
            row["_dt"] = parse_dt(row["timestamp"])
            index[(row["session_date"], row["instrument_key"])].append(row)
    for rows in index.values():
        rows.sort(key=lambda r: r["_dt"])
    return index


def _find_candidate_lists(value: Any) -> Iterable[list[dict[str, Any]]]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _find_candidate_lists(item)
    elif isinstance(value, list):
        if value and all(isinstance(x, dict) for x in value):
            yield value
        for item in value:
            yield from _find_candidate_lists(item)


def _looks_like_trade(row: dict[str, Any]) -> bool:
    keys = set(row)
    return (
        ("instrument_key" in keys or "option_instrument_key" in keys)
        and ("entry_timestamp" in keys or "entry_time" in keys or "entry_at" in keys)
        and ("entry_price" in keys or "entry_open" in keys or "entry_premium" in keys)
    )


def economics_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    preferred = []
    for key in ("rows", "trade_rows", "trades", "candidates"):
        value = payload.get(key)
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            preferred.append(value)
    lists = preferred or list(_find_candidate_lists(payload))
    for rows in lists:
        matching = [dict(row) for row in rows if _looks_like_trade(row)]
        if matching:
            return matching
    raise ValueError(
        "could not locate trade rows in economics JSON; expected rows with "
        "instrument_key, entry_timestamp and entry_price-like fields"
    )


def get_first(row: dict[str, Any], names: Sequence[str], required: bool = True) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    if required:
        raise ValueError(f"missing one of fields {list(names)}")
    return None


def normalize_trade(row: dict[str, Any]) -> dict[str, Any]:
    block = str(row.get("block") or EXPECTED_BLOCK).upper()
    if block != EXPECTED_BLOCK:
        raise ValueError(f"final replay accepts OOS_H only; got {block}")
    return {
        "block": EXPECTED_BLOCK,
        "session_date": str(get_first(row, ("session_date", "date"))),
        "direction": str(get_first(row, ("direction",))).upper(),
        "instrument_key": str(get_first(row, ("instrument_key", "option_instrument_key"))),
        "entry_timestamp": str(get_first(row, ("entry_timestamp", "entry_time", "entry_at"))),
        "entry_price": finite(
            get_first(row, ("entry_price", "entry_open", "entry_premium")),
            "entry_price",
        ),
        "option_side": str(get_first(row, ("option_side", "side"), required=False) or ""),
        "strike": get_first(row, ("strike", "atm_strike"), required=False),
    }


def simulate_frozen_exit(
    *,
    trade: dict[str, Any],
    candles: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    entry = float(trade["entry_price"])
    entry_dt = parse_dt(trade["entry_timestamp"]).replace(second=0, microsecond=0)
    path = [
        candle
        for candle in candles
        if candle["_dt"].replace(second=0, microsecond=0) >= entry_dt
    ][: int(FROZEN_EXIT["max_hold_minutes"])]

    if len(path) < int(FROZEN_EXIT["max_hold_minutes"]):
        raise ValueError(
            f"incomplete 15m path for {trade['session_date']} {trade['instrument_key']} "
            f"at {trade['entry_timestamp']}: only {len(path)} candles"
        )

    # Exact next-minute OPEN integrity: economics entry must equal first replay bar OPEN.
    first_open = float(path[0]["open"])
    if not math.isclose(entry, first_open, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            f"entry mismatch: economics={entry} ohlc_open={first_open} "
            f"{trade['session_date']} {trade['instrument_key']}"
        )

    active_stop = entry * (1.0 - FROZEN_EXIT["initial_stop_pct"] / 100.0)
    pending_stop: float | None = None
    best_high = entry
    exit_price = None
    exit_reason = None
    exit_timestamp = None
    stop_history = []

    for i, candle in enumerate(path):
        if pending_stop is not None:
            active_stop = max(active_stop, pending_stop)
            pending_stop = None

        bar_open = float(candle["open"])
        bar_high = float(candle["high"])
        bar_low = float(candle["low"])
        bar_close = float(candle["close"])

        stop_history.append(
            {
                "timestamp": candle["timestamp"],
                "active_stop": active_stop,
            }
        )

        # Existing active stop is evaluated before any stop update from this bar.
        if bar_open <= active_stop:
            exit_price = bar_open
            exit_reason = "STOP_GAP"
            exit_timestamp = candle["timestamp"]
            break
        if bar_low <= active_stop:
            exit_price = active_stop
            exit_reason = "STOP_TOUCH"
            exit_timestamp = candle["timestamp"]
            break

        best_high = max(best_high, bar_high)
        best_return = pct_return(entry, best_high)
        next_stop = active_stop

        if best_return >= FROZEN_EXIT["breakeven_trigger_pct"]:
            next_stop = max(next_stop, entry)
        if best_return >= FROZEN_EXIT["trail_activation_pct"]:
            next_stop = max(
                next_stop,
                best_high * (1.0 - FROZEN_EXIT["trail_distance_pct"] / 100.0),
            )

        # Important: becomes active only on the next candle.
        if next_stop > active_stop:
            pending_stop = next_stop

        if i == int(FROZEN_EXIT["max_hold_minutes"]) - 1:
            exit_price = bar_close
            exit_reason = "TIME_EXIT"
            exit_timestamp = candle["timestamp"]
            break

    assert exit_price is not None and exit_reason is not None
    gross = pct_return(entry, exit_price)
    net = gross - ROUND_TRIP_COST_PCT_POINTS

    return {
        **trade,
        "policy_id": EXIT_POLICY_ID,
        "exit_timestamp": exit_timestamp,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_return_pct": gross,
        "net_return_pct": net,
        "best_high_before_exit": best_high,
        "stop_history": stop_history,
    }


def replay(
    *,
    contract: dict[str, Any],
    economics_payload: dict[str, Any],
    ohlc_path: Path,
) -> dict[str, Any]:
    mismatches = verify_contract_files(contract)
    if mismatches:
        raise ValueError("freeze contract file mismatch: " + "; ".join(mismatches))
    if contract.get("status") != "FROZEN":
        raise ValueError("freeze contract is not FROZEN")
    if contract.get("exit_policy_id") != EXIT_POLICY_ID:
        raise ValueError("unexpected frozen exit policy")
    if contract.get("entry_rule") != ENTRY_RULE:
        raise ValueError("unexpected entry rule")
    if contract.get("contract_rule") != CONTRACT_RULE:
        raise ValueError("unexpected contract rule")
    if contract.get("exit_parameters") != FROZEN_EXIT:
        raise ValueError("frozen exit parameters changed")

    if economics_payload.get("entry_rule") not in (None, ENTRY_RULE):
        raise ValueError("economics entry rule mismatch")
    if economics_payload.get("contract_rule") not in (None, CONTRACT_RULE):
        raise ValueError("economics contract rule mismatch")

    raw_rows = economics_rows(economics_payload)
    trades = [normalize_trade(row) for row in raw_rows]
    ohlc = load_ohlc(ohlc_path)

    realized = []
    for trade in sorted(trades, key=lambda x: parse_dt(x["entry_timestamp"])):
        key = (trade["session_date"], trade["instrument_key"])
        candles = ohlc.get(key)
        if not candles:
            raise ValueError(f"missing OHLC for {key}")
        realized.append(simulate_frozen_exit(trade=trade, candles=candles))

    direction_summary = {}
    for direction in ("BEARISH", "BULLISH"):
        direction_summary[direction] = summarize(
            [row for row in realized if row["direction"] == direction]
        )

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "block": EXPECTED_BLOCK,
        "entry_rule": ENTRY_RULE,
        "contract_rule": CONTRACT_RULE,
        "frozen_policy_id": EXIT_POLICY_ID,
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "frozen_exit_parameters": dict(FROZEN_EXIT),
        "summary": summarize(realized),
        "direction_summaries": direction_summary,
        "rows": realized,
        "integrity": {
            "single_frozen_policy_only": True,
            "alternative_exit_search_performed": False,
            "entry_open_reconciled_to_ohlc": True,
            "complete_15m_path_required": True,
            "exact_contract_only": True,
            "oos_h_only": True,
        },
        "governance": {
            "result_may_not_be_used_to_retune_oos_h": True,
            "oos_h_may_not_be_reused_as_fresh_holdout": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-contract", required=True)
    parser.add_argument("--economics", required=True)
    parser.add_argument("--ohlc", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    contract = load_json(Path(args.freeze_contract))
    economics = load_json(Path(args.economics))
    result = replay(
        contract=contract,
        economics_payload=economics,
        ohlc_path=Path(args.ohlc),
    )
    result["output"] = args.output
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
