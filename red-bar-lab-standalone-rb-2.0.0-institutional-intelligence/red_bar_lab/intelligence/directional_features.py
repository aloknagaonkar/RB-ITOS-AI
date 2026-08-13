from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class DirectionalFeatureSnapshot:
    timestamp: pd.Timestamp
    close: float
    ema_fast: float
    ema_slow: float
    ema_fast_slope_atr: float
    ema_slow_slope_atr: float
    ema_fast_acceleration_atr: float
    ema_spread_atr: float
    plus_di: float
    minus_di: float
    adx: float
    adx_slope: float
    atr: float
    displacement_atr: float
    range_atr: float
    compression_ratio: float
    recent_swing_high: float
    recent_swing_low: float
    bullish_structure: bool
    bearish_structure: bool
    breakout: bool
    breakdown: bool
    price_above_fast: bool
    price_above_slow: bool
    volume_ratio: float

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("Directional features require non-empty completed candle data.")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required candle columns: {', '.join(missing)}")

    result = frame.loc[:, REQUIRED_COLUMNS].copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = (
        result.dropna(subset=REQUIRED_COLUMNS)
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
    if result.empty:
        raise ValueError("No valid completed candles are available.")
    return result


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def build_directional_feature_frame(
    frame: pd.DataFrame,
    *,
    ema_fast_period: int = 10,
    ema_slow_period: int = 30,
    atr_period: int = 14,
    dmi_period: int = 14,
    swing_lookback: int = 5,
    compression_lookback: int = 10,
    displacement_periods: int = 3,
) -> pd.DataFrame:
    """Build deterministic, execution-independent directional features.

    Input must contain completed candles only. The function does not fetch data,
    infer unfinished bars, create Red Bar signals, or place trades.
    """
    source = _validated_frame(frame)
    if min(
        ema_fast_period,
        ema_slow_period,
        atr_period,
        dmi_period,
        swing_lookback,
        compression_lookback,
        displacement_periods,
    ) <= 0:
        raise ValueError("All feature periods must be positive.")

    high = source["high"]
    low = source["low"]
    close = source["close"]
    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = _wilder(true_range, atr_period).replace(0.0, np.nan)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=source.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=source.index,
        dtype=float,
    )
    plus_di = 100.0 * _wilder(plus_dm, dmi_period) / atr
    minus_di = 100.0 * _wilder(minus_dm, dmi_period) / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = _wilder(dx, dmi_period)

    ema_fast = close.ewm(span=ema_fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=ema_slow_period, adjust=False).mean()

    previous_swing_high = high.shift(1).rolling(swing_lookback, min_periods=swing_lookback).max()
    previous_swing_low = low.shift(1).rolling(swing_lookback, min_periods=swing_lookback).min()

    candle_range = high - low
    normal_range = candle_range.shift(1).rolling(
        compression_lookback, min_periods=compression_lookback
    ).mean()

    volume_mean = source["volume"].shift(1).rolling(
        compression_lookback, min_periods=compression_lookback
    ).mean()

    output = source.copy()
    output["atr"] = atr
    output["ema_fast"] = ema_fast
    output["ema_slow"] = ema_slow
    output["ema_fast_slope_atr"] = ema_fast.diff() / atr
    output["ema_slow_slope_atr"] = ema_slow.diff() / atr
    output["ema_fast_acceleration_atr"] = output["ema_fast_slope_atr"].diff()
    output["ema_spread_atr"] = (ema_fast - ema_slow) / atr
    output["plus_di"] = plus_di
    output["minus_di"] = minus_di
    output["adx"] = adx
    output["adx_slope"] = adx.diff()
    output["displacement_atr"] = (close - close.shift(displacement_periods)) / atr
    output["range_atr"] = candle_range / atr
    output["compression_ratio"] = candle_range / normal_range.replace(0.0, np.nan)
    output["recent_swing_high"] = previous_swing_high
    output["recent_swing_low"] = previous_swing_low
    output["breakout"] = close > previous_swing_high
    output["breakdown"] = close < previous_swing_low

    prior_high = high.shift(1)
    prior_low = low.shift(1)
    earlier_high = high.shift(2)
    earlier_low = low.shift(2)
    output["bullish_structure"] = (prior_high > earlier_high) & (prior_low > earlier_low)
    output["bearish_structure"] = (prior_high < earlier_high) & (prior_low < earlier_low)
    output["price_above_fast"] = close > ema_fast
    output["price_above_slow"] = close > ema_slow
    output["volume_ratio"] = source["volume"] / volume_mean.replace(0.0, np.nan)
    return output


def latest_directional_features(
    frame: pd.DataFrame,
    **kwargs: object,
) -> DirectionalFeatureSnapshot:
    feature_frame = build_directional_feature_frame(frame, **kwargs)
    row = feature_frame.iloc[-1]
    required = (
        "atr",
        "ema_fast_slope_atr",
        "ema_slow_slope_atr",
        "ema_fast_acceleration_atr",
        "ema_spread_atr",
        "plus_di",
        "minus_di",
        "adx",
        "adx_slope",
        "displacement_atr",
        "range_atr",
        "compression_ratio",
        "recent_swing_high",
        "recent_swing_low",
        "volume_ratio",
    )
    missing = [name for name in required if pd.isna(row[name])]
    if missing:
        raise ValueError(
            "Insufficient completed candle history for directional features: "
            + ", ".join(missing)
        )

    return DirectionalFeatureSnapshot(
        timestamp=pd.Timestamp(row["timestamp"]),
        close=float(row["close"]),
        ema_fast=float(row["ema_fast"]),
        ema_slow=float(row["ema_slow"]),
        ema_fast_slope_atr=float(row["ema_fast_slope_atr"]),
        ema_slow_slope_atr=float(row["ema_slow_slope_atr"]),
        ema_fast_acceleration_atr=float(row["ema_fast_acceleration_atr"]),
        ema_spread_atr=float(row["ema_spread_atr"]),
        plus_di=float(row["plus_di"]),
        minus_di=float(row["minus_di"]),
        adx=float(row["adx"]),
        adx_slope=float(row["adx_slope"]),
        atr=float(row["atr"]),
        displacement_atr=float(row["displacement_atr"]),
        range_atr=float(row["range_atr"]),
        compression_ratio=float(row["compression_ratio"]),
        recent_swing_high=float(row["recent_swing_high"]),
        recent_swing_low=float(row["recent_swing_low"]),
        bullish_structure=bool(row["bullish_structure"]),
        bearish_structure=bool(row["bearish_structure"]),
        breakout=bool(row["breakout"]),
        breakdown=bool(row["breakdown"]),
        price_above_fast=bool(row["price_above_fast"]),
        price_above_slow=bool(row["price_above_slow"]),
        volume_ratio=float(row["volume_ratio"]),
    )
