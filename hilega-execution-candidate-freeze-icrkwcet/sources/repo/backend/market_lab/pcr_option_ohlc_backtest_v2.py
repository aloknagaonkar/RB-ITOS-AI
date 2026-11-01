"""OHLC premium backtest for PCR Research Methodology v2.

Unlike v1, the traded contract is the exact T0-ATM CE/PE instrument carried by
methodology v2.  It is not re-selected at the confirmation timestamp.
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
from typing import Any

CANDIDATE_TIERS = {"HIGH", "VERY_HIGH"}
RETURN_HORIZONS = (1, 3, 5, 10, 15)
TARGETS_PCT = (5.0, 10.0, 15.0)
STOPS_PCT = (5.0, 10.0)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _ret(px: float | None, entry: float | None) -> float | None:
    if px is None or entry is None or entry <= 0:
        return None
    return 100.0 * (px - entry) / entry


def _load_ohlc(path: str | Path) -> dict[tuple[str, str, datetime], dict[str, str]]:
    idx: dict[tuple[str, str, datetime], dict[str, str]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            idx[(row["session_date"], row["instrument_key"], _dt(row["timestamp"]))] = row
    return idx


def _offset_group(offset: int) -> str:
    if offset == 0: return "T0"
    if offset == 1: return "T_PLUS_1"
    if offset == 2: return "T_PLUS_2"
    if offset == 3: return "T_PLUS_3"
    return "T_PLUS_4_5"


def _target_stop(bars: list[tuple[int, dict[str, str]]], entry: float, target: float, stop: float) -> dict[str, Any]:
    target_px = entry * (1 + target / 100.0)
    stop_px = entry * (1 - stop / 100.0)
    for minute, row in bars:
        hi, lo = _num(row.get("high")), _num(row.get("low"))
        if hi is None or lo is None:
            continue
        hit_t, hit_s = hi >= target_px, lo <= stop_px
        if hit_t and hit_s: return {"result": "AMBIGUOUS_SAME_BAR", "minute": minute}
        if hit_t: return {"result": "TARGET_FIRST", "minute": minute}
        if hit_s: return {"result": "STOP_FIRST", "minute": minute}
    return {"result": "NEITHER_WITHIN_15M", "minute": None}


def _summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "candidate_count": len(trades),
        "entry_available_count": sum(x.get("entry_premium") is not None for x in trades),
        "complete_15m_path_count": sum(x.get("returns_pct", {}).get("15m") is not None for x in trades),
        "outcome_counts": dict(sorted(Counter(str(x.get("outcome")) for x in trades).items())),
    }
    for horizon in RETURN_HORIZONS:
        key = f"{horizon}m"
        vals = [float(x["returns_pct"][key]) for x in trades if x.get("returns_pct", {}).get(key) is not None]
        out[f"return_{key}"] = {
            "available_count": len(vals), "positive_count": sum(v > 0 for v in vals),
            "positive_pct": _pct(sum(v > 0 for v in vals), len(vals)),
            "mean_pct": sum(vals) / len(vals) if vals else None, "median_pct": _median(vals),
        }
    mfe = [float(x["mfe_pct_15m"]) for x in trades if x.get("mfe_pct_15m") is not None]
    mae = [float(x["mae_pct_15m"]) for x in trades if x.get("mae_pct_15m") is not None]
    out["intrabar_excursion_15m"] = {"available_count": len(mfe), "median_mfe_pct": _median(mfe), "median_mae_pct": _median(mae)}
    matrix: dict[str, Any] = {}
    for target in TARGETS_PCT:
        for stop in STOPS_PCT:
            label = f"TARGET_{int(target)}_STOP_{int(stop)}"
            values = [x.get("target_stop", {}).get(label, {}).get("result") for x in trades]
            c = Counter(v for v in values if v)
            decisive = c["TARGET_FIRST"] + c["STOP_FIRST"]
            matrix[label] = {
                "available_count": sum(c.values()), "target_first": c["TARGET_FIRST"], "stop_first": c["STOP_FIRST"],
                "ambiguous_same_bar": c["AMBIGUOUS_SAME_BAR"], "neither_within_15m": c["NEITHER_WITHIN_15M"],
                "target_first_pct_of_decisive": _pct(c["TARGET_FIRST"], decisive),
            }
    out["target_stop_matrix"] = matrix
    return out


def analyze(methodology_path: str | Path, ohlc_path: str | Path) -> dict[str, Any]:
    methodology = json.loads(Path(methodology_path).read_text(encoding="utf-8"))
    if methodology.get("status") != "AVAILABLE" or methodology.get("methodology_version") != "PCR_RESEARCH_METHODOLOGY_V2":
        raise ValueError("methodology input must be AVAILABLE PCR_RESEARCH_METHODOLOGY_V2")
    guard = methodology.get("leakage_guard", {})
    if guard.get("current_holdout_validation_input_used") is not False or guard.get("panel_any_confirmation_allowed") is not False:
        raise ValueError("methodology leakage guard is not clean")
    ohlc = _load_ohlc(ohlc_path)
    trades: list[dict[str, Any]] = []

    for dkey in ("bearish", "bullish"):
        direction = dkey.upper()
        side = "PE" if direction == "BEARISH" else "CE"
        instrument_field = "t0_pe_instrument_key" if direction == "BEARISH" else "t0_ce_instrument_key"
        for event in methodology.get("directions", {}).get(dkey, {}).get("events", []):
            tier = str(event.get("confidence_tier"))
            offset = event.get("first_confirmation_offset_minutes")
            if tier not in CANDIDATE_TIERS or event.get("confirmation_status") != "CONFIRMED" or offset is None:
                continue
            offset = int(offset)
            if offset not in range(6):
                continue
            session = str(event["session_date"])
            t0 = _dt(str(event["timestamp"]))
            confirmation_ts = t0 + timedelta(minutes=offset)
            instrument = event.get(instrument_field)
            entry_ts = confirmation_ts + timedelta(minutes=1)
            entry_row = ohlc.get((session, instrument, entry_ts)) if instrument else None
            entry = _num(entry_row.get("open")) if entry_row else None
            bars: list[tuple[int, dict[str, str]]] = []
            returns: dict[str, float | None] = {}
            if instrument:
                for minute in range(16):
                    row = ohlc.get((session, instrument, entry_ts + timedelta(minutes=minute)))
                    if row is not None:
                        bars.append((minute, row))
                for h in RETURN_HORIZONS:
                    row = ohlc.get((session, instrument, entry_ts + timedelta(minutes=h)))
                    returns[f"{h}m"] = _ret(_num(row.get("close")) if row else None, entry)
            else:
                returns = {f"{h}m": None for h in RETURN_HORIZONS}
            highs = [_num(r.get("high")) for _, r in bars]
            lows = [_num(r.get("low")) for _, r in bars]
            highs = [x for x in highs if x is not None]
            lows = [x for x in lows if x is not None]
            target_stop: dict[str, Any] = {}
            if entry is not None and entry > 0:
                for target in TARGETS_PCT:
                    for stop in STOPS_PCT:
                        label = f"TARGET_{int(target)}_STOP_{int(stop)}"
                        target_stop[label] = _target_stop(bars, entry, target, stop)
            trades.append({
                "session_date": session,
                "stage2_timestamp": t0.isoformat(),
                "direction": direction,
                "option_side": side,
                "outcome": event.get("outcome"),
                "confidence_profile": event.get("confidence_profile"),
                "confidence_tier": tier,
                "confirmation_offset_minutes": offset,
                "confirmation_offset_group": _offset_group(offset),
                "confirmation_timestamp": confirmation_ts.isoformat(),
                "frozen_t0_atm_strike": event.get("t0_atm_strike"),
                "instrument_key": instrument,
                "contract_selection_rule": "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION",
                "entry_rule": "NEXT_MINUTE_OPEN",
                "entry_timestamp": entry_ts.isoformat(),
                "entry_premium": entry,
                "returns_pct": returns,
                "mfe_pct_15m": _ret(max(highs), entry) if highs else None,
                "mae_pct_15m": _ret(min(lows), entry) if lows else None,
                "target_stop": target_stop,
            })

    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        rows = [t for t in trades if t["direction"] == direction]
        directions[direction.lower()] = {
            "direction": direction,
            "option_side": "PE" if direction == "BEARISH" else "CE",
            "candidate_filter": "HIGH_OR_VERY_HIGH_AND_FROZEN_T0_ATM_SAME_STRIKE_CONFIRMED_WITHIN_5M",
            "summary": _summarize(rows),
            "by_confirmation_timing": {
                group: _summarize([t for t in rows if t["confirmation_offset_group"] == group])
                for group in ("T0", "T_PLUS_1", "T_PLUS_2", "T_PLUS_3", "T_PLUS_4_5")
            },
        }
    return {
        "status": "AVAILABLE",
        "methodology_version": "PCR_RESEARCH_METHODOLOGY_V2",
        "confidence_source": str(methodology_path),
        "ohlc_source": str(ohlc_path),
        "confidence_profile": methodology.get("profile"),
        "entry_rule": "NEXT_MINUTE_OPEN",
        "contract_selection_rule": "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION",
        "directions": directions,
        "trades": trades,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="OHLC backtest for leakage-guarded PCR methodology v2")
    p.add_argument("--methodology", required=True)
    p.add_argument("--ohlc", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = analyze(args.methodology, args.ohlc)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "methodology_version": result["methodology_version"],
        "confidence_profile": result["confidence_profile"], "entry_rule": result["entry_rule"],
        "contract_selection_rule": result["contract_selection_rule"],
        "bearish": result["directions"]["bearish"]["summary"],
        "bullish": result["directions"]["bullish"]["summary"],
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
