"""Directional Price-Momentum Option Buying Strategy V1 - signal engine.

This is the first price-primary research step after the PCR research branch.

Important design rules
----------------------
* Price action is the PRIMARY signal.
* PCR is recorded only as optional diagnostic context and never participates
  in signal generation.
* Only information available at or before the signal minute is used.
* `forward_change_*` columns are explicitly forbidden as signal inputs.
* The signal freezes the exact moving-ATM CE/PE instrument at the signal minute.
* Option entry/backtest is deliberately handled by a separate module.

V1 uses the existing historical evidence minute `spot` series as a close-price
proxy. It therefore detects CLOSE breakouts, not intrabar wick/body patterns.
If V1 shows promise, underlying OHLC can be added later without changing the
research discipline.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


STRATEGY_ID = "DIRECTIONAL_PRICE_MOMENTUM_OPTION_BUYING_V1"
SIGNAL_ENGINE_VERSION = "PRICE_MOMENTUM_SIGNAL_ENGINE_V1"

IST = timezone(timedelta(hours=5, minutes=30))

ALLOWED_DEVELOPMENT_BLOCKS = {
    "TRAIN",
    "OOS_A",
    "OOS_B",
    "OOS_C",
    "OOS_D",
}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}

FAST_EMA_PERIOD = 5
SLOW_EMA_PERIOD = 15
EMA_SLOPE_LOOKBACK = 3
MOMENTUM_FAST_MINUTES = 5
MOMENTUM_SLOW_MINUTES = 15
BREAKOUT_LOOKBACK = 20
EXPANSION_LOOKBACK = 20
EXPANSION_MULTIPLIER = 1.25
MAX_BREAKOUT_EXTENSION_RANGE_FRACTION = 0.75
MIN_EXTENSION_POINTS = 5.0
COOLDOWN_MINUTES = 10
EARLIEST_SIGNAL_TIME = time(9, 45)
LATEST_SIGNAL_TIME = time(15, 10)


@dataclass(frozen=True)
class BlockInput:
    name: str
    evidence_path: Path
    positioning_path: Path


@dataclass(frozen=True)
class Signal:
    block: str
    session_date: str
    timestamp: str
    direction: str
    option_side: str
    signal_status: str
    option_selection_status: str
    moving_atm: float | None
    strike: float | None
    instrument_key: str | None
    spot: float
    ema_fast: float
    ema_slow: float
    ema_fast_slope_3m: float
    spot_momentum_5m: float
    spot_momentum_15m: float
    prior_20m_high_close: float
    prior_20m_low_close: float
    prior_20m_close_range: float
    breakout_extension_points: float
    current_1m_change: float
    median_abs_1m_change_20m: float
    expansion_ratio: float | None
    realized_vol_15m: float
    trend_condition: bool
    momentum_condition: bool
    breakout_condition: bool
    expansion_condition: bool
    not_overextended_condition: bool
    pcr_context_used_for_signal: bool
    fixed_pcr: float | None
    moving_pcr: float | None
    full_pcr: float | None
    moving_pcr_change_5m: float | None


def normalize_block_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def parse_block(value: str) -> BlockInput:
    parts = value.split("|")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "--block must be NAME|EVIDENCE_CSV|POSITIONING_CSV"
        )

    name, evidence, positioning = parts
    name = normalize_block_name(name)

    if name in FORBIDDEN_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"{name} is forbidden for V1 development signal construction"
        )
    if name not in ALLOWED_DEVELOPMENT_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"Unsupported development block {name}; "
            f"allowed={sorted(ALLOWED_DEVELOPMENT_BLOCKS)}"
        )

    return BlockInput(name, Path(evidence), Path(positioning))


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def minute_iso(value: str) -> str:
    return parse_dt(value).replace(second=0, microsecond=0).isoformat()


def f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "unavailable"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_evidence_columns(rows: Sequence[dict[str, str]], path: Path) -> None:
    if not rows:
        raise ValueError(f"{path} has no rows")
    required = {
        "session_date",
        "timestamp",
        "spot",
        "moving_atm",
        "fixed_pcr",
        "moving_pcr",
        "full_pcr",
        "moving_pcr_change_5m",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"{path} missing evidence columns: {sorted(missing)}")


def validate_positioning_columns(rows: Sequence[dict[str, str]], path: Path) -> None:
    if not rows:
        raise ValueError(f"{path} has no rows")
    required = {
        "session_date",
        "timestamp",
        "moving_atm",
        "strike",
        "strike_offset",
        "ce_instrument_key",
        "pe_instrument_key",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"{path} missing positioning columns: {sorted(missing)}")


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def realized_vol_15m(spots: Sequence[float], index: int) -> float:
    if index < 15:
        raise ValueError("15-minute history unavailable")
    segment = spots[index - 15 : index + 1]
    changes = [segment[i] - segment[i - 1] for i in range(1, len(segment))]
    return statistics.pstdev(changes)


def prior_abs_change_median(
    spots: Sequence[float], index: int, lookback: int
) -> float:
    if index < lookback:
        raise ValueError("expansion history unavailable")
    changes = [
        abs(spots[j] - spots[j - 1])
        for j in range(index - lookback + 1, index)
    ]
    if not changes:
        return 0.0
    return statistics.median(changes)


def positioning_atm_index(
    rows: Sequence[dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        offset = f(row.get("strike_offset"))
        if offset is None or abs(offset) > 1e-9:
            continue
        key = (row["session_date"], minute_iso(row["timestamp"]))
        if key in result:
            raise ValueError(f"Duplicate ATM positioning row: {key}")
        result[key] = row
    return result


def session_rows(
    evidence: Sequence[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in evidence:
        groups.setdefault(row["session_date"], []).append(row)

    for date, rows in groups.items():
        rows.sort(key=lambda x: parse_dt(x["timestamp"]))
        seen: set[str] = set()
        for row in rows:
            ts = minute_iso(row["timestamp"])
            if ts in seen:
                raise ValueError(f"Duplicate evidence minute {date} {ts}")
            seen.add(ts)
    return groups


def _signal_direction(
    *,
    spot: float,
    prior_high: float,
    prior_low: float,
    ema_fast_value: float,
    ema_slow_value: float,
    ema_slope: float,
    momentum_5m: float,
    momentum_15m: float,
    current_1m_change: float,
    median_abs_change: float,
    prior_range: float,
) -> tuple[str | None, dict[str, bool], float, float | None]:
    expansion_threshold = EXPANSION_MULTIPLIER * median_abs_change
    expansion_ratio = (
        abs(current_1m_change) / median_abs_change
        if median_abs_change > 0
        else None
    )

    max_extension = max(
        MIN_EXTENSION_POINTS,
        MAX_BREAKOUT_EXTENSION_RANGE_FRACTION * prior_range,
    )

    bullish_trend = ema_fast_value > ema_slow_value and ema_slope > 0
    bullish_momentum = momentum_5m > 0 and momentum_15m > 0
    bullish_breakout = spot > prior_high
    bullish_expansion = (
        current_1m_change > 0
        and (
            abs(current_1m_change) >= expansion_threshold
            if median_abs_change > 0
            else current_1m_change > 0
        )
    )
    bullish_extension = spot - prior_high
    bullish_not_extended = 0 < bullish_extension <= max_extension

    bearish_trend = ema_fast_value < ema_slow_value and ema_slope < 0
    bearish_momentum = momentum_5m < 0 and momentum_15m < 0
    bearish_breakout = spot < prior_low
    bearish_expansion = (
        current_1m_change < 0
        and (
            abs(current_1m_change) >= expansion_threshold
            if median_abs_change > 0
            else current_1m_change < 0
        )
    )
    bearish_extension = prior_low - spot
    bearish_not_extended = 0 < bearish_extension <= max_extension

    if all(
        (
            bullish_trend,
            bullish_momentum,
            bullish_breakout,
            bullish_expansion,
            bullish_not_extended,
        )
    ):
        return (
            "BULLISH",
            {
                "trend": bullish_trend,
                "momentum": bullish_momentum,
                "breakout": bullish_breakout,
                "expansion": bullish_expansion,
                "not_overextended": bullish_not_extended,
            },
            bullish_extension,
            expansion_ratio,
        )

    if all(
        (
            bearish_trend,
            bearish_momentum,
            bearish_breakout,
            bearish_expansion,
            bearish_not_extended,
        )
    ):
        return (
            "BEARISH",
            {
                "trend": bearish_trend,
                "momentum": bearish_momentum,
                "breakout": bearish_breakout,
                "expansion": bearish_expansion,
                "not_overextended": bearish_not_extended,
            },
            bearish_extension,
            expansion_ratio,
        )

    return None, {}, 0.0, expansion_ratio


def generate_block_signals(block: BlockInput) -> tuple[list[Signal], dict[str, Any]]:
    evidence = load_csv(block.evidence_path)
    positioning = load_csv(block.positioning_path)

    validate_evidence_columns(evidence, block.evidence_path)
    validate_positioning_columns(positioning, block.positioning_path)

    atm_rows = positioning_atm_index(positioning)
    by_session = session_rows(evidence)

    signals: list[Signal] = []
    session_summaries: dict[str, dict[str, int]] = {}

    minimum_index = max(
        SLOW_EMA_PERIOD,
        MOMENTUM_SLOW_MINUTES,
        BREAKOUT_LOOKBACK,
        EXPANSION_LOOKBACK,
        EMA_SLOPE_LOOKBACK,
    )

    for date, rows in sorted(by_session.items()):
        valid_rows: list[dict[str, str]] = []
        spots: list[float] = []

        for row in rows:
            spot = f(row.get("spot"))
            if spot is None:
                continue
            valid_rows.append(row)
            spots.append(spot)

        if not valid_rows:
            session_summaries[date] = {"bullish": 0, "bearish": 0, "total": 0}
            continue

        fast = ema(spots, FAST_EMA_PERIOD)
        slow = ema(spots, SLOW_EMA_PERIOD)
        last_signal_at: dict[str, datetime | None] = {
            "BULLISH": None,
            "BEARISH": None,
        }
        counts = {"bullish": 0, "bearish": 0, "total": 0}

        for i in range(minimum_index, len(valid_rows)):
            row = valid_rows[i]
            at = parse_dt(row["timestamp"])
            local_t = at.time().replace(tzinfo=None)

            if local_t < EARLIEST_SIGNAL_TIME or local_t > LATEST_SIGNAL_TIME:
                continue

            # Require exact consecutive minute history for all research inputs.
            exact = True
            for offset in range(BREAKOUT_LOOKBACK, -1, -1):
                expected = at - timedelta(minutes=offset)
                actual = parse_dt(valid_rows[i - offset]["timestamp"])
                if actual.replace(second=0, microsecond=0) != expected.replace(
                    second=0, microsecond=0
                ):
                    exact = False
                    break
            if not exact:
                continue

            spot = spots[i]
            prior = spots[i - BREAKOUT_LOOKBACK : i]
            prior_high = max(prior)
            prior_low = min(prior)
            prior_range = prior_high - prior_low

            m5 = spot - spots[i - MOMENTUM_FAST_MINUTES]
            m15 = spot - spots[i - MOMENTUM_SLOW_MINUTES]
            slope = fast[i] - fast[i - EMA_SLOPE_LOOKBACK]
            change1 = spot - spots[i - 1]
            med_abs = prior_abs_change_median(spots, i, EXPANSION_LOOKBACK)
            vol15 = realized_vol_15m(spots, i)

            direction, conditions, extension, expansion_ratio = _signal_direction(
                spot=spot,
                prior_high=prior_high,
                prior_low=prior_low,
                ema_fast_value=fast[i],
                ema_slow_value=slow[i],
                ema_slope=slope,
                momentum_5m=m5,
                momentum_15m=m15,
                current_1m_change=change1,
                median_abs_change=med_abs,
                prior_range=prior_range,
            )

            if direction is None:
                continue

            previous = last_signal_at[direction]
            if previous is not None and at - previous < timedelta(
                minutes=COOLDOWN_MINUTES
            ):
                continue

            last_signal_at[direction] = at

            key = (date, minute_iso(row["timestamp"]))
            atm = atm_rows.get(key)

            option_side = "CE" if direction == "BULLISH" else "PE"
            moving_atm = f(row.get("moving_atm"))
            strike = f(atm.get("strike")) if atm else None
            instrument_key = None
            option_selection_status = "UNAVAILABLE"

            if atm is not None:
                instrument_key = (
                    atm.get("ce_instrument_key")
                    if direction == "BULLISH"
                    else atm.get("pe_instrument_key")
                )
                instrument_key = (instrument_key or "").strip() or None

                atm_moving = f(atm.get("moving_atm"))
                if (
                    moving_atm is not None
                    and atm_moving is not None
                    and abs(moving_atm - atm_moving) <= 1e-9
                    and strike is not None
                    and abs(strike - moving_atm) <= 1e-9
                    and instrument_key is not None
                ):
                    option_selection_status = "AVAILABLE_EXACT_MOVING_ATM"
                else:
                    instrument_key = None

            signal = Signal(
                block=block.name,
                session_date=date,
                timestamp=minute_iso(row["timestamp"]),
                direction=direction,
                option_side=option_side,
                signal_status="PRICE_MOMENTUM_BREAKOUT_CONFIRMED",
                option_selection_status=option_selection_status,
                moving_atm=moving_atm,
                strike=strike,
                instrument_key=instrument_key,
                spot=spot,
                ema_fast=fast[i],
                ema_slow=slow[i],
                ema_fast_slope_3m=slope,
                spot_momentum_5m=m5,
                spot_momentum_15m=m15,
                prior_20m_high_close=prior_high,
                prior_20m_low_close=prior_low,
                prior_20m_close_range=prior_range,
                breakout_extension_points=extension,
                current_1m_change=change1,
                median_abs_1m_change_20m=med_abs,
                expansion_ratio=expansion_ratio,
                realized_vol_15m=vol15,
                trend_condition=conditions["trend"],
                momentum_condition=conditions["momentum"],
                breakout_condition=conditions["breakout"],
                expansion_condition=conditions["expansion"],
                not_overextended_condition=conditions["not_overextended"],
                pcr_context_used_for_signal=False,
                fixed_pcr=f(row.get("fixed_pcr")),
                moving_pcr=f(row.get("moving_pcr")),
                full_pcr=f(row.get("full_pcr")),
                moving_pcr_change_5m=f(row.get("moving_pcr_change_5m")),
            )
            signals.append(signal)
            counts[direction.lower()] += 1
            counts["total"] += 1

        session_summaries[date] = counts

    summary = {
        "block": block.name,
        "session_count": len(by_session),
        "signal_count": len(signals),
        "bullish_signal_count": sum(s.direction == "BULLISH" for s in signals),
        "bearish_signal_count": sum(s.direction == "BEARISH" for s in signals),
        "option_available_count": sum(
            s.option_selection_status == "AVAILABLE_EXACT_MOVING_ATM"
            for s in signals
        ),
        "session_summaries": session_summaries,
    }
    return signals, summary


def write_csv(signals: Sequence[Signal], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not signals:
        path.write_text("", encoding="utf-8")
        return
    rows = [asdict(signal) for signal in signals]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Directional Price-Momentum Option Buying Strategy V1 "
            "price-primary signal generator"
        )
    )
    parser.add_argument(
        "--block",
        action="append",
        required=True,
        type=parse_block,
        help="NAME|EVIDENCE_CSV|POSITIONING_CSV",
    )
    parser.add_argument("--output", required=True, help="Signal JSON output")
    parser.add_argument("--csv-output", required=True, help="Per-signal CSV output")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    blocks: list[BlockInput] = args.block
    names = [b.name for b in blocks]

    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate block names: {names}")

    # For the first development study we require the same complete five-block
    # development universe used by prior research.
    if set(names) != ALLOWED_DEVELOPMENT_BLOCKS:
        raise ValueError(
            "V1 development construction requires exactly "
            f"{sorted(ALLOWED_DEVELOPMENT_BLOCKS)}; received={sorted(names)}"
        )

    all_signals: list[Signal] = []
    block_summaries: dict[str, Any] = {}

    for block in blocks:
        signals, summary = generate_block_signals(block)
        all_signals.extend(signals)
        block_summaries[block.name] = summary

    payload = {
        "status": "AVAILABLE",
        "strategy_id": STRATEGY_ID,
        "signal_engine_version": SIGNAL_ENGINE_VERSION,
        "research_status": "DEVELOPMENT_SIGNAL_GENERATION",
        "development_blocks": sorted(names),
        "parameters": {
            "fast_ema_period": FAST_EMA_PERIOD,
            "slow_ema_period": SLOW_EMA_PERIOD,
            "ema_slope_lookback_minutes": EMA_SLOPE_LOOKBACK,
            "momentum_fast_minutes": MOMENTUM_FAST_MINUTES,
            "momentum_slow_minutes": MOMENTUM_SLOW_MINUTES,
            "breakout_lookback_minutes": BREAKOUT_LOOKBACK,
            "expansion_lookback_minutes": EXPANSION_LOOKBACK,
            "expansion_multiplier": EXPANSION_MULTIPLIER,
            "max_breakout_extension_prior_range_fraction": (
                MAX_BREAKOUT_EXTENSION_RANGE_FRACTION
            ),
            "minimum_extension_points": MIN_EXTENSION_POINTS,
            "cooldown_minutes_same_direction": COOLDOWN_MINUTES,
            "earliest_signal_time_ist": EARLIEST_SIGNAL_TIME.isoformat(),
            "latest_signal_time_ist": LATEST_SIGNAL_TIME.isoformat(),
        },
        "signal_definition": {
            "bullish": (
                "EMA5>EMA15 AND EMA5 slope3m>0 AND spot momentum5m>0 "
                "AND momentum15m>0 AND close breaks prior20m high AND "
                "1m move >=1.25x prior20m median absolute 1m move AND "
                "breakout is not overextended"
            ),
            "bearish": (
                "Exact mirror: EMA5<EMA15, negative slope/momentum, "
                "close breaks prior20m low, directional expansion, "
                "not overextended"
            ),
            "option_selection": (
                "Freeze exact moving-ATM CE for bullish or PE for bearish "
                "from strike_offset=0 positioning row at signal minute"
            ),
        },
        "leakage_guard": {
            "price_primary_signal": True,
            "pcr_used_for_signal": False,
            "pcr_recorded_as_diagnostic_context_only": True,
            "future_return_features_used": False,
            "forward_change_columns_used": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "all_features_at_or_before_signal": True,
            "signal_uses_current_and_backward_spot_only": True,
        },
        "limitations": [
            (
                "V1 uses evidence spot as a 1-minute close proxy. "
                "It does not yet use underlying candle open/high/low."
            ),
            (
                "This module generates signals only. It does not evaluate "
                "profitability or alter signal parameters using returns."
            ),
            (
                "PCR values are persisted only for later controlled comparison "
                "and never affect V1 signal eligibility."
            ),
        ],
        "signal_count": len(all_signals),
        "bullish_signal_count": sum(
            s.direction == "BULLISH" for s in all_signals
        ),
        "bearish_signal_count": sum(
            s.direction == "BEARISH" for s in all_signals
        ),
        "option_available_count": sum(
            s.option_selection_status == "AVAILABLE_EXACT_MOVING_ATM"
            for s in all_signals
        ),
        "block_summaries": block_summaries,
        "signals": [asdict(signal) for signal in all_signals],
    }

    output = Path(args.output)
    csv_output = Path(args.csv_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(all_signals, csv_output)

    print(
        json.dumps(
            {
                "status": payload["status"],
                "strategy_id": STRATEGY_ID,
                "research_status": payload["research_status"],
                "signal_count": payload["signal_count"],
                "bullish_signal_count": payload["bullish_signal_count"],
                "bearish_signal_count": payload["bearish_signal_count"],
                "option_available_count": payload["option_available_count"],
                "block_signal_counts": {
                    name: summary["signal_count"]
                    for name, summary in block_summaries.items()
                },
                "output": str(output),
                "csv_output": str(csv_output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
