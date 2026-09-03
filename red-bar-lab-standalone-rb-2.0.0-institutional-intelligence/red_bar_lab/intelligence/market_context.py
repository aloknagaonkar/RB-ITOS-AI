from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd


Timeframe = Literal["1M", "5M"]


@dataclass(frozen=True)
class MarketIndicatorSnapshot:
    instrument_key: str
    trading_date: str
    timeframe: Timeframe
    candle_timestamp: datetime
    candle_open: float
    candle_high: float
    candle_low: float
    candle_close: float
    candle_volume: float
    rsi_period: int
    rsi_value: float | None
    vwap_value: float | None
    price_vs_vwap: str
    rsi_state: str | None
    source: str
    data_quality: str
    fresh: bool

    def to_storage_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["candle_timestamp"] = self.candle_timestamp.isoformat()
        return payload


RSI_BULLISH_THRESHOLD = 55.0
RSI_BEARISH_THRESHOLD = 45.0


def rsi_alignment_state(
    rsi_value: float | None,
    *,
    bullish_threshold: float = RSI_BULLISH_THRESHOLD,
    bearish_threshold: float = RSI_BEARISH_THRESHOLD,
) -> str | None:
    """Classify an RSI reading as BULLISH, BEARISH or NEUTRAL.

    Informational only. RSI does not gate Red Bar V2 admission -- direction is
    decided by the Red Bar reference and the futures VWAP. ``None`` means no
    reading exists yet: Wilder RSI(14) is NaN until 15 candles have completed,
    so the 1-minute timeframe has no value before 09:30 IST and the 5-minute
    timeframe none before 10:30.

    This replaces the former ``bullish_context``/``bearish_context`` pair, which
    silently bundled RSI with the VWAP comparison and so could not be read as a
    statement about RSI at all.
    """
    if rsi_value is None:
        return None
    if rsi_value > bullish_threshold:
        return "BULLISH"
    if rsi_value < bearish_threshold:
        return "BEARISH"
    return "NEUTRAL"


class MarketContextError(ValueError):
    """Raised when candle input cannot produce trustworthy market context."""


def _normalise_candles(candles: pd.DataFrame) -> pd.DataFrame:
    if candles.empty:
        raise MarketContextError("Candle frame is empty.")

    frame = candles.copy()
    if "timestamp" in frame.columns:
        timestamps = pd.to_datetime(frame.pop("timestamp"), errors="coerce")
        frame.index = pd.DatetimeIndex(timestamps)
    elif not isinstance(frame.index, pd.DatetimeIndex):
        raise MarketContextError(
            "Candles require a DatetimeIndex or a timestamp column."
        )

    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise MarketContextError(
            f"Candles are missing required columns: {', '.join(missing)}"
        )

    frame = frame.loc[~frame.index.isna(), list(required)].copy()
    frame = frame.rename_axis("timestamp").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    if frame.empty:
        raise MarketContextError("No valid OHLCV candles remain after normalisation.")
    return frame


def completed_candles(
    candles: pd.DataFrame,
    *,
    evaluation_time: datetime | pd.Timestamp,
    interval_minutes: int = 1,
) -> pd.DataFrame:
    """Return candles whose full interval has completed by evaluation_time."""
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")
    frame = _normalise_candles(candles)
    evaluated_at = pd.Timestamp(evaluation_time)
    if frame.index.tz is not None and evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.tz_localize(frame.index.tz)
    elif frame.index.tz is None and evaluated_at.tzinfo is not None:
        evaluated_at = evaluated_at.tz_localize(None)
    close_times = frame.index + pd.Timedelta(minutes=interval_minutes)
    return frame.loc[close_times <= evaluated_at].copy()


def aggregate_completed_5m(one_minute_candles: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only complete five-row 1-minute groups into 5-minute candles."""
    frame = _normalise_candles(one_minute_candles)
    grouped = frame.resample("5min", origin="start_day", offset="15min")
    aggregated = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_rows=("close", "count"),
    )
    aggregated = aggregated.loc[aggregated["source_rows"] == 5].copy()
    return aggregated.drop(columns=["source_rows"])


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate deterministic Wilder RSI without external TA dependencies."""
    if period <= 0:
        raise ValueError("RSI period must be positive")
    values = pd.to_numeric(close, errors="coerce").astype(float)
    delta = values.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)

    result = pd.Series(np.nan, index=values.index, dtype=float)
    if len(values) <= period:
        return result

    avg_gain = gains.iloc[1 : period + 1].mean()
    avg_loss = losses.iloc[1 : period + 1].mean()

    def _value(gain: float, loss: float) -> float:
        if loss == 0.0 and gain == 0.0:
            return 50.0
        if loss == 0.0:
            return 100.0
        if gain == 0.0:
            return 0.0
        relative_strength = gain / loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    result.iloc[period] = _value(float(avg_gain), float(avg_loss))
    for position in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains.iloc[position]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses.iloc[position]) / period
        result.iloc[position] = _value(float(avg_gain), float(avg_loss))
    return result


def session_vwap(candles: pd.DataFrame) -> pd.Series:
    """Calculate typical-price VWAP, resetting at each trading date."""
    frame = _normalise_candles(candles)
    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    weighted = typical_price * frame["volume"]
    session_key = pd.Series(frame.index.date, index=frame.index)
    cumulative_volume = frame["volume"].groupby(session_key).cumsum()
    cumulative_weighted = weighted.groupby(session_key).cumsum()
    return cumulative_weighted.div(cumulative_volume.replace(0.0, np.nan))


def add_market_indicators(
    candles: pd.DataFrame,
    *,
    rsi_period: int = 14,
) -> pd.DataFrame:
    frame = _normalise_candles(candles)
    frame["rsi"] = wilder_rsi(frame["close"], period=rsi_period)
    frame["vwap"] = session_vwap(frame)
    return frame


def build_latest_snapshot(
    candles: pd.DataFrame,
    *,
    instrument_key: str,
    timeframe: Timeframe,
    evaluation_time: datetime | pd.Timestamp,
    expected_timestamp: datetime | pd.Timestamp | None = None,
    rsi_period: int = 14,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
    source: str = "MARKET_CONTEXT_ENGINE_V1",
) -> MarketIndicatorSnapshot | None:
    """Build the latest trustworthy completed-candle RSI/VWAP snapshot.

    For 1M input, only completed 1-minute candles are considered. For 5M,
    completed 1-minute candles are first aggregated and incomplete five-minute
    groups are discarded.
    """
    completed_1m = completed_candles(
        candles, evaluation_time=evaluation_time, interval_minutes=1
    )
    if completed_1m.empty:
        return None

    if timeframe == "1M":
        context_frame = completed_1m
    elif timeframe == "5M":
        context_frame = aggregate_completed_5m(completed_1m)
    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    if context_frame.empty:
        return None

    enriched = add_market_indicators(context_frame, rsi_period=rsi_period)
    latest = enriched.iloc[-1]
    timestamp = pd.Timestamp(enriched.index[-1])

    expected = pd.Timestamp(expected_timestamp) if expected_timestamp is not None else None
    if expected is not None:
        if timestamp.tzinfo is not None and expected.tzinfo is None:
            expected = expected.tz_localize(timestamp.tzinfo)
        elif timestamp.tzinfo is None and expected.tzinfo is not None:
            expected = expected.tz_localize(None)
    fresh = expected is None or timestamp == expected

    rsi_value = None if pd.isna(latest["rsi"]) else float(latest["rsi"])
    vwap_value = None if pd.isna(latest["vwap"]) else float(latest["vwap"])
    close = float(latest["close"])

    if not fresh:
        data_quality = "STALE_CONTEXT"
    elif rsi_value is None:
        data_quality = "INSUFFICIENT_RSI_HISTORY"
    elif vwap_value is None:
        data_quality = "VWAP_UNAVAILABLE"
    else:
        data_quality = "VALID"

    if vwap_value is None:
        price_vs_vwap = "UNAVAILABLE"
    elif close > vwap_value:
        price_vs_vwap = "ABOVE"
    elif close < vwap_value:
        price_vs_vwap = "BELOW"
    else:
        price_vs_vwap = "AT"

    candle_datetime = timestamp.to_pydatetime()
    return MarketIndicatorSnapshot(
        instrument_key=instrument_key,
        trading_date=candle_datetime.date().isoformat(),
        timeframe=timeframe,
        candle_timestamp=candle_datetime,
        candle_open=float(latest["open"]),
        candle_high=float(latest["high"]),
        candle_low=float(latest["low"]),
        candle_close=close,
        candle_volume=float(latest["volume"]),
        rsi_period=rsi_period,
        rsi_value=rsi_value,
        vwap_value=vwap_value,
        price_vs_vwap=price_vs_vwap,
        rsi_state=rsi_alignment_state(
            rsi_value,
            bullish_threshold=bullish_threshold,
            bearish_threshold=bearish_threshold,
        ),
        source=source,
        data_quality=data_quality,
        fresh=fresh,
    )
