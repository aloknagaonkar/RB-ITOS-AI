from __future__ import annotations

from pathlib import Path

import pandas as pd

IST = "Asia/Kolkata"

VOLUME_STRUCTURE_COLUMNS = (
    "signal_id",
    "instrument_key",
    "trading_date",
    "entry_timestamp",
    "volume_current_1m",
    "volume_avg_20m",
    "relative_volume_20m",
    "volume_trend_5m",
    "price_volume_state",
    "compression_ratio_20m",
    "structure_state",
    "breakout_strength",
    "range_width_20m",
    "higher_high_count_20m",
    "lower_low_count_20m",
    "bullish_structure_score",
    "bearish_structure_score",
)


def _to_ist(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=("timestamp", "open", "high", "low", "close", "volume")
        )
    result = frame.copy()
    ts = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.loc[ts.notna()].copy()
    result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
    return (
        result.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _volume_context(frame: pd.DataFrame):
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    current = float(volume.iloc[-1]) if len(volume) else None
    avg20 = float(volume.tail(20).mean()) if len(volume) else None
    rvol = (
        current / avg20
        if current is not None and avg20 not in (None, 0.0)
        else None
    )

    if len(volume) < 10:
        trend = "UNKNOWN"
    else:
        first = float(volume.tail(10).head(5).mean())
        second = float(volume.tail(10).tail(5).mean())
        if second > first * 1.15:
            trend = "RISING"
        elif second < first * 0.85:
            trend = "FALLING"
        else:
            trend = "STABLE"

    return current, avg20, rvol, trend


def _price_volume_state(frame: pd.DataFrame) -> str:
    if len(frame) < 10:
        return "UNKNOWN"

    recent = frame.tail(10)
    price_change = float(recent["close"].iloc[-1]) - float(
        recent["close"].iloc[0]
    )
    volume = pd.to_numeric(
        recent["volume"], errors="coerce"
    ).fillna(0.0)
    first = float(volume.head(5).mean())
    last = float(volume.tail(5).mean())

    rising = last > first * 1.10
    falling = last < first * 0.90

    if price_change > 0 and rising:
        return "BULLISH_ACCUMULATION"
    if price_change < 0 and rising:
        return "BEARISH_DISTRIBUTION"
    if price_change > 0 and falling:
        return "WEAK_RALLY"
    if price_change < 0 and falling:
        return "WEAK_DECLINE"
    return "NEUTRAL"


def _structure(frame: pd.DataFrame) -> dict[str, object]:
    if len(frame) < 20:
        return {
            "compression_ratio_20m": None,
            "structure_state": "UNKNOWN",
            "breakout_strength": None,
            "range_width_20m": None,
            "higher_high_count_20m": 0,
            "lower_low_count_20m": 0,
            "bullish_structure_score": 0.0,
            "bearish_structure_score": 0.0,
        }

    recent = frame.tail(20).copy()
    highs = pd.to_numeric(recent["high"], errors="coerce")
    lows = pd.to_numeric(recent["low"], errors="coerce")
    closes = pd.to_numeric(recent["close"], errors="coerce")

    range20 = float(highs.max() - lows.min())
    first10 = recent.head(10)
    last10 = recent.tail(10)
    first_range = float(
        first10["high"].max() - first10["low"].min()
    )
    last_range = float(
        last10["high"].max() - last10["low"].min()
    )

    compression_ratio = (
        last_range / first_range if first_range > 0 else None
    )

    if compression_ratio is None:
        state = "UNKNOWN"
    elif compression_ratio <= 0.65:
        state = "COMPRESSION"
    elif compression_ratio >= 1.35:
        state = "EXPANSION"
    else:
        state = "RANGE"

    higher_highs = int((highs.diff() > 0).sum())
    lower_lows = int((lows.diff() < 0).sum())
    denominator = max(1, len(recent) - 1)
    bullish_score = higher_highs / denominator
    bearish_score = lower_lows / denominator

    prior_high = float(recent.iloc[:-1]["high"].max())
    prior_low = float(recent.iloc[:-1]["low"].min())
    last_close = float(closes.iloc[-1])

    breakout_strength = 0.0
    if range20 > 0 and last_close > prior_high:
        breakout_strength = (last_close - prior_high) / range20
        state = "BULLISH_BREAKOUT"
    elif range20 > 0 and last_close < prior_low:
        breakout_strength = (prior_low - last_close) / range20
        state = "BEARISH_BREAKOUT"

    return {
        "compression_ratio_20m": compression_ratio,
        "structure_state": state,
        "breakout_strength": breakout_strength,
        "range_width_20m": range20,
        "higher_high_count_20m": higher_highs,
        "lower_low_count_20m": lower_lows,
        "bullish_structure_score": bullish_score,
        "bearish_structure_score": bearish_score,
    }


def build_volume_structure_snapshot(
    *,
    signal: dict[str, object],
    instrument_key: str,
    current_day: pd.DataFrame,
) -> dict[str, object]:
    entry_ts = pd.Timestamp(signal["confirmation_timestamp"])
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize(IST)
    else:
        entry_ts = entry_ts.tz_convert(IST)

    current = _to_ist(current_day)
    current = current[
        current["timestamp"] <= entry_ts
    ].reset_index(drop=True)

    if current.empty:
        raise ValueError("No pre-entry candle data available.")

    vol_current, vol_avg20, rvol, vol_trend = _volume_context(current)

    return {
        "signal_id": signal.get("signal_id"),
        "instrument_key": instrument_key,
        "trading_date": str(signal.get("trading_date")),
        "entry_timestamp": entry_ts.isoformat(),
        "volume_current_1m": vol_current,
        "volume_avg_20m": vol_avg20,
        "relative_volume_20m": rvol,
        "volume_trend_5m": vol_trend,
        "price_volume_state": _price_volume_state(current),
        **_structure(current),
    }


def write_volume_structure_csv(rows, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows))
    for col in VOLUME_STRUCTURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    frame.loc[:, list(VOLUME_STRUCTURE_COLUMNS)].to_csv(
        output_path,
        index=False,
    )
    return output_path
