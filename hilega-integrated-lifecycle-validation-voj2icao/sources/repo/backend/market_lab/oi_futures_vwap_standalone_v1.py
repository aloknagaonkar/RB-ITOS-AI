from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "OI_FUTURES_VWAP_STANDALONE_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
HORIZONS = (1, 3, 5, 10, 15)
ROUND_TRIP_COST_PCT_POINTS = 0.5

BULLISH_CE_STATE = "LONG_BUILDUP"
BULLISH_PE_STATE = "SHORT_BUILDUP"
BEARISH_CE_STATE = "SHORT_BUILDUP"
BEARISH_PE_STATE = "LONG_BUILDUP"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def parse_block_path(value: str) -> tuple[str, Path]:
    if "|" not in value:
        raise argparse.ArgumentTypeError("expected BLOCK|PATH")
    block, raw_path = value.split("|", 1)
    block = block.strip()
    if block not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"forbidden/unknown block {block!r}; allowed={sorted(ALLOWED_BLOCKS)}"
        )
    return block, Path(raw_path)


def metric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "positive_count": 0,
            "win_rate_pct": None,
            "mean_pct": None,
            "median_pct": None,
            "sum_pct_points": None,
            "profit_factor": None,
            "average_winner_pct": None,
            "average_loser_pct": None,
            "best_pct": None,
            "worst_pct": None,
        }

    wins = [x for x in values if x > 0]
    losses = [x for x in values if x <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "count": len(values),
        "positive_count": len(wins),
        "win_rate_pct": 100.0 * len(wins) / len(values),
        "mean_pct": mean(values),
        "median_pct": median(values),
        "sum_pct_points": sum(values),
        "profit_factor": (
            gross_profit / gross_loss if gross_loss > 0 else None
        ),
        "average_winner_pct": mean(wins) if wins else None,
        "average_loser_pct": mean(losses) if losses else None,
        "best_pct": max(values),
        "worst_pct": min(values),
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_futures_vwap(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = read_csv(path)
    required = {
        "session_date", "timestamp", "close", "session_vwap",
        "instrument_key", "expiry",
    }
    headers = set(rows[0].keys()) if rows else set()
    missing = required - headers
    if missing:
        raise ValueError(f"futures VWAP missing columns: {sorted(missing)}")

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["session_date"], row["timestamp"])
        if key in out:
            raise ValueError(f"duplicate futures VWAP row: {key}")
        out[key] = {
            "close": float(row["close"]),
            "vwap": float(row["session_vwap"]),
            "instrument_key": row["instrument_key"],
            "expiry": row["expiry"],
            "contract_source": row.get("contract_source"),
        }
    return out


def detect_positioning_schema(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        raise ValueError("empty positioning CSV")

    fields = set(rows[0].keys())
    required = {
        "session_date", "timestamp", "strike_offset",
        "ce_instrument_key", "pe_instrument_key",
    }
    missing = required - fields
    if missing:
        raise ValueError(
            f"positioning CSV missing required exact-ATM fields: {sorted(missing)}"
        )

    state_pairs = (
        ("ce_5m_state", "pe_5m_state"),
        ("ce_state", "pe_state"),
        ("ce_positioning_state", "pe_positioning_state"),
        ("ce_build_up", "pe_build_up"),
        ("ce_buildup", "pe_buildup"),
    )
    for ce_state, pe_state in state_pairs:
        if ce_state in fields and pe_state in fields:
            return {
                "ce_state": ce_state,
                "pe_state": pe_state,
            }

    raise ValueError(
        "positioning CSV does not expose a supported CE/PE state pair; "
        f"available fields={sorted(fields)}"
    )


def load_positioning(
    specs: list[tuple[str, Path]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    schema_by_block: dict[str, Any] = {}

    for block, path in specs:
        rows = read_csv(path)
        schema = detect_positioning_schema(rows)
        schema_by_block[block] = schema

        # Exact moving ATM only. No nearest strike fallback.
        for row in rows:
            if str(row.get("strike_offset") or "").strip() not in {"0", "0.0"}:
                continue

            session_date = str(row.get("session_date") or "")
            timestamp = str(row.get("timestamp") or "")
            ce_key = str(row.get("ce_instrument_key") or "").strip()
            pe_key = str(row.get("pe_instrument_key") or "").strip()
            ce_state = str(row.get(schema["ce_state"]) or "").upper().strip()
            pe_state = str(row.get(schema["pe_state"]) or "").upper().strip()

            if not session_date or not timestamp:
                continue

            rows_out.append({
                "block": block,
                "session_date": session_date,
                "timestamp": timestamp,
                "ce_state": ce_state,
                "pe_state": pe_state,
                "ce_instrument_key": ce_key or None,
                "pe_instrument_key": pe_key or None,
                "moving_atm": _float(row.get("moving_atm")),
                "strike": _float(row.get("strike")),
                "spot": _float(row.get("spot")),
            })

    rows_out.sort(
        key=lambda x: (x["block"], x["session_date"], _dt(x["timestamp"]))
    )
    return rows_out, schema_by_block


def load_option_ohlc(
    specs: list[tuple[str, Path]],
) -> dict[tuple[str, str, str, str], dict[str, float]]:
    idx: dict[tuple[str, str, str, str], dict[str, float]] = {}

    for block, path in specs:
        rows = read_csv(path)
        if not rows:
            continue
        required = {
            "session_date", "instrument_key", "timestamp",
            "open", "high", "low", "close",
        }
        missing = required - set(rows[0].keys())
        if missing:
            raise ValueError(
                f"{block} option OHLC missing columns: {sorted(missing)}"
            )

        for row in rows:
            key = (
                block,
                str(row["session_date"]),
                str(row["instrument_key"]),
                str(row["timestamp"]),
            )
            if key in idx:
                raise ValueError(f"duplicate option OHLC row: {key}")
            idx[key] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }

    return idx


def raw_oi_direction(ce_state: str, pe_state: str) -> str | None:
    if ce_state == BULLISH_CE_STATE and pe_state == BULLISH_PE_STATE:
        return "BULLISH"
    if ce_state == BEARISH_CE_STATE and pe_state == BEARISH_PE_STATE:
        return "BEARISH"
    return None


def confluence_direction(
    ce_state: str,
    pe_state: str,
    futures_close: float,
    futures_vwap: float,
) -> str | None:
    oi_direction = raw_oi_direction(ce_state, pe_state)

    if oi_direction == "BULLISH" and futures_close > futures_vwap:
        return "BULLISH"

    if oi_direction == "BEARISH" and futures_close < futures_vwap:
        return "BEARISH"

    return None


def generate_transition_signals(
    positioning_rows: list[dict[str, Any]],
    futures_idx: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter]:
    """
    Emit only on transition into confluence.

    Persistent same-direction confluence does not generate repeated signals.
    Condition break resets the state. A direct BULLISH<->BEARISH flip is a
    new transition and therefore a new signal.
    """
    signals: list[dict[str, Any]] = []
    issues: Counter = Counter()

    by_session: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in positioning_rows:
        by_session[(row["block"], row["session_date"])].append(row)

    for (block, session_date), rows in sorted(by_session.items()):
        rows.sort(key=lambda x: _dt(x["timestamp"]))
        previous_confluence: str | None = None

        for row in rows:
            fut = futures_idx.get((session_date, row["timestamp"]))
            if fut is None:
                issues["MISSING_FUTURES_VWAP_AT_POSITIONING_TIMESTAMP"] += 1
                previous_confluence = None
                continue

            direction = confluence_direction(
                row["ce_state"],
                row["pe_state"],
                fut["close"],
                fut["vwap"],
            )

            if direction is not None and direction != previous_confluence:
                option_side = "CE" if direction == "BULLISH" else "PE"
                instrument_key = (
                    row["ce_instrument_key"]
                    if option_side == "CE"
                    else row["pe_instrument_key"]
                )
                if not instrument_key:
                    issues["MISSING_EXACT_ATM_INSTRUMENT"] += 1
                else:
                    signals.append({
                        "block": block,
                        "session_date": session_date,
                        "signal_timestamp": row["timestamp"],
                        "direction": direction,
                        "option_side": option_side,
                        "instrument_key": instrument_key,
                        "moving_atm": row["moving_atm"],
                        "strike": row["strike"],
                        "spot": row["spot"],
                        "ce_state": row["ce_state"],
                        "pe_state": row["pe_state"],
                        "futures_close": fut["close"],
                        "futures_vwap": fut["vwap"],
                        "futures_vwap_distance_points": (
                            fut["close"] - fut["vwap"]
                        ),
                        "futures_instrument_key": fut["instrument_key"],
                        "futures_expiry": fut["expiry"],
                        "futures_contract_source": fut["contract_source"],
                    })

            previous_confluence = direction

    return signals, issues


def attach_option_economics(
    signals: list[dict[str, Any]],
    ohlc_idx: dict[tuple[str, str, str, str], dict[str, float]],
) -> tuple[list[dict[str, Any]], Counter]:
    trades: list[dict[str, Any]] = []
    issues: Counter = Counter()

    for signal in signals:
        signal_ts = _dt(signal["signal_timestamp"])
        entry_ts = signal_ts + timedelta(minutes=1)

        base_key = (
            signal["block"],
            signal["session_date"],
            signal["instrument_key"],
        )

        entry = ohlc_idx.get((*base_key, entry_ts.isoformat()))
        if entry is None:
            issues["EXACT_NEXT_MINUTE_OPEN_UNAVAILABLE"] += 1
            trades.append({
                **signal,
                "entry_available": False,
                "complete_15m_path": False,
                "issue": "EXACT_NEXT_MINUTE_OPEN_UNAVAILABLE",
                "entry_timestamp": entry_ts.isoformat(),
            })
            continue

        entry_price = entry["open"]
        if entry_price <= 0:
            issues["INVALID_ENTRY_OPEN"] += 1
            continue

        gross_returns: dict[str, float] = {}
        net_returns: dict[str, float] = {}
        complete = True

        for horizon in HORIZONS:
            ts = entry_ts + timedelta(minutes=horizon)
            candle = ohlc_idx.get((*base_key, ts.isoformat()))
            if candle is None:
                complete = False
                issues[f"MISSING_{horizon}M_CLOSE"] += 1
                continue

            gross = 100.0 * (candle["close"] - entry_price) / entry_price
            gross_returns[f"{horizon}m"] = gross
            net_returns[f"{horizon}m"] = (
                gross - ROUND_TRIP_COST_PCT_POINTS
            )

        path = []
        for minute in range(0, 16):
            ts = entry_ts + timedelta(minutes=minute)
            candle = ohlc_idx.get((*base_key, ts.isoformat()))
            if candle is None:
                complete = False
                continue
            path.append(candle)

        mfe = None
        mae = None
        if path:
            mfe = 100.0 * (
                max(x["high"] for x in path) - entry_price
            ) / entry_price
            mae = 100.0 * (
                min(x["low"] for x in path) - entry_price
            ) / entry_price

        trades.append({
            **signal,
            "entry_available": True,
            "complete_15m_path": complete,
            "issue": None if complete else "INCOMPLETE_15M_PATH",
            "entry_timestamp": entry_ts.isoformat(),
            "entry_price": entry_price,
            "gross_returns_pct": gross_returns,
            "net_returns_pct": net_returns,
            "mfe_pct_15m": mfe,
            "mae_pct_15m": mae,
        })

    return trades, issues


def trade_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        r for r in rows
        if r.get("entry_available") and r.get("complete_15m_path")
    ]

    out: dict[str, Any] = {
        "trade_count": len(valid),
        "direction_counts": dict(Counter(r["direction"] for r in valid)),
    }

    for horizon in HORIZONS:
        key = f"{horizon}m"
        values = [
            float(r["net_returns_pct"][key])
            for r in valid
            if key in (r.get("net_returns_pct") or {})
        ]
        out[f"net_{key}"] = metric_summary(values)

    mfe = [float(r["mfe_pct_15m"]) for r in valid if r.get("mfe_pct_15m") is not None]
    mae = [float(r["mae_pct_15m"]) for r in valid if r.get("mae_pct_15m") is not None]

    out["mfe_15m"] = {
        "count": len(mfe),
        "mean_pct": mean(mfe) if mfe else None,
        "median_pct": median(mfe) if mfe else None,
    }
    out["mae_15m"] = {
        "count": len(mae),
        "mean_pct": mean(mae) if mae else None,
        "median_pct": median(mae) if mae else None,
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--positioning",
        action="append",
        type=parse_block_path,
        required=True,
        help="repeat BLOCK|PATH for TRAIN/OOS_A/OOS_B/OOS_C/OOS_D",
    )
    ap.add_argument(
        "--option-ohlc",
        action="append",
        type=parse_block_path,
        required=True,
        help="repeat BLOCK|PATH for TRAIN/OOS_A/OOS_B/OOS_C/OOS_D",
    )
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    positioning_rows, positioning_schema = load_positioning(args.positioning)
    futures_idx = load_futures_vwap(Path(args.futures_vwap))
    option_ohlc_idx = load_option_ohlc(args.option_ohlc)

    signals, signal_issues = generate_transition_signals(
        positioning_rows,
        futures_idx,
    )
    trades, econ_issues = attach_option_economics(
        signals,
        option_ohlc_idx,
    )

    valid_trades = [
        r for r in trades
        if r.get("entry_available") and r.get("complete_15m_path")
    ]

    by_block = {
        block: trade_summary(
            [r for r in valid_trades if r["block"] == block]
        )
        for block in sorted(ALLOWED_BLOCKS)
    }
    by_direction = {
        direction: trade_summary(
            [r for r in valid_trades if r["direction"] == direction]
        )
        for direction in ("BULLISH", "BEARISH")
    }

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "strategy_definition": {
            "price_structure_used": False,
            "t1_used": False,
            "t3_used": False,
            "bullish_oi": (
                "CE LONG_BUILDUP + PE SHORT_BUILDUP"
            ),
            "bearish_oi": (
                "CE SHORT_BUILDUP + PE LONG_BUILDUP"
            ),
            "bullish_vwap": "NIFTY FUT close > prospective session VWAP",
            "bearish_vwap": "NIFTY FUT close < prospective session VWAP",
            "signal_emission": (
                "first minute entering confluence; persistent same-direction "
                "confluence emits no duplicate signal; break resets"
            ),
            "contract": (
                "exact moving ATM CE/PE from strike_offset == 0 at signal timestamp"
            ),
            "entry": "exact next-minute option OPEN",
            "nearest_strike_fallback": False,
            "nearest_time_fallback": False,
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
            "vwap_distance_threshold": None,
            "vwap_slope_used": False,
            "extra_indicators_used": False,
        },
        "source_schema": {
            "positioning_schema_by_block": positioning_schema,
            "positioning_exact_atm_selector": "strike_offset == 0",
        },
        "summary": {
            "exact_atm_positioning_row_count": len(positioning_rows),
            "transition_signal_count": len(signals),
            "trade_record_count": len(trades),
            "complete_trade_count": len(valid_trades),
            "signal_issue_counts": dict(signal_issues),
            "economics_issue_counts": dict(econ_issues),
            "overall": trade_summary(valid_trades),
        },
        "block_summaries": by_block,
        "direction_summaries": by_direction,
        "sep7_signals": [
            r for r in trades if r["session_date"] == "2026-09-07"
        ],
        "trades": trades,
        "governance": {
            "research_only": True,
            "standalone_strategy": True,
            "midpoint_v1_modified": False,
            "allowed_blocks": sorted(ALLOWED_BLOCKS),
            "oos_e_f_g_h_used": False,
            "threshold_search_performed": False,
            "fresh_oos_required_before_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
