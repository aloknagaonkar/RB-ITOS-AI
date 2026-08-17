from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import hashlib
import json

import pandas as pd


IST = "Asia/Kolkata"
SIGNAL_SOURCE = "RSI_EXTREME_REVERSAL_V1"


def _rsi(close: pd.Series, period: int = 7) -> pd.Series:
    """Exact Wilder RSI seeded with the first period simple average."""
    values = pd.to_numeric(close, errors="coerce").astype(float)
    delta = values.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    result = pd.Series(float("nan"), index=values.index, dtype=float)
    if len(values) <= period:
        return result

    average_gain = float(gain.iloc[1 : period + 1].mean())
    average_loss = float(loss.iloc[1 : period + 1].mean())

    def value(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0.0 and avg_gain > 0.0:
            return 100.0
        if avg_gain == 0.0 and avg_loss > 0.0:
            return 0.0
        if avg_gain == 0.0 and avg_loss == 0.0:
            return 50.0
        relative_strength = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    result.iloc[period] = value(average_gain, average_loss)
    for index in range(period + 1, len(values)):
        average_gain = (
            average_gain * (period - 1) + float(gain.iloc[index])
        ) / period
        average_loss = (
            average_loss * (period - 1) + float(loss.iloc[index])
        ) / period
        result.iloc[index] = value(average_gain, average_loss)
    return result


def _timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(IST)
    return timestamp.tz_convert(IST)


def _signal_id(instrument_key: str, direction: str, confirmed_at: pd.Timestamp) -> str:
    identity = f"{instrument_key}|{direction}|{confirmed_at.isoformat()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
    return f"RSI7-{digest}"


@dataclass(frozen=True)
class RsiExtremeReversalSignal:
    record: dict[str, object]

    def as_record(self) -> dict[str, object]:
        return dict(self.record)


class RsiExtremeReversalEngine:
    """1-minute RSI(7) 80/20 reversal with completed-candle structure confirmation."""

    def __init__(
        self,
        *,
        period: int = 7,
        oversold: float = 20.0,
        overbought: float = 80.0,
        arm_candles: int = 5,
    ):
        self.period = int(period)
        self.oversold = float(oversold)
        self.overbought = float(overbought)
        self.arm_candles = int(arm_candles)

    def detect(
        self,
        candles: pd.DataFrame,
        *,
        instrument_key: str,
    ) -> list[RsiExtremeReversalSignal]:
        required = {"timestamp", "open", "high", "low", "close"}
        if candles.empty or not required.issubset(candles.columns):
            return []

        frame = candles.copy()
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], errors="coerce", utc=True
        ).dt.tz_convert(IST)
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = (
            frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .reset_index(drop=True)
        )
        frame["rsi"] = _rsi(frame["close"], self.period)
        signals: list[RsiExtremeReversalSignal] = []
        ce_armed_at: int | None = None
        pe_armed_at: int | None = None

        for index in range(1, len(frame)):
            previous_rsi = frame.at[index - 1, "rsi"]
            current_rsi = frame.at[index, "rsi"]
            if pd.isna(previous_rsi) or pd.isna(current_rsi):
                continue

            if ce_armed_at is None and float(current_rsi) <= self.oversold:
                ce_armed_at = index
            if pe_armed_at is None and float(current_rsi) >= self.overbought:
                pe_armed_at = index

            if ce_armed_at is not None and index - ce_armed_at > self.arm_candles:
                ce_armed_at = None
            if pe_armed_at is not None and index - pe_armed_at > self.arm_candles:
                pe_armed_at = None

            current_open = float(frame.at[index, "open"])
            current_high = float(frame.at[index, "high"])
            current_low = float(frame.at[index, "low"])
            current_close = float(frame.at[index, "close"])
            previous_high = float(frame.at[index - 1, "high"])
            previous_low = float(frame.at[index - 1, "low"])

            bullish_candle = current_close > current_open
            bearish_candle = current_close < current_open
            bullish_structure_reclaim = current_close > previous_high
            bearish_structure_reclaim = current_close < previous_low
            fresh_lower_low = current_low < previous_low
            fresh_higher_high = current_high > previous_high

            if (
                ce_armed_at is not None
                and float(previous_rsi) <= self.oversold
                and float(current_rsi) > self.oversold
                and bullish_candle
                and bullish_structure_reclaim
                and not fresh_lower_low
            ):
                signals.append(
                    self._build(
                        frame,
                        index,
                        ce_armed_at,
                        "BULLISH",
                        instrument_key,
                        previous_high=previous_high,
                        previous_low=previous_low,
                    )
                )
                ce_armed_at = None

            if (
                pe_armed_at is not None
                and float(previous_rsi) >= self.overbought
                and float(current_rsi) < self.overbought
                and bearish_candle
                and bearish_structure_reclaim
                and not fresh_higher_high
            ):
                signals.append(
                    self._build(
                        frame,
                        index,
                        pe_armed_at,
                        "BEARISH",
                        instrument_key,
                        previous_high=previous_high,
                        previous_low=previous_low,
                    )
                )
                pe_armed_at = None

        return signals

    def _build(
        self,
        frame: pd.DataFrame,
        index: int,
        armed_index: int,
        direction: str,
        instrument_key: str,
        *,
        previous_high: float,
        previous_low: float,
    ) -> RsiExtremeReversalSignal:
        candle_open_at = _timestamp(frame.at[index, "timestamp"])
        confirmed_at = candle_open_at + pd.Timedelta(minutes=1)
        armed_at = _timestamp(frame.at[armed_index, "timestamp"])
        close = float(frame.at[index, "close"])
        low = float(frame.at[index, "low"])
        high = float(frame.at[index, "high"])
        bullish = direction == "BULLISH"
        record = {
            "signal_id": _signal_id(instrument_key, direction, confirmed_at),
            "direction": direction,
            "option_type": "CE" if bullish else "PE",
            "status": "ACTIVE",
            "state": "ACTIVE",
            "signal_source": SIGNAL_SOURCE,
            "source": SIGNAL_SOURCE,
            "signal_sources": [SIGNAL_SOURCE],
            "execution_strategy_source": SIGNAL_SOURCE,
            "source_count": 1,
            "merge_status": "SINGLE_SOURCE",
            "level_name": "RSI7_OVERSOLD_REVERSAL" if bullish else "RSI7_OVERBOUGHT_REVERSAL",
            "level_value": close,
            "trigger_level": close,
            "invalidation_level": low if bullish else high,
            "confirmation_high": high,
            "confirmation_low": low,
            "confirmation_close": close,
            "previous_candle_high": previous_high,
            "previous_candle_low": previous_low,
            "underlying_entry": close,
            "candle_a_high": high,
            "candle_a_low": low,
            "reference_price": close,
            "setup_timestamp": confirmed_at.isoformat(),
            "confirmation_timestamp": confirmed_at.isoformat(),
            "detected_at": confirmed_at.isoformat(),
            "fresh_until": (confirmed_at + pd.Timedelta(minutes=5)).isoformat(),
            "entry_ready_timestamp": confirmed_at.isoformat(),
            "rsi_period": self.period,
            "rsi_armed_value": float(frame.at[armed_index, "rsi"]),
            "rsi_confirmation_value": float(frame.at[index, "rsi"]),
            "rsi_armed_timestamp": armed_at.isoformat(),
            "rsi_arm_candles": self.arm_candles,
            "rsi_lifecycle_state": "REVERSAL_CONFIRMED",
            "rsi_extreme_detected": True,
            "rsi_crossback_confirmed": True,
            "candle_direction_confirmed": True,
            "structure_reclaim_confirmed": True,
            "fresh_extreme_rejected": False,
            "structure_confirmation_rule": (
                "CLOSE_ABOVE_PREVIOUS_HIGH_NO_FRESH_LOWER_LOW"
                if bullish
                else "CLOSE_BELOW_PREVIOUS_LOW_NO_FRESH_HIGHER_HIGH"
            ),
            "strategy_stop_loss_pct": 7.0,
            "fixed_profit_target": False,
            "evaluation_horizon_minutes": 15,
            "oi_support_status": "NOT_EVALUATED",
            "relative_volume_status": "OBSERVE_ONLY",
            "iv_status": "OBSERVE_ONLY",
            "pcr_status": "OBSERVE_ONLY",
            "greeks_status": "OBSERVE_ONLY",
            "native_execution_adapter": True,
            "execution_allowed": True,
        }
        return RsiExtremeReversalSignal(record)


def append_rsi_signals_once(path: str | Path, signals: list[Mapping[str, object]]) -> int:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if destination.exists():
        for line in destination.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            existing.add(str(row.get("signal_id") or ""))

    new_rows = [dict(row) for row in signals if str(row.get("signal_id") or "") not in existing]
    if not new_rows:
        return 0
    with destination.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    return len(new_rows)
