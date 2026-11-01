from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_NEW_ARM_EXACT_OPTION_ECONOMICS_V1"
EXPECTED_STRUCTURAL_VERSION = "MIDPOINT_V2_STRUCTURAL_RECONSTRUCTION_V1"
ALLOWED_ARMS = {"BASE_THEN_GO", "FAILED_BREAK_RECLAIM"}
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
ROUND_TRIP_COST_PCT_POINTS = 0.5
HORIZONS = (1, 3, 5, 10, 15)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_block_path(value: str) -> tuple[str, Path]:
    if "|" not in value:
        raise ValueError("expected BLOCK|path")
    block, path = value.split("|", 1)
    block = block.strip()
    p = Path(path.strip())
    if block not in ALLOWED_BLOCKS:
        raise ValueError(f"unsupported block {block!r}")
    return block, p


def first_existing(headers: list[str], candidates: tuple[str, ...]) -> str:
    lower = {h.lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    raise ValueError(
        f"none of columns {candidates!r} found; available={headers!r}"
    )


def optional_existing(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    lower = {h.lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v


def load_positioning(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Index exact positioning snapshot by (session_date, timestamp).

    Required semantics:
    - moving ATM strike at timestamp
    - exact CE/PE instrument keys at same timestamp
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        ts_col = first_existing(
            headers, ("timestamp", "datetime", "time", "ts", "snapshot_timestamp")
        )
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        atm_col = first_existing(
            headers, ("moving_atm", "atm_strike", "atm", "strike")
        )
        ce_key_col = first_existing(
            headers, ("ce_instrument_key", "call_instrument_key", "ce_key")
        )
        pe_key_col = first_existing(
            headers, ("pe_instrument_key", "put_instrument_key", "pe_key")
        )

        for row in reader:
            raw_ts = row.get(ts_col)
            if not raw_ts:
                continue
            try:
                ts = parse_dt(str(raw_ts))
            except ValueError:
                continue
            session_date = (
                str(row.get(date_col))
                if date_col and row.get(date_col)
                else ts.date().isoformat()
            )
            atm = finite_float(row.get(atm_col))
            if atm is None:
                continue
            out[(session_date, ts.isoformat())] = {
                "session_date": session_date,
                "timestamp": ts.isoformat(),
                "moving_atm": atm,
                "ce_instrument_key": row.get(ce_key_col),
                "pe_instrument_key": row.get(pe_key_col),
            }
    return out


def load_ohlc(path: Path) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """
    Index by (session_date, instrument_key) -> timestamp -> candle.
    """
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        ts_col = first_existing(
            headers, ("timestamp", "datetime", "time", "ts", "candle_timestamp")
        )
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        key_col = first_existing(
            headers, ("instrument_key", "instrument", "instrument_token", "key")
        )
        open_col = first_existing(headers, ("open", "open_price", "o"))
        high_col = first_existing(headers, ("high", "high_price", "h"))
        low_col = first_existing(headers, ("low", "low_price", "l"))
        close_col = first_existing(headers, ("close", "close_price", "c"))

        for row in reader:
            raw_ts = row.get(ts_col)
            key = row.get(key_col)
            if not raw_ts or not key:
                continue
            try:
                ts = parse_dt(str(raw_ts))
            except ValueError:
                continue
            session_date = (
                str(row.get(date_col))
                if date_col and row.get(date_col)
                else ts.date().isoformat()
            )
            candle = {
                "timestamp": ts.isoformat(),
                "open": finite_float(row.get(open_col)),
                "high": finite_float(row.get(high_col)),
                "low": finite_float(row.get(low_col)),
                "close": finite_float(row.get(close_col)),
            }
            out[(session_date, str(key))][ts.isoformat()] = candle
    return dict(out)


def pct_return(entry: float, price: float | None) -> float | None:
    if price is None:
        return None
    return (price / entry - 1.0) * 100.0


def option_side(direction: str) -> str:
    if direction == "BULLISH":
        return "CE"
    if direction == "BEARISH":
        return "PE"
    raise ValueError(f"unsupported direction {direction!r}")


def exact_atm_contract(
    positioning: dict[tuple[str, str], dict[str, Any]],
    session_date: str,
    confirmation_ts: datetime,
    side: str,
) -> dict[str, Any] | None:
    snap = positioning.get((session_date, confirmation_ts.isoformat()))
    if not snap:
        return None
    key_field = "ce_instrument_key" if side == "CE" else "pe_instrument_key"
    instrument_key = snap.get(key_field)
    if not instrument_key:
        return None
    return {
        "strike": snap["moving_atm"],
        "instrument_key": str(instrument_key),
        "positioning_timestamp": snap["timestamp"],
    }


def build_trade(
    structural_row: dict[str, Any],
    positioning: dict[tuple[str, str], dict[str, Any]],
    ohlc: dict[tuple[str, str], dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    result = structural_row["v2_result"]
    arm = str(result.get("entry_arm"))
    direction = str(result.get("entry_direction"))
    session_date = str(structural_row["session_date"])
    confirmation_raw = structural_row.get("confirmation_timestamp")

    base = {
        "block": structural_row["block"],
        "session_date": session_date,
        "setup_type": structural_row.get("setup_type"),
        "entry_arm": arm,
        "original_direction": structural_row.get("direction"),
        "entry_direction": direction,
        "option_side": option_side(direction),
        "t3_timestamp": structural_row.get("t3_timestamp"),
        "absolute_confirmation_bar_index": structural_row.get(
            "absolute_confirmation_bar_index"
        ),
        "confirmation_timestamp": confirmation_raw,
        "instrument_available": False,
        "entry_available": False,
        "complete_15m_path": False,
        "issue": None,
    }

    if arm not in ALLOWED_ARMS:
        base["issue"] = "NOT_A_NEW_V2_ARM"
        return base
    if not confirmation_raw:
        base["issue"] = "MISSING_CONFIRMATION_TIMESTAMP"
        return base

    confirmation_ts = parse_dt(str(confirmation_raw))
    side = base["option_side"]
    contract = exact_atm_contract(positioning, session_date, confirmation_ts, side)
    base["instrument_available"] = contract is not None
    if contract is None:
        base["issue"] = "EXACT_ATM_CONTRACT_UNAVAILABLE_AT_CONFIRMATION"
        return base
    base.update(contract)

    series = ohlc.get((session_date, contract["instrument_key"]), {})
    entry_ts = confirmation_ts + timedelta(minutes=1)
    candle = series.get(entry_ts.isoformat())
    if candle is None or candle.get("open") is None:
        base["issue"] = "EXACT_NEXT_MINUTE_OPEN_UNAVAILABLE"
        return base

    entry = float(candle["open"])
    if entry <= 0:
        base["issue"] = "INVALID_ENTRY_OPEN"
        return base

    base["entry_available"] = True
    base["entry_timestamp"] = entry_ts.isoformat()
    base["entry_price"] = entry

    returns = {}
    for h in HORIZONS:
        c = series.get((entry_ts + timedelta(minutes=h)).isoformat())
        returns[f"{h}m"] = pct_return(entry, c.get("close") if c else None)

    path = []
    for i in range(15):
        c = series.get((entry_ts + timedelta(minutes=i)).isoformat())
        if c is None:
            break
        path.append(c)

    base["complete_15m_path"] = len(path) == 15
    if path:
        highs = [c["high"] for c in path if c.get("high") is not None]
        lows = [c["low"] for c in path if c.get("low") is not None]
        base["mfe_pct_15m"] = pct_return(entry, max(highs)) if highs else None
        base["mae_pct_15m"] = pct_return(entry, min(lows)) if lows else None
    else:
        base["mfe_pct_15m"] = None
        base["mae_pct_15m"] = None

    base["gross_returns_pct"] = returns
    base["net_returns_pct"] = {
        k: (v - ROUND_TRIP_COST_PCT_POINTS if v is not None else None)
        for k, v in returns.items()
    }
    return base


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r.get("entry_available")]
    out: dict[str, Any] = {
        "candidate_count": len(rows),
        "instrument_available_count": sum(bool(r.get("instrument_available")) for r in rows),
        "entry_available_count": len(valid),
        "complete_15m_path_count": sum(bool(r.get("complete_15m_path")) for r in rows),
        "issue_counts": dict(sorted(Counter(str(r.get("issue")) for r in rows if r.get("issue")).items())),
    }

    for h in HORIZONS:
        key = f"{h}m"
        vals = [
            r["net_returns_pct"][key]
            for r in valid
            if r.get("net_returns_pct", {}).get(key) is not None
        ]
        out[f"net_{key}"] = {
            "count": len(vals),
            "mean_pct": mean(vals) if vals else None,
            "median_pct": median(vals) if vals else None,
            "positive_count": sum(v > 0 for v in vals),
        }

    mfe = [r.get("mfe_pct_15m") for r in valid if r.get("mfe_pct_15m") is not None]
    mae = [r.get("mae_pct_15m") for r in valid if r.get("mae_pct_15m") is not None]
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
    ap.add_argument("--structural", required=True)
    ap.add_argument("--positioning", action="append", required=True)
    ap.add_argument("--ohlc", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    structural = load_json(Path(args.structural))
    if structural.get("research_version") != EXPECTED_STRUCTURAL_VERSION:
        raise SystemExit(
            f"Unexpected structural version={structural.get('research_version')!r}"
        )

    pos_specs = [parse_block_path(v) for v in args.positioning]
    ohlc_specs = [parse_block_path(v) for v in args.ohlc]
    if {b for b, _ in pos_specs} != ALLOWED_BLOCKS:
        raise SystemExit("Need positioning files for TRAIN + OOS_A/B/C/D exactly")
    if {b for b, _ in ohlc_specs} != ALLOWED_BLOCKS:
        raise SystemExit("Need option OHLC files for TRAIN + OOS_A/B/C/D exactly")

    positioning_by_block = {
        block: load_positioning(path) for block, path in pos_specs
    }
    ohlc_by_block = {
        block: load_ohlc(path) for block, path in ohlc_specs
    }

    candidates = [
        r for r in structural.get("rows") or []
        if (r.get("v2_result") or {}).get("entry_arm") in ALLOWED_ARMS
    ]
    if len(candidates) != 17:
        raise SystemExit(f"Expected 17 new-arm candidates, got {len(candidates)}")

    rows = []
    for r in candidates:
        block = str(r["block"])
        if block not in ALLOWED_BLOCKS:
            raise SystemExit(f"Forbidden/unexpected block in candidate: {block}")
        rows.append(
            build_trade(
                r,
                positioning_by_block[block],
                ohlc_by_block[block],
            )
        )

    arm_summaries = {}
    for arm in sorted(ALLOWED_ARMS):
        arm_summaries[arm] = summarize_rows(
            [r for r in rows if r["entry_arm"] == arm]
        )

    direction_summaries = {}
    for direction in ("BULLISH", "BEARISH"):
        direction_summaries[direction] = summarize_rows(
            [r for r in rows if r["entry_direction"] == direction]
        )

    block_summaries = {}
    for block in sorted(ALLOWED_BLOCKS):
        block_summaries[block] = summarize_rows(
            [r for r in rows if r["block"] == block]
        )

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_structural_version": EXPECTED_STRUCTURAL_VERSION,
        "candidate_scope": "NEW_V2_ARMS_ONLY",
        "entry_rule": "EXACT_NEXT_MINUTE_OPEN_AFTER_V2_CONFIRMATION",
        "contract_rule": "EXACT_MOVING_ATM_AT_V2_CONFIRMATION_NO_NEAREST_FALLBACK",
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "candidate_count": len(rows),
        "arm_counts": dict(sorted(Counter(r["entry_arm"] for r in rows).items())),
        "direction_counts": dict(sorted(Counter(r["entry_direction"] for r in rows).items())),
        "instrument_available_count": sum(bool(r["instrument_available"]) for r in rows),
        "entry_available_count": sum(bool(r["entry_available"]) for r in rows),
        "complete_15m_path_count": sum(bool(r["complete_15m_path"]) for r in rows),
        "overall_summary": summarize_rows(rows),
        "arm_summaries": arm_summaries,
        "direction_summaries": direction_summaries,
        "block_summaries": block_summaries,
        "rows": rows,
        "integrity": {
            "immediate_continuation_included": False,
            "oos_h_used": False,
            "future_outcome_used": False,
            "entry_direction_taken_from_v2_result": True,
            "atm_selected_at_v2_confirmation_timestamp": True,
            "entry_is_exact_next_minute_open": True,
            "nearest_strike_fallback_used": False,
            "pnl_rule_selection_performed": False,
            "exit_policy_search_performed": False,
        },
        "governance": {
            "development_research_only": True,
            "result_does_not_promote_v2": True,
            "result_does_not_authorize_paper_or_live_trading": True,
            "oos_h_must_not_be_used": True,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
