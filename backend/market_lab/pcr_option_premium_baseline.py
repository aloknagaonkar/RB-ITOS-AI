"""Lookahead-safe option-premium baseline for PCR confidence + positioning events.

This v1 deliberately uses only the already-built historical positioning sidecar.
Because that sidecar stores minute CLOSE (not OPEN/HIGH/LOW), entry is defined as
the exact same instrument's close at the minute after positioning confirmation.
Future returns are exact same-instrument minute closes. Missing observations remain
unavailable; there is no interpolation and no instrument substitution.

Research-only: no orders, brokerage/slippage, stops, targets, sizing, or execution.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

CANDIDATE_TIERS = {"HIGH", "VERY_HIGH"}
RETURN_HORIZONS = (1, 3, 5, 10, 15)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _median(values: Iterable[float]) -> float | None:
    data = list(values)
    return statistics.median(data) if data else None


def _pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


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


def _load_positioning(path: str | Path) -> tuple[dict[tuple[str, datetime], list[dict[str, str]]], dict[tuple[str, datetime, str], dict[str, str]]]:
    """Return timestamp rows and exact instrument rows from positioning sidecar CSV."""
    by_time: dict[tuple[str, datetime], list[dict[str, str]]] = defaultdict(list)
    by_instrument: dict[tuple[str, datetime, str], dict[str, str]] = {}
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            session = str(row["session_date"])
            ts = _dt(row["timestamp"])
            by_time[(session, ts)].append(row)
            for side in ("ce", "pe"):
                key = row.get(f"{side}_instrument_key")
                if not key:
                    continue
                identity = (session, ts, key)
                existing = by_instrument.get(identity)
                if existing is not None and existing is not row:
                    # Duplicate exposure of the same instrument in one minute would make
                    # a deterministic premium lookup ambiguous.
                    old_close = existing.get(f"{side}_close")
                    new_close = row.get(f"{side}_close")
                    if old_close != new_close:
                        raise ValueError(f"conflicting positioning rows for {identity}")
                by_instrument[identity] = row
    return dict(by_time), by_instrument


def _atm_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    matches = []
    for row in rows:
        try:
            offset = int(float(row.get("strike_offset", "")))
        except (TypeError, ValueError):
            continue
        if offset == 0:
            matches.append(row)
    if not matches:
        return None
    if len(matches) > 1:
        strikes = {row.get("strike") for row in matches}
        if len(strikes) > 1:
            raise ValueError("multiple ATM rows at one timestamp")
    return matches[0]


def _side_fields(direction: str) -> tuple[str, str, str]:
    if direction == "BULLISH":
        return "CE", "ce_instrument_key", "ce_close"
    if direction == "BEARISH":
        return "PE", "pe_instrument_key", "pe_close"
    raise ValueError(f"unsupported direction {direction}")


def _same_instrument_close(
    by_instrument: dict[tuple[str, datetime, str], dict[str, str]],
    *,
    session: str,
    timestamp: datetime,
    instrument_key: str,
    close_field: str,
) -> float | None:
    row = by_instrument.get((session, timestamp, instrument_key))
    if row is None:
        return None
    return _finite_float(row.get(close_field))


def _summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "candidate_count": len(trades),
        "entry_available_count": sum(1 for x in trades if x["entry_premium"] is not None),
        "complete_15m_path_count": sum(1 for x in trades if x["returns_pct"].get("15m") is not None),
        "outcome_counts": dict(sorted(Counter(str(x["outcome"]) for x in trades).items())),
    }
    for horizon in RETURN_HORIZONS:
        key = f"{horizon}m"
        values = [float(x["returns_pct"][key]) for x in trades if x["returns_pct"].get(key) is not None]
        result[f"return_{key}"] = {
            "available_count": len(values),
            "positive_count": sum(v > 0 for v in values),
            "positive_pct": _pct(sum(v > 0 for v in values), len(values)),
            "mean_pct": (sum(values) / len(values)) if values else None,
            "median_pct": _median(values),
        }
    favorable = [float(x["max_favorable_close_excursion_pct_15m"]) for x in trades if x.get("max_favorable_close_excursion_pct_15m") is not None]
    adverse = [float(x["max_adverse_close_excursion_pct_15m"]) for x in trades if x.get("max_adverse_close_excursion_pct_15m") is not None]
    result["close_excursion_15m"] = {
        "available_count": len(favorable),
        "median_max_favorable_pct": _median(favorable),
        "median_max_adverse_pct": _median(adverse),
    }
    return result


def analyze(confidence_path: str | Path, positioning_path: str | Path) -> dict[str, Any]:
    confidence = json.loads(Path(confidence_path).read_text(encoding="utf-8"))
    if confidence.get("status") != "AVAILABLE":
        raise ValueError("confidence-positioning report is not AVAILABLE")

    by_time, by_instrument = _load_positioning(positioning_path)
    trades: list[dict[str, Any]] = []

    for dkey in ("bearish", "bullish"):
        direction = dkey.upper()
        option_side, instrument_field, close_field = _side_fields(direction)
        events = confidence.get("directions", {}).get(dkey, {}).get("events", [])
        for event in events:
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
            atm = _atm_row(by_time.get((session, confirmation_ts), []))

            instrument_key = atm.get(instrument_field) if atm else None
            strike = _finite_float(atm.get("strike")) if atm else None
            atm_confirmation_close = _finite_float(atm.get(close_field)) if atm else None
            entry_ts = confirmation_ts + timedelta(minutes=1)
            entry_premium = None
            if instrument_key:
                entry_premium = _same_instrument_close(
                    by_instrument,
                    session=session,
                    timestamp=entry_ts,
                    instrument_key=instrument_key,
                    close_field=close_field,
                )

            returns: dict[str, float | None] = {}
            path_returns: list[float] = []
            for horizon in RETURN_HORIZONS:
                value = None
                if instrument_key and entry_premium is not None and entry_premium > 0:
                    future = _same_instrument_close(
                        by_instrument,
                        session=session,
                        timestamp=entry_ts + timedelta(minutes=horizon),
                        instrument_key=instrument_key,
                        close_field=close_field,
                    )
                    if future is not None:
                        value = 100.0 * (future - entry_premium) / entry_premium
                returns[f"{horizon}m"] = value

            # Minute-close excursion, not intrabar MFE/MAE. Inspect every exact minute
            # from entry through +15m for the same instrument.
            if instrument_key and entry_premium is not None and entry_premium > 0:
                for minute in range(0, 16):
                    px = _same_instrument_close(
                        by_instrument,
                        session=session,
                        timestamp=entry_ts + timedelta(minutes=minute),
                        instrument_key=instrument_key,
                        close_field=close_field,
                    )
                    if px is not None:
                        path_returns.append(100.0 * (px - entry_premium) / entry_premium)

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
                "confirmation_close": atm_confirmation_close,
                "entry_rule": "NEXT_MINUTE_CLOSE",
                "entry_timestamp": entry_ts.isoformat(),
                "entry_premium": entry_premium,
                "returns_pct": returns,
                "max_favorable_close_excursion_pct_15m": max(path_returns) if path_returns else None,
                "max_adverse_close_excursion_pct_15m": min(path_returns) if path_returns else None,
            })

    directions: dict[str, Any] = {}
    for direction in ("BEARISH", "BULLISH"):
        rows = [x for x in trades if x["direction"] == direction]
        by_timing = {}
        for group in ("T0", "T_PLUS_1", "T_PLUS_2", "T_PLUS_3", "T_PLUS_4_5"):
            by_timing[group] = _summarize([x for x in rows if x["confirmation_offset_group"] == group])
        by_tier = {}
        for tier in ("HIGH", "VERY_HIGH"):
            by_tier[tier] = _summarize([x for x in rows if x["confidence_tier"] == tier])
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
        "entry_rule": "NEXT_MINUTE_CLOSE",
        "return_horizons_minutes": list(RETURN_HORIZONS),
        "methodology": [
            "Only HIGH or VERY_HIGH PCR-confidence events with positioning confirmation from T0 through T0+5m are evaluated.",
            "Bullish candidates buy the ATM CE at the positioning-confirmation timestamp; bearish candidates buy the ATM PE.",
            "The selected ATM instrument is frozen at confirmation and all future premium observations use the exact same instrument key.",
            "To avoid using the confirmation candle close as an executable price, v1 enters at the exact next minute close because the existing sidecar does not retain option candle open/high/low.",
            "Returns use exact same-instrument minute closes at +1/+3/+5/+10/+15 minutes after entry; missing data remains unavailable.",
            "The 15m excursion fields are maximum/minimum observed minute-CLOSE returns, not intrabar MFE/MAE.",
        ],
        "limitations": [
            "NEXT_MINUTE_CLOSE is a lookahead-safe baseline, not a production execution model; a future raw-OHLC extension should test next-minute OPEN and intrabar HIGH/LOW.",
            "The positioning sidecar contains only the moving ATM ±5 basket each minute, so a frozen instrument can become unavailable if it leaves that basket.",
            "No brokerage, taxes, spread, slippage, quantity sizing, stop-loss, target, or overlapping-trade suppression is applied.",
            "This output is research evidence and must not be interpreted as live-trading performance.",
        ],
        "directions": directions,
        "trades": trades,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest premium paths for HIGH/VERY_HIGH PCR+positioning candidates")
    p.add_argument("--confidence", required=True, help="PCR confidence + positioning JSON report")
    p.add_argument("--positioning", required=True, help="Historical positioning sidecar CSV")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    result = analyze(args.confidence, args.positioning)
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
