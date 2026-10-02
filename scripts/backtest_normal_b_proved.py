#!/usr/bin/env python3
"""Causal backtest for the NORMAL_B_PROVED three-tier exit candidate.

The script is research-only. It does not import broker, order, paper-trading,
or live-runtime modules. Input rows must be exact, contiguous one-minute bars
beginning one minute after the trade entry candle.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd


Direction = Literal["BULLISH", "BEARISH"]
REQUIRED_COLUMNS = (
    "Timestamp",
    "Open",
    "High",
    "Low",
    "Close",
    "Intrabar_MFE",
)


@dataclass(frozen=True)
class BacktestConfig:
    """Frozen NORMAL_B_PROVED policy parameters."""

    primary_target_points: float = 50.0
    tier2_mfe_points: float = 30.0
    tier2_floor_points: float = 15.0
    tier3_mfe_points: float = 45.0
    tier3_ratchet_offset_points: float = 10.0
    inactivity_minutes: int = 30

    def __post_init__(self) -> None:
        point_values = (
            self.primary_target_points,
            self.tier2_mfe_points,
            self.tier2_floor_points,
            self.tier3_mfe_points,
            self.tier3_ratchet_offset_points,
        )
        if not all(np.isfinite(value) and value > 0 for value in point_values):
            raise ValueError("All point parameters must be finite and positive")
        if not (
            self.tier2_floor_points
            < self.tier2_mfe_points
            < self.tier3_mfe_points
            < self.primary_target_points
        ):
            raise ValueError(
                "Require Tier-2 floor < Tier-2 MFE < Tier-3 MFE < target"
            )
        if self.inactivity_minutes <= 0:
            raise ValueError("inactivity_minutes must be positive")


@dataclass(frozen=True)
class BacktestResult:
    """Serializable outcome for one trade."""

    status: str
    direction: str
    entry_timestamp: str
    activation_timestamp: str
    entry_price: float
    midpoint_price: float
    exit_timestamp: str | None
    exit_trigger: str
    exit_price: float | None
    total_captured_points: float | None
    raw_exit_minus_entry: float | None
    max_favourable_excursion: float
    active_floor_points: float | None
    highest_closed_profit_tier3: float | None
    valuation_basis: str | None
    bars_evaluated: int
    policy: dict[str, float | int]
    final_mark_timestamp: str
    final_mark_price: float
    final_mark_directional_points: float
    observation_only: bool = True
    execution_enabled: bool = False
    paper_order_enabled: bool = False
    quantity: None = None
    order_sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _exact_aware_minute(value: Any, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    if timestamp.second or timestamp.microsecond or timestamp.nanosecond:
        raise ValueError(f"{field} must be an exact minute")
    return timestamp


def _prepare_input(
    frame: pd.DataFrame,
    *,
    entry_timestamp: Any,
    activation_timestamp: Any,
    entry_price: float,
    midpoint_price: float,
    direction: Direction,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, int]:
    """Validate input and calculate causal directional features."""

    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError("direction must be BULLISH or BEARISH")
    if not np.isfinite(entry_price) or not np.isfinite(midpoint_price):
        raise ValueError("entry_price and midpoint_price must be finite")

    entry_at = _exact_aware_minute(entry_timestamp, "entry_timestamp")
    activation_at = _exact_aware_minute(
        activation_timestamp, "activation_timestamp"
    )
    if activation_at <= entry_at:
        raise ValueError("activation_timestamp must be after entry_timestamp")

    output = frame.loc[:, REQUIRED_COLUMNS].copy()
    output["Timestamp"] = pd.to_datetime(output["Timestamp"], errors="raise")
    if output["Timestamp"].dt.tz is None:
        raise ValueError("All candle timestamps must be timezone-aware")
    if output.empty:
        raise ValueError("At least one post-entry candle is required")
    if output["Timestamp"].duplicated().any():
        raise ValueError("Duplicate candle timestamps are not allowed")
    if not output["Timestamp"].is_monotonic_increasing:
        raise ValueError("Candles must be sorted in ascending timestamp order")
    one_minute = pd.Timedelta("1min")
    if output["Timestamp"].iloc[0] != entry_at + one_minute:
        raise ValueError("First candle must be exactly entry_timestamp + 1 minute")
    differences = output["Timestamp"].diff().iloc[1:]
    if not differences.eq(one_minute).all():
        raise ValueError("Candles must be contiguous exact one-minute rows")

    numeric_columns = ["Open", "High", "Low", "Close", "Intrabar_MFE"]
    output[numeric_columns] = output[numeric_columns].apply(
        pd.to_numeric, errors="raise"
    )
    values = output[numeric_columns].to_numpy(dtype=np.float64, copy=True)
    if not np.isfinite(values).all():
        raise ValueError("OHLC and Intrabar_MFE values must be finite")
    open_price, high, low, close, supplied_mfe = values.T
    if np.any(low > high):
        raise ValueError("Low cannot exceed High")
    if np.any(low > np.minimum(open_price, close)):
        raise ValueError("Low cannot exceed Open or Close")
    if np.any(high < np.maximum(open_price, close)):
        raise ValueError("High cannot be below Open or Close")

    activation_matches = np.flatnonzero(
        output["Timestamp"].eq(activation_at).to_numpy()
    )
    if len(activation_matches) != 1:
        raise ValueError("activation_timestamp must match exactly one candle")
    activation_index = int(activation_matches[0])

    sign = 1.0 if direction == "BULLISH" else -1.0
    favourable_price = high if direction == "BULLISH" else low
    bar_excursion = sign * (favourable_price - float(entry_price))
    causal_mfe = np.maximum.accumulate(np.maximum(bar_excursion, 0.0))
    if not np.allclose(supplied_mfe, causal_mfe, rtol=0.0, atol=1e-7):
        mismatch = int(np.flatnonzero(~np.isclose(
            supplied_mfe, causal_mfe, rtol=0.0, atol=1e-7
        ))[0])
        timestamp = output["Timestamp"].iloc[mismatch].isoformat()
        raise ValueError(
            "Intrabar_MFE disagrees with causal OHLC at "
            f"{timestamp}: supplied={supplied_mfe[mismatch]}, "
            f"computed={causal_mfe[mismatch]}"
        )

    output["Directional_Close_Points"] = sign * (close - float(entry_price))
    output["Bar_Excursion_Points"] = bar_excursion
    output["Computed_MFE"] = causal_mfe
    return output, entry_at, activation_at, activation_index


def backtest_normal_b_proved(
    frame: pd.DataFrame,
    *,
    entry_timestamp: Any,
    activation_timestamp: Any,
    entry_price: float,
    midpoint_price: float,
    direction: Direction,
    config: BacktestConfig | None = None,
) -> tuple[BacktestResult, pd.DataFrame]:
    """Backtest one already-classified NORMAL_B_PROVED trade.

    The activation candle is evidence used to enter the state at its close.
    Exit rules therefore start on the following completed minute, preventing a
    target or floor from being filled retroactively on the classifier candle.

    Returns the immutable summary and a causal per-minute audit trace.
    """

    policy = config or BacktestConfig()
    data, entry_at, activation_at, activation_index = _prepare_input(
        frame,
        entry_timestamp=entry_timestamp,
        activation_timestamp=activation_timestamp,
        entry_price=entry_price,
        midpoint_price=midpoint_price,
        direction=direction,
    )

    timestamps = data["Timestamp"].array
    high = data["High"].to_numpy(dtype=np.float64, copy=False)
    low = data["Low"].to_numpy(dtype=np.float64, copy=False)
    close = data["Close"].to_numpy(dtype=np.float64, copy=False)
    close_points = data["Directional_Close_Points"].to_numpy(
        dtype=np.float64, copy=False
    )
    excursion = data["Bar_Excursion_Points"].to_numpy(
        dtype=np.float64, copy=False
    )
    running_mfe = data["Computed_MFE"].to_numpy(dtype=np.float64, copy=False)

    count = len(data)
    states = np.full(count, "PRE_ACTIVATION", dtype=object)
    floors = np.full(count, np.nan, dtype=np.float64)
    tier3_high_close = np.full(count, np.nan, dtype=np.float64)
    inactivity_due = np.full(count, None, dtype=object)
    triggers = np.full(count, "", dtype=object)

    state = "NORMAL_B_PROVED"
    floor: float | None = None
    highest_tier3_close: float | None = None
    last_mfe_at = activation_at
    prior_mfe = float(running_mfe[activation_index])
    scheduled_time_exit: pd.Timestamp | None = None
    exit_index: int | None = None
    exit_trigger = "NO_EXIT"
    exit_price: float | None = None
    captured_points: float | None = None
    valuation_basis: str | None = None
    sign = 1.0 if direction == "BULLISH" else -1.0

    states[activation_index] = state
    for index in range(activation_index + 1, count):
        timestamp = pd.Timestamp(timestamps[index])
        current_mfe = float(running_mfe[index])
        if current_mfe > prior_mfe:
            last_mfe_at = timestamp
            prior_mfe = current_mfe

        # Target has first priority because it is an intrabar resting target.
        if excursion[index] >= policy.primary_target_points:
            exit_index = index
            exit_trigger = "Target_Hit"
            captured_points = policy.primary_target_points
            exit_price = float(entry_price + sign * captured_points)
            valuation_basis = "ASSUMED_EXACT_TARGET_FILL"
        else:
            midpoint_invalidated = (
                close[index] < midpoint_price
                if direction == "BULLISH"
                else close[index] > midpoint_price
            )
            if midpoint_invalidated:
                exit_index = index
                exit_trigger = "Midpoint_Invalidation"
                exit_price = float(close[index])
                captured_points = float(close_points[index])
                valuation_basis = "OBSERVED_CANDLE_CLOSE"
            elif scheduled_time_exit is not None and timestamp == scheduled_time_exit:
                exit_index = index
                exit_trigger = "Time_Stop"
                exit_price = float(close[index])
                captured_points = float(close_points[index])
                valuation_basis = "OBSERVED_CANDLE_CLOSE"

        if exit_index is None:
            if current_mfe > policy.tier3_mfe_points:
                state = "NORMAL_B_PROVED_TIER3"
                highest_tier3_close = max(
                    close_points[index]
                    if highest_tier3_close is None
                    else highest_tier3_close,
                    float(close_points[index]),
                )
                ratchet = (
                    highest_tier3_close - policy.tier3_ratchet_offset_points
                )
                floor = max(
                    policy.tier2_floor_points,
                    ratchet,
                    policy.tier2_floor_points if floor is None else floor,
                )
            elif current_mfe > policy.tier2_mfe_points:
                state = "NORMAL_B_PROVED_TIER2"
                floor = policy.tier2_floor_points

            if floor is not None and close_points[index] < floor:
                exit_index = index
                exit_trigger = (
                    "Floor_Breach_Tier3"
                    if state == "NORMAL_B_PROVED_TIER3"
                    else "Floor_Breach_Tier2"
                )
                exit_price = float(close[index])
                captured_points = float(close_points[index])
                valuation_basis = "OBSERVED_CANDLE_CLOSE"

        if exit_index is None and scheduled_time_exit is None:
            elapsed_without_peak = timestamp - last_mfe_at
            inactivity_period = pd.Timedelta(
                f"{policy.inactivity_minutes}min"
            )
            if elapsed_without_peak >= inactivity_period:
                scheduled_time_exit = timestamp + pd.Timedelta("1min")

        states[index] = "CLOSED" if exit_index == index else state
        floors[index] = np.nan if floor is None else floor
        tier3_high_close[index] = (
            np.nan if highest_tier3_close is None else highest_tier3_close
        )
        inactivity_due[index] = (
            None if scheduled_time_exit is None else scheduled_time_exit.isoformat()
        )
        if exit_index == index:
            triggers[index] = exit_trigger
            break

    final_index = exit_index if exit_index is not None else count - 1
    trace = data.iloc[: final_index + 1].copy()
    trace["Candidate_State"] = states[: final_index + 1]
    trace["Active_Floor_Points"] = floors[: final_index + 1]
    trace["Highest_Closed_Profit_Tier3"] = tier3_high_close[: final_index + 1]
    trace["Inactivity_Exit_Due"] = inactivity_due[: final_index + 1]
    trace["Exit_Trigger"] = triggers[: final_index + 1]

    exit_timestamp = (
        None
        if exit_index is None
        else pd.Timestamp(timestamps[exit_index]).isoformat()
    )
    final_timestamp = pd.Timestamp(timestamps[final_index]).isoformat()
    raw_change = None if exit_price is None else float(exit_price - entry_price)
    result = BacktestResult(
        status="CLOSED" if exit_index is not None else "OPEN",
        direction=direction,
        entry_timestamp=entry_at.isoformat(),
        activation_timestamp=activation_at.isoformat(),
        entry_price=float(entry_price),
        midpoint_price=float(midpoint_price),
        exit_timestamp=exit_timestamp,
        exit_trigger=exit_trigger,
        exit_price=exit_price,
        total_captured_points=captured_points,
        raw_exit_minus_entry=raw_change,
        max_favourable_excursion=float(running_mfe[final_index]),
        active_floor_points=None if floor is None else float(floor),
        highest_closed_profit_tier3=(
            None
            if highest_tier3_close is None
            else float(highest_tier3_close)
        ),
        valuation_basis=valuation_basis,
        bars_evaluated=final_index + 1,
        policy=asdict(policy),
        final_mark_timestamp=final_timestamp,
        final_mark_price=float(close[final_index]),
        final_mark_directional_points=float(close_points[final_index]),
    )
    _assert_causal_trace(trace, result, policy)
    return result, trace


def _assert_causal_trace(
    trace: pd.DataFrame,
    result: BacktestResult,
    config: BacktestConfig,
) -> None:
    """Fail closed if the generated path violates policy invariants."""

    floors = trace["Active_Floor_Points"].dropna().to_numpy(dtype=float)
    if len(floors) > 1 and np.any(np.diff(floors) < -1e-12):
        raise AssertionError("Active floor decreased; ratchet invariant violated")
    tier3 = trace["Candidate_State"].isin(
        ("NORMAL_B_PROVED_TIER3", "CLOSED")
    ) & trace["Highest_Closed_Profit_Tier3"].notna()
    if tier3.any():
        expected_minimum = (
            trace.loc[tier3, "Highest_Closed_Profit_Tier3"]
            - config.tier3_ratchet_offset_points
        )
        observed = trace.loc[tier3, "Active_Floor_Points"]
        if (observed + 1e-12 < expected_minimum).any():
            raise AssertionError("Tier-3 floor is below its causal ratchet")
    if result.exit_trigger.startswith("Floor_Breach"):
        last = trace.iloc[-1]
        if not last["Directional_Close_Points"] < last["Active_Floor_Points"]:
            raise AssertionError("Floor exit was not triggered by actual close")
        if result.exit_price != float(last["Close"]):
            raise AssertionError("Floor exit price must equal triggering close")
    if result.exit_trigger == "Target_Hit":
        if result.total_captured_points != config.primary_target_points:
            raise AssertionError("Target exit must capture the exact target")


def _read_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in (".parquet", ".pq"):
        return pd.read_parquet(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError("Input must be CSV, JSON, Parquet, or PQ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--entry-timestamp", required=True)
    parser.add_argument("--activation-timestamp", required=True)
    parser.add_argument("--entry-price", required=True, type=float)
    parser.add_argument("--midpoint-price", required=True, type=float)
    parser.add_argument(
        "--direction", required=True, choices=("BULLISH", "BEARISH")
    )
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--trace-output", type=Path)
    arguments = parser.parse_args()

    result, trace = backtest_normal_b_proved(
        _read_frame(arguments.input),
        entry_timestamp=arguments.entry_timestamp,
        activation_timestamp=arguments.activation_timestamp,
        entry_price=arguments.entry_price,
        midpoint_price=arguments.midpoint_price,
        direction=arguments.direction,
    )
    summary = result.to_dict()
    rendered = json.dumps(summary, indent=2)
    print(rendered)
    if arguments.summary_output:
        arguments.summary_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.summary_output.write_text(rendered + "\n", encoding="utf-8")
    if arguments.trace_output:
        arguments.trace_output.parent.mkdir(parents=True, exist_ok=True)
        trace.to_csv(arguments.trace_output, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
