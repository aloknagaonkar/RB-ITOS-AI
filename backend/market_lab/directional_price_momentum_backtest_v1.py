"""Raw option-path backtest for Directional Price-Momentum Strategy V1.

This module evaluates the already-generated, price-primary V1 signals without
changing or filtering the signal definition.

Research rules
--------------
* Signal source is frozen `directional_price_momentum_v1` output.
* Exact instrument_key selected at the signal minute is preserved.
* Entry is the next exact 1-minute candle OPEN for that instrument.
* No later ATM substitution.
* Long-option returns are measured at +1/+3/+5/+10/+15 minutes.
* 15-minute MFE/MAE use exact intraminute option HIGH/LOW.
* Target/stop matrices are descriptive only; no policy is selected here.
* PCR does not participate in eligibility or backtest logic.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence


BACKTEST_VERSION = "DIRECTIONAL_PRICE_MOMENTUM_OPTION_BACKTEST_V1"
STRATEGY_ID = "DIRECTIONAL_PRICE_MOMENTUM_OPTION_BUYING_V1"
SIGNAL_ENGINE_VERSION = "PRICE_MOMENTUM_SIGNAL_ENGINE_V1"

IST = timezone(timedelta(hours=5, minutes=30))

ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}

HORIZONS = (1, 3, 5, 10, 15)
TARGETS = (5, 10, 15)
STOPS = (5, 10)


def normalize_block_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).replace(second=0, microsecond=0)


def f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_ohlc_block(value: str) -> tuple[str, Path]:
    parts = value.split("|")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--ohlc-block must be NAME|OHLC_CSV")
    name, path = parts
    name = normalize_block_name(name)
    if name in FORBIDDEN_BLOCKS:
        raise argparse.ArgumentTypeError(f"{name} is forbidden in V1 development backtest")
    if name not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"Unsupported block {name}; allowed={sorted(ALLOWED_BLOCKS)}"
        )
    return name, Path(path)


def pct_return(entry: float, exit_value: float) -> float:
    if entry <= 0:
        raise ValueError("entry premium must be positive")
    return ((exit_value / entry) - 1.0) * 100.0


def target_stop_classification(
    *,
    entry: float,
    candles: Sequence[dict[str, float]],
    target_pct: float,
    stop_pct: float,
) -> str:
    """Classify first target/stop touch using minute OHLC.

    If both levels are touched within the same earliest candle, intrabar order is
    unknowable and the result is AMBIGUOUS_SAME_BAR.
    """
    target_price = entry * (1.0 + target_pct / 100.0)
    stop_price = entry * (1.0 - stop_pct / 100.0)

    for candle in candles:
        target_hit = candle["high"] >= target_price
        stop_hit = candle["low"] <= stop_price

        if target_hit and stop_hit:
            return "AMBIGUOUS_SAME_BAR"
        if target_hit:
            return "TARGET_FIRST"
        if stop_hit:
            return "STOP_FIRST"

    return "NEITHER_WITHIN_15M"


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    if losses == 0:
        return None
    return gains / losses


def validate_signal_payload(payload: dict[str, Any]) -> None:
    if payload.get("status") != "AVAILABLE":
        raise ValueError("signal payload status is not AVAILABLE")
    if payload.get("strategy_id") != STRATEGY_ID:
        raise ValueError("unexpected strategy_id")
    if payload.get("signal_engine_version") != SIGNAL_ENGINE_VERSION:
        raise ValueError("unexpected signal_engine_version")

    guard = payload.get("leakage_guard") or {}
    expected = {
        "price_primary_signal": True,
        "pcr_used_for_signal": False,
        "future_return_features_used": False,
        "forward_change_columns_used": False,
        "oos_e_f_g_h_used": False,
        "oos_h_used": False,
    }
    for key, value in expected.items():
        if guard.get(key) != value:
            raise ValueError(
                f"signal leakage guard {key} expected {value!r}, got {guard.get(key)!r}"
            )

    blocks = {normalize_block_name(x) for x in payload.get("development_blocks", [])}
    if blocks != ALLOWED_BLOCKS:
        raise ValueError(
            f"development blocks must be exactly {sorted(ALLOWED_BLOCKS)}, got {sorted(blocks)}"
        )


def validate_ohlc_rows(rows: Sequence[dict[str, str]], path: Path) -> None:
    if not rows:
        raise ValueError(f"{path} has no OHLC rows")
    required = {
        "session_date",
        "instrument_key",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"{path} missing OHLC columns {sorted(missing)}")


def build_ohlc_index(
    block_rows: dict[str, list[dict[str, str]]],
) -> dict[tuple[str, str, str, datetime], dict[str, float]]:
    index: dict[tuple[str, str, str, datetime], dict[str, float]] = {}

    for block, rows in block_rows.items():
        for row in rows:
            open_ = f(row.get("open"))
            high = f(row.get("high"))
            low = f(row.get("low"))
            close = f(row.get("close"))
            if None in (open_, high, low, close):
                continue

            key = (
                block,
                row["session_date"],
                row["instrument_key"],
                parse_dt(row["timestamp"]),
            )
            if key in index:
                raise ValueError(f"duplicate OHLC row {key}")

            index[key] = {
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
            }

    return index


def evaluate_signal(
    signal: dict[str, Any],
    ohlc_index: dict[tuple[str, str, str, datetime], dict[str, float]],
) -> dict[str, Any]:
    block = normalize_block_name(str(signal["block"]))
    session_date = str(signal["session_date"])
    instrument_key = (signal.get("instrument_key") or "").strip()
    signal_ts = parse_dt(str(signal["timestamp"]))
    entry_ts = signal_ts + timedelta(minutes=1)

    result: dict[str, Any] = {
        "block": block,
        "session_date": session_date,
        "signal_timestamp": signal_ts.isoformat(),
        "entry_timestamp": entry_ts.isoformat(),
        "direction": signal["direction"],
        "option_side": signal["option_side"],
        "instrument_key": instrument_key or None,
        "moving_atm": signal.get("moving_atm"),
        "strike": signal.get("strike"),
        "signal_spot": signal.get("spot"),
        "option_selection_status": signal.get("option_selection_status"),
        "entry_rule": "NEXT_EXACT_MINUTE_OPEN",
        "contract_selection_rule": "EXACT_SIGNAL_TIME_MOVING_ATM_NO_SUBSTITUTION",
        "entry_status": "UNAVAILABLE",
        "path_status": "UNAVAILABLE",
        "entry_premium": None,
        "returns_pct": {f"{h}m": None for h in HORIZONS},
        "mfe_pct_15m": None,
        "mae_pct_15m": None,
        "target_stop": {},
    }

    if (
        signal.get("option_selection_status") != "AVAILABLE_EXACT_MOVING_ATM"
        or not instrument_key
    ):
        result["entry_status"] = "UNAVAILABLE_SIGNAL_OPTION"
        return result

    entry_key = (block, session_date, instrument_key, entry_ts)
    entry_candle = ohlc_index.get(entry_key)
    if entry_candle is None:
        result["entry_status"] = "UNAVAILABLE_NEXT_MINUTE_OPEN"
        return result

    entry = entry_candle["open"]
    if entry <= 0:
        result["entry_status"] = "UNAVAILABLE_INVALID_ENTRY_PREMIUM"
        return result

    result["entry_status"] = "AVAILABLE"
    result["entry_premium"] = entry

    path: list[dict[str, float]] = []
    for offset in range(15):
        ts = entry_ts + timedelta(minutes=offset)
        candle = ohlc_index.get((block, session_date, instrument_key, ts))
        if candle is None:
            result["path_status"] = "UNAVAILABLE_INCOMPLETE_15M_PATH"
            return result
        path.append(candle)

    result["path_status"] = "AVAILABLE_COMPLETE_15M_PATH"

    for horizon in HORIZONS:
        close = path[horizon - 1]["close"]
        result["returns_pct"][f"{horizon}m"] = pct_return(entry, close)

    max_high = max(c["high"] for c in path)
    min_low = min(c["low"] for c in path)
    result["mfe_pct_15m"] = pct_return(entry, max_high)
    result["mae_pct_15m"] = pct_return(entry, min_low)

    for target in TARGETS:
        for stop in STOPS:
            key = f"TARGET_{target}_STOP_{stop}"
            result["target_stop"][key] = target_stop_classification(
                entry=entry,
                candles=path,
                target_pct=float(target),
                stop_pct=float(stop),
            )

    return result


def metric_summary(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    complete = [
        t for t in trades if t.get("path_status") == "AVAILABLE_COMPLETE_15M_PATH"
    ]

    result: dict[str, Any] = {
        "candidate_count": len(trades),
        "entry_available_count": sum(t.get("entry_status") == "AVAILABLE" for t in trades),
        "complete_15m_path_count": len(complete),
        "return_metrics": {},
        "intrabar_excursion_15m": {
            "available_count": len(complete),
            "median_mfe_pct": (
                statistics.median(t["mfe_pct_15m"] for t in complete)
                if complete
                else None
            ),
            "median_mae_pct": (
                statistics.median(t["mae_pct_15m"] for t in complete)
                if complete
                else None
            ),
        },
        "target_stop_matrix": {},
    }

    for horizon in HORIZONS:
        key = f"{horizon}m"
        values = [
            float(t["returns_pct"][key])
            for t in complete
            if t["returns_pct"].get(key) is not None
        ]
        result["return_metrics"][f"return_{horizon}m"] = {
            "available_count": len(values),
            "positive_count": sum(v > 0 for v in values),
            "positive_pct": (100 * sum(v > 0 for v in values) / len(values))
            if values
            else None,
            "mean_pct": statistics.fmean(values) if values else None,
            "median_pct": statistics.median(values) if values else None,
            "profit_factor_close_return": profit_factor(values),
        }

    for target in TARGETS:
        for stop in STOPS:
            name = f"TARGET_{target}_STOP_{stop}"
            labels = [t["target_stop"].get(name) for t in complete]
            decisive = sum(
                label in {"TARGET_FIRST", "STOP_FIRST"} for label in labels
            )
            target_first = sum(label == "TARGET_FIRST" for label in labels)
            result["target_stop_matrix"][name] = {
                "available_count": len(labels),
                "target_first": target_first,
                "stop_first": sum(label == "STOP_FIRST" for label in labels),
                "ambiguous_same_bar": sum(
                    label == "AMBIGUOUS_SAME_BAR" for label in labels
                ),
                "neither_within_15m": sum(
                    label == "NEITHER_WITHIN_15M" for label in labels
                ),
                "target_first_pct_of_decisive": (
                    100 * target_first / decisive if decisive else None
                ),
            }

    return result


def grouped_summary(
    trades: Sequence[dict[str, Any]],
    key_name: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade[key_name])].append(trade)
    return {
        key: metric_summary(group)
        for key, group in sorted(groups.items())
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Raw exact-instrument option backtest for price-momentum V1"
    )
    parser.add_argument("--signals", required=True, help="V1 signal JSON")
    parser.add_argument(
        "--ohlc-block",
        action="append",
        required=True,
        type=parse_ohlc_block,
        help="NAME|OHLC_CSV",
    )
    parser.add_argument("--output", required=True, help="Backtest JSON output")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    signals_payload = load_json(Path(args.signals))
    validate_signal_payload(signals_payload)

    block_paths: list[tuple[str, Path]] = args.ohlc_block
    names = [name for name, _ in block_paths]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate OHLC blocks: {names}")
    if set(names) != ALLOWED_BLOCKS:
        raise ValueError(
            f"OHLC inputs must be exactly {sorted(ALLOWED_BLOCKS)}, got {sorted(names)}"
        )

    block_rows: dict[str, list[dict[str, str]]] = {}
    for name, path in block_paths:
        rows = load_csv(path)
        validate_ohlc_rows(rows, path)
        block_rows[name] = rows

    index = build_ohlc_index(block_rows)

    signals = signals_payload.get("signals") or []
    trades = [evaluate_signal(signal, index) for signal in signals]

    payload = {
        "status": "AVAILABLE",
        "strategy_id": STRATEGY_ID,
        "signal_engine_version": SIGNAL_ENGINE_VERSION,
        "backtest_version": BACKTEST_VERSION,
        "research_status": "DEVELOPMENT_RAW_OPTION_PATH_BACKTEST",
        "entry_rule": "NEXT_EXACT_MINUTE_OPEN",
        "contract_selection_rule": "EXACT_SIGNAL_TIME_MOVING_ATM_NO_SUBSTITUTION",
        "leakage_guard": {
            "signals_recomputed_or_retuned": False,
            "pcr_used_for_trade_eligibility": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "future_information_used_for_entry": False,
        },
        "limitations": [
            "Target/stop matrices are descriptive; no exit policy is frozen here.",
            "No brokerage/slippage/cost model is applied in this raw path study.",
            "Signals can overlap; this is candidate-level research, not a portfolio simulation.",
        ],
        "summary": metric_summary(trades),
        "by_direction": grouped_summary(trades, "direction"),
        "by_block": grouped_summary(trades, "block"),
        "trades": trades,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": payload["status"],
                "strategy_id": payload["strategy_id"],
                "backtest_version": BACKTEST_VERSION,
                "candidate_count": payload["summary"]["candidate_count"],
                "entry_available_count": payload["summary"]["entry_available_count"],
                "complete_15m_path_count": payload["summary"]["complete_15m_path_count"],
                "by_direction_candidate_count": {
                    key: value["candidate_count"]
                    for key, value in payload["by_direction"].items()
                },
                "by_block_candidate_count": {
                    key: value["candidate_count"]
                    for key, value in payload["by_block"].items()
                },
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
