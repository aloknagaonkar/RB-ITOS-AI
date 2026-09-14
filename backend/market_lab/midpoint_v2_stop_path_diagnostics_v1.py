from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_STOP_PATH_DIAGNOSTICS_V1"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V2_NEW_ARM_EXACT_OPTION_ECONOMICS_V1"
ALLOWED_ARMS = {"BASE_THEN_GO", "FAILED_BREAK_RECLAIM"}
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}

STOP_PCT = 5.0
BE_TRIGGER_PCT = 5.0
TRAIL_TRIGGER_PCT = 10.0
ROUND_TRIP_COST_PCT_POINTS = 0.5


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
    if block not in ALLOWED_BLOCKS:
        raise ValueError(f"unsupported block {block!r}")
    return block, Path(path.strip())


def first_existing(headers: list[str], candidates: tuple[str, ...]) -> str:
    lower = {h.lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    raise ValueError(f"missing columns {candidates!r}; available={headers!r}")


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
        return float(value)
    except (TypeError, ValueError):
        return None


def load_ohlc(path: Path) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts", "candle_timestamp"))
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        key_col = first_existing(headers, ("instrument_key", "instrument", "instrument_token", "key"))
        open_col = first_existing(headers, ("open", "open_price", "o"))
        high_col = first_existing(headers, ("high", "high_price", "h"))
        low_col = first_existing(headers, ("low", "low_price", "l"))
        close_col = first_existing(headers, ("close", "close_price", "c"))

        for row in reader:
            raw_ts = row.get(ts_col)
            instrument_key = row.get(key_col)
            if not raw_ts or not instrument_key:
                continue
            try:
                ts = parse_dt(str(raw_ts))
            except ValueError:
                continue
            session_date = str(row.get(date_col)) if date_col and row.get(date_col) else ts.date().isoformat()
            out.setdefault((session_date, str(instrument_key)), {})[ts.isoformat()] = {
                "timestamp": ts.isoformat(),
                "open": finite_float(row.get(open_col)),
                "high": finite_float(row.get(high_col)),
                "low": finite_float(row.get(low_col)),
                "close": finite_float(row.get(close_col)),
            }
    return out


def pct(entry: float, price: float) -> float:
    return (price / entry - 1.0) * 100.0


def diagnose_trade(trade: dict[str, Any], series: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry_ts = parse_dt(str(trade["entry_timestamp"]))
    entry = float(trade["entry_price"])
    stop_price = entry * (1.0 - STOP_PCT / 100.0)

    path = []
    for minute in range(16):
        ts = entry_ts + timedelta(minutes=minute)
        candle = series.get(ts.isoformat())
        if candle is None:
            return {**trade, "diagnostic_available": False, "issue": "MISSING_15M_PATH", "missing_timestamp": ts.isoformat()}
        vals = [candle.get(k) for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            return {**trade, "diagnostic_available": False, "issue": "INCOMPLETE_15M_PATH", "missing_timestamp": ts.isoformat()}
        path.append({
            "minute": minute,
            "timestamp": ts.isoformat(),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        })

    stop_idx = None
    stop_kind = None
    for bar in path:
        if bar["open"] <= stop_price:
            stop_idx = int(bar["minute"])
            stop_kind = "GAP"
            break
        if bar["low"] <= stop_price:
            stop_idx = int(bar["minute"])
            stop_kind = "TOUCH"
            break

    considered = path if stop_idx is None else path[: stop_idx + 1]
    high_before_stop = max(b["high"] for b in considered)
    low_before_stop = min(b["low"] for b in considered)

    result = {
        **trade,
        "diagnostic_available": True,
        "issue": None,
        "stop5_price": stop_price,
        "stop5_hit": stop_idx is not None,
        "stop5_hit_minute": stop_idx,
        "stop5_hit_kind": stop_kind,
        "high_before_stop_pct": pct(entry, high_before_stop),
        "low_before_stop_pct": pct(entry, low_before_stop),
        "same_stop_bar_order_ambiguous_for_plus5": False,
        "same_stop_bar_order_ambiguous_for_plus10": False,
        "recovered_to_entry_after_stop": None,
        "reached_plus5_after_stop": None,
        "reached_plus10_after_stop": None,
        "max_high_after_stop_pct": None,
        "max_close_after_stop_pct": None,
        "final_15m_gross_pct": pct(entry, path[15]["close"]),
        "final_15m_net_pct": pct(entry, path[15]["close"]) - ROUND_TRIP_COST_PCT_POINTS,
    }

    if stop_idx is not None:
        stop_bar = path[stop_idx]
        result["same_stop_bar_order_ambiguous_for_plus5"] = stop_bar["high"] >= entry * 1.05
        result["same_stop_bar_order_ambiguous_for_plus10"] = stop_bar["high"] >= entry * 1.10

        later = path[stop_idx + 1 :]
        if later:
            max_high = max(b["high"] for b in later)
            max_close = max(b["close"] for b in later)
            result["max_high_after_stop_pct"] = pct(entry, max_high)
            result["max_close_after_stop_pct"] = pct(entry, max_close)
            result["recovered_to_entry_after_stop"] = max_high >= entry
            result["reached_plus5_after_stop"] = max_high >= entry * 1.05
            result["reached_plus10_after_stop"] = max_high >= entry * 1.10
        else:
            result["recovered_to_entry_after_stop"] = False
            result["reached_plus5_after_stop"] = False
            result["reached_plus10_after_stop"] = False

    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r.get("diagnostic_available")]
    stopped = [r for r in valid if r.get("stop5_hit")]
    stop_minutes = [int(r["stop5_hit_minute"]) for r in stopped if r.get("stop5_hit_minute") is not None]
    final_net_stopped = [float(r["final_15m_net_pct"]) for r in stopped]

    return {
        "trade_count": len(rows),
        "diagnostic_available_count": len(valid),
        "issue_counts": dict(sorted(Counter(str(r.get("issue")) for r in rows if r.get("issue")).items())),
        "stop5_hit_count": len(stopped),
        "stop5_hit_pct": (100.0 * len(stopped) / len(valid)) if valid else None,
        "stop5_gap_count": sum(r.get("stop5_hit_kind") == "GAP" for r in stopped),
        "stop5_touch_count": sum(r.get("stop5_hit_kind") == "TOUCH" for r in stopped),
        "median_stop5_hit_minute": median(stop_minutes) if stop_minutes else None,
        "mean_stop5_hit_minute": mean(stop_minutes) if stop_minutes else None,
        "stop5_hit_then_recovered_to_entry_count": sum(bool(r.get("recovered_to_entry_after_stop")) for r in stopped),
        "stop5_hit_then_reached_plus5_count": sum(bool(r.get("reached_plus5_after_stop")) for r in stopped),
        "stop5_hit_then_reached_plus10_count": sum(bool(r.get("reached_plus10_after_stop")) for r in stopped),
        "stop5_hit_but_final_15m_net_positive_count": sum(float(r["final_15m_net_pct"]) > 0 for r in stopped),
        "stop5_hit_final_15m_net_mean_pct": mean(final_net_stopped) if final_net_stopped else None,
        "stop5_hit_final_15m_net_median_pct": median(final_net_stopped) if final_net_stopped else None,
        "same_stop_bar_plus5_order_ambiguous_count": sum(bool(r.get("same_stop_bar_order_ambiguous_for_plus5")) for r in stopped),
        "same_stop_bar_plus10_order_ambiguous_count": sum(bool(r.get("same_stop_bar_order_ambiguous_for_plus10")) for r in stopped),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--economics", required=True)
    ap.add_argument("--ohlc", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    economics = load_json(Path(args.economics))
    if economics.get("research_version") != EXPECTED_ECONOMICS_VERSION:
        raise SystemExit(f"unexpected economics version={economics.get('research_version')!r}")
    if economics.get("candidate_count") != 17:
        raise SystemExit(f"expected 17 candidates, got {economics.get('candidate_count')!r}")
    if (economics.get("integrity") or {}).get("oos_h_used"):
        raise SystemExit("OOS-H forbidden")

    specs = [parse_block_path(v) for v in args.ohlc]
    if {b for b, _ in specs} != ALLOWED_BLOCKS:
        raise SystemExit("need OHLC for TRAIN + OOS_A/B/C/D exactly")
    ohlc_by_block = {b: load_ohlc(p) for b, p in specs}

    source_rows = economics.get("rows") or []
    if len(source_rows) != 17:
        raise SystemExit(f"expected 17 economics rows, got {len(source_rows)}")

    rows = []
    for trade in source_rows:
        arm = str(trade.get("entry_arm"))
        if arm not in ALLOWED_ARMS:
            raise SystemExit(f"unexpected arm {arm!r}")
        block = str(trade["block"])
        key = (str(trade["session_date"]), str(trade["instrument_key"]))
        rows.append(diagnose_trade(trade, ohlc_by_block[block].get(key, {})))

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_economics_version": EXPECTED_ECONOMICS_VERSION,
        "candidate_count": 17,
        "diagnostic_stop_pct": STOP_PCT,
        "reference_trigger_levels_pct": {
            "breakeven_trigger_pct": BE_TRIGGER_PCT,
            "trail_trigger_pct": TRAIL_TRIGGER_PCT,
        },
        "overall_summary": summarize(rows),
        "arm_summaries": {
            arm: summarize([r for r in rows if r["entry_arm"] == arm])
            for arm in ("BASE_THEN_GO", "FAILED_BREAK_RECLAIM")
        },
        "direction_summaries": {
            direction: summarize([r for r in rows if r["entry_direction"] == direction])
            for direction in ("BULLISH", "BEARISH")
        },
        "rows": rows,
        "integrity": {
            "entry_logic_modified": False,
            "exit_policy_selected": False,
            "alternative_stop_thresholds_tested": False,
            "stop5_used_as_existing_reference_only": True,
            "intrabar_order_inferred": False,
            "post_stop_analysis_starts_next_bar": True,
            "oos_h_used": False,
            "immediate_continuation_included": False,
        },
        "governance": {
            "diagnostic_only": True,
            "no_new_stop_parameter_promoted": True,
            "no_v2_arm_promoted_or_rejected_automatically": True,
            "fresh_oos_required_before_any_v2_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
