"""OHLC-aware premium backtest for frozen PCR + positioning candidates."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

CANDIDATE_TIERS = {"HIGH", "VERY_HIGH"}
RETURN_HORIZONS = (1, 3, 5, 10, 15)
TARGETS_PCT = (5.0, 10.0, 15.0)
STOPS_PCT = (5.0, 10.0)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _pct(n: int, d: int) -> float | None:
    return (100.0 * n / d) if d else None


def _offset_group(offset: int) -> str:
    if offset == 0:
        return "T0"
    if offset == 1:
        return "T_PLUS_1"
    if offset == 2:
        return "T_PLUS_2"
    if offset == 3:
        return "T_PLUS_3"
    return "T_PLUS_4_5"


def _load_positioning(path: str | Path):
    by_time: dict[tuple[str, datetime], list[dict[str, str]]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["session_date"], _dt(row["timestamp"]))
            by_time.setdefault(key, []).append(row)
    return by_time


def _load_ohlc(path: str | Path):
    idx: dict[tuple[str, str, datetime], dict[str, str]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            idx[(row["session_date"], row["instrument_key"], _dt(row["timestamp"]))] = row
    return idx


def _atm_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    exact = [r for r in rows if _finite_float(r.get("strike_offset")) == 0.0]
    if len(exact) == 1:
        return exact[0]
    if not rows:
        return None
    # Defensive fallback: choose strike nearest moving ATM if offset is unavailable.
    def distance(r: dict[str, str]) -> float:
        strike = _finite_float(r.get("strike"))
        atm = _finite_float(r.get("moving_atm"))
        return abs(strike - atm) if strike is not None and atm is not None else float("inf")
    best = min(rows, key=distance)
    return best if distance(best) != float("inf") else None


def _side_fields(direction: str) -> tuple[str, str]:
    if direction == "BULLISH":
        return "CE", "ce_instrument_key"
    if direction == "BEARISH":
        return "PE", "pe_instrument_key"
    raise ValueError(f"unsupported direction {direction}")


def _ret(px: float | None, entry: float | None) -> float | None:
    if px is None or entry is None or entry <= 0:
        return None
    return 100.0 * (px - entry) / entry


def _target_stop_result(
    bars: list[tuple[int, dict[str, str]]],
    *,
    entry: float,
    target_pct: float,
    stop_pct: float,
) -> dict[str, Any]:
    target_px = entry * (1.0 + target_pct / 100.0)
    stop_px = entry * (1.0 - stop_pct / 100.0)
    for minute, row in bars:
        high = _finite_float(row.get("high"))
        low = _finite_float(row.get("low"))
        if high is None or low is None:
            continue
        hit_target = high >= target_px
        hit_stop = low <= stop_px
        if hit_target and hit_stop:
            return {"result": "AMBIGUOUS_SAME_BAR", "minute": minute}
        if hit_target:
            return {"result": "TARGET_FIRST", "minute": minute}
        if hit_stop:
            return {"result": "STOP_FIRST", "minute": minute}
    return {"result": "NEITHER_WITHIN_15M", "minute": None}


def _summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "candidate_count": len(trades),
        "entry_available_count": sum(x.get("entry_premium") is not None for x in trades),
        "complete_15m_path_count": sum(x.get("returns_pct", {}).get("15m") is not None for x in trades),
        "outcome_counts": dict(sorted(Counter(str(x.get("outcome")) for x in trades).items())),
    }
    for horizon in RETURN_HORIZONS:
        key = f"{horizon}m"
        values = [float(x["returns_pct"][key]) for x in trades if x.get("returns_pct", {}).get(key) is not None]
        result[f"return_{key}"] = {
            "available_count": len(values),
            "positive_count": sum(v > 0 for v in values),
            "positive_pct": _pct(sum(v > 0 for v in values), len(values)),
            "mean_pct": (sum(values) / len(values)) if values else None,
            "median_pct": _median(values),
        }
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
            outcomes = [x.get("target_stop", {}).get(label, {}).get("result") for x in trades]
            outcomes = [o for o in outcomes if o]
            counts = Counter(outcomes)
            decisive = counts["TARGET_FIRST"] + counts["STOP_FIRST"]
            matrix[label] = {
                "available_count": len(outcomes),
                "target_first": counts["TARGET_FIRST"],
                "stop_first": counts["STOP_FIRST"],
                "ambiguous_same_bar": counts["AMBIGUOUS_SAME_BAR"],
                "neither_within_15m": counts["NEITHER_WITHIN_15M"],
                "target_first_pct_of_decisive": _pct(counts["TARGET_FIRST"], decisive),
            }
    result["target_stop_matrix"] = matrix
    return result


def analyze(confidence_path: str | Path, positioning_path: str | Path, ohlc_path: str | Path) -> dict[str, Any]:
    confidence = json.loads(Path(confidence_path).read_text(encoding="utf-8"))
    if confidence.get("status") != "AVAILABLE":
        raise ValueError("confidence-positioning report is not AVAILABLE")

    positioning = _load_positioning(positioning_path)
    ohlc = _load_ohlc(ohlc_path)
    trades: list[dict[str, Any]] = []

    for dkey in ("bearish", "bullish"):
        direction = dkey.upper()
        option_side, instrument_field = _side_fields(direction)
        for event in confidence.get("directions", {}).get(dkey, {}).get("events", []):
            tier = str(event.get("confidence_tier"))
            offset_raw = event.get("first_confirmation_offset_minutes")
            if tier not in CANDIDATE_TIERS or offset_raw is None:
                continue
            offset = int(offset_raw)
            if offset < 0 or offset > 5:
                continue

            session = str(event["session_date"])
            t0 = _dt(str(event["timestamp"]))
            confirmation_ts = t0 + timedelta(minutes=offset)
            atm = _atm_row(positioning.get((session, confirmation_ts), []))
            instrument_key = atm.get(instrument_field) if atm else None
            strike = _finite_float(atm.get("strike")) if atm else None

            entry_ts = confirmation_ts + timedelta(minutes=1)
            entry_row = ohlc.get((session, instrument_key, entry_ts)) if instrument_key else None
            entry = _finite_float(entry_row.get("open")) if entry_row else None

            returns: dict[str, float | None] = {}
            bars: list[tuple[int, dict[str, str]]] = []
            if instrument_key:
                for minute in range(0, 16):
                    row = ohlc.get((session, instrument_key, entry_ts + timedelta(minutes=minute)))
                    if row is not None:
                        bars.append((minute, row))
                for horizon in RETURN_HORIZONS:
                    row = ohlc.get((session, instrument_key, entry_ts + timedelta(minutes=horizon)))
                    returns[f"{horizon}m"] = _ret(_finite_float(row.get("close")) if row else None, entry)
            else:
                for horizon in RETURN_HORIZONS:
                    returns[f"{horizon}m"] = None

            highs = [_finite_float(row.get("high")) for _, row in bars]
            lows = [_finite_float(row.get("low")) for _, row in bars]
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
                            bars, entry=entry, target_pct=target, stop_pct=stop
                        )

            trades.append({
                "session_date": session,
                "stage2_timestamp": t0.isoformat(),
                "direction": direction,
                "option_side": option_side,
                "outcome": str(event.get("outcome")),
                "confidence_tier": tier,
                "confidence_score": event.get("confidence_score"),
                "confirmation_offset_minutes": offset,
                "confirmation_offset_group": _offset_group(offset),
                "confirmation_timestamp": confirmation_ts.isoformat(),
                "atm_strike_at_confirmation": strike,
                "instrument_key": instrument_key,
                "entry_rule": "NEXT_MINUTE_OPEN",
                "entry_timestamp": entry_ts.isoformat(),
                "entry_premium": entry,
                "returns_pct": returns,
                "mfe_pct_15m": mfe,
                "mae_pct_15m": mae,
                "target_stop": target_stop,
            })

    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        rows = [x for x in trades if x["direction"] == direction]
        by_timing = {
            group: _summarize([x for x in rows if x["confirmation_offset_group"] == group])
            for group in ("T0", "T_PLUS_1", "T_PLUS_2", "T_PLUS_3", "T_PLUS_4_5")
        }
        by_tier = {
            tier: _summarize([x for x in rows if x["confidence_tier"] == tier])
            for tier in ("HIGH", "VERY_HIGH")
        }
        directions[direction.lower()] = {
            "direction": direction,
            "option_side": "PE" if direction == "BEARISH" else "CE",
            "candidate_filter": "HIGH_OR_VERY_HIGH_AND_POSITIONING_CONFIRMED_WITHIN_5M",
            "summary": _summarize(rows),
            "by_confirmation_timing": by_timing,
            "by_confidence_tier": by_tier,
        }

    return {
        "status": "AVAILABLE",
        "confidence_source": str(confidence_path),
        "positioning_source": str(positioning_path),
        "ohlc_source": str(ohlc_path),
        "entry_rule": "NEXT_MINUTE_OPEN",
        "return_horizons_minutes": list(RETURN_HORIZONS),
        "target_pcts": list(TARGETS_PCT),
        "stop_pcts": list(STOPS_PCT),
        "methodology": [
            "Only HIGH or VERY_HIGH PCR-confidence events with positioning confirmation from T0 through T0+5m are evaluated.",
            "Bullish candidates freeze the ATM CE at positioning confirmation; bearish candidates freeze the ATM PE.",
            "Entry is the exact next-minute OPEN of that frozen instrument, avoiding confirmation-candle lookahead.",
            "MFE uses minute HIGH and MAE uses minute LOW from entry through +15m for the same instrument key.",
            "Target/stop tests step minute-by-minute. If target and stop are both touched inside the same 1-minute candle before either was previously resolved, the outcome is AMBIGUOUS_SAME_BAR rather than guessed.",
        ],
        "limitations": [
            "This is a research execution baseline; no brokerage, taxes, spread, slippage, queue position, quantity sizing, or overlapping-trade suppression is applied.",
            "One-minute candles cannot reveal target-vs-stop ordering when both levels are touched in the same candle; those cases are reported as ambiguous.",
            "Target/stop settings are descriptive matrices, not optimized or promoted trading rules.",
            "This output is research evidence and must not be interpreted as live-trading performance.",
        ],
        "directions": directions,
        "trades": trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OHLC backtest for PCR + positioning option candidates")
    parser.add_argument("--confidence", required=True)
    parser.add_argument("--positioning", required=True)
    parser.add_argument("--ohlc", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = analyze(args.confidence, args.positioning, args.ohlc)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    compact = {
        "status": result["status"],
        "entry_rule": result["entry_rule"],
        "output": str(out),
        "bearish": result["directions"]["bearish"],
        "bullish": result["directions"]["bullish"],
    }
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
