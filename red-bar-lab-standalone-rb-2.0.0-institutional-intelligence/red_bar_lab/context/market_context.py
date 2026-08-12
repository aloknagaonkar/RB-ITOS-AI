from __future__ import annotations

from pathlib import Path

import pandas as pd

IST = "Asia/Kolkata"

CONTEXT_COLUMNS = (
    "signal_id","instrument_key","trading_date","entry_timestamp",
    "session_open","previous_close","previous_high","previous_low",
    "gap_points","gap_pct","minutes_from_open",
    "price_from_open_points","price_from_open_pct",
    "session_high_so_far","session_low_so_far","session_range_so_far",
    "session_range_position","distance_to_previous_high",
    "distance_to_previous_low","opening_range_15_high","opening_range_15_low",
    "opening_range_15_position","atr14_5m","ema9_5m","ema21_5m",
    "trend_5m","realized_volatility_30m_pct",
)


def _to_ist(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=("timestamp","open","high","low","close","volume")
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


def _completed_5m(frame: pd.DataFrame, entry_ts: pd.Timestamp) -> pd.DataFrame:
    source = _to_ist(frame)
    source = source[source["timestamp"] <= entry_ts].copy()
    if source.empty:
        return source

    bars = (
        source.set_index("timestamp")
        .resample(
            "5min",
            origin="start_day",
            offset="15min",
            label="left",
            closed="left",
        )
        .agg(
            open=("open","first"),
            high=("high","max"),
            low=("low","min"),
            close=("close","last"),
            source_rows=("close","count"),
        )
        .dropna(subset=["open","high","low","close"])
    )
    return bars[bars["source_rows"] >= 5].reset_index()


def _atr14(bars: pd.DataFrame):
    if len(bars) < 14:
        return None
    prev = bars["close"].shift(1)
    tr = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - prev).abs(),
            (bars["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = tr.rolling(14, min_periods=14).mean().iloc[-1]
    return None if pd.isna(value) else float(value)


def _ema_trend(bars: pd.DataFrame):
    if bars.empty:
        return None, None, "UNKNOWN"

    close = bars["close"].astype(float)
    ema9 = (
        float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        if len(close) >= 9 else None
    )
    ema21 = (
        float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        if len(close) >= 21 else None
    )
    if ema9 is None or ema21 is None:
        return ema9, ema21, "UNKNOWN"

    last = float(close.iloc[-1])
    if ema9 > ema21 and last >= ema9:
        trend = "UPTREND"
    elif ema9 < ema21 and last <= ema9:
        trend = "DOWNTREND"
    else:
        trend = "RANGE"
    return ema9, ema21, trend


def _rv30(frame: pd.DataFrame):
    if len(frame) < 31:
        return None
    ret = frame["close"].astype(float).tail(31).pct_change().dropna()
    if len(ret) < 2:
        return None
    value = ret.std(ddof=1) * 100.0
    return None if pd.isna(value) else float(value)


def _range_position(price, high, low):
    if high is None or low is None:
        return "UNAVAILABLE"
    if price > high:
        return "ABOVE"
    if price < low:
        return "BELOW"
    return "INSIDE"


def build_market_context_snapshot(
    *,
    signal: dict[str, object],
    instrument_key: str,
    current_day: pd.DataFrame,
    previous_day: pd.DataFrame | None,
) -> dict[str, object]:
    entry_ts = pd.Timestamp(signal["confirmation_timestamp"])
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize(IST)
    else:
        entry_ts = entry_ts.tz_convert(IST)

    current = _to_ist(current_day)
    current = current[current["timestamp"] <= entry_ts].reset_index(drop=True)
    if current.empty:
        raise ValueError("No candles available at or before signal entry.")

    previous = _to_ist(previous_day)
    entry_price = float(signal["underlying_entry"])
    session_open = float(current.iloc[0]["open"])
    high_so_far = float(current["high"].max())
    low_so_far = float(current["low"].min())
    range_so_far = high_so_far - low_so_far

    previous_close = (
        float(previous.iloc[-1]["close"]) if not previous.empty else None
    )
    previous_high = (
        float(previous["high"].max()) if not previous.empty else None
    )
    previous_low = (
        float(previous["low"].min()) if not previous.empty else None
    )

    gap_points = (
        session_open - previous_close if previous_close is not None else None
    )
    gap_pct = (
        gap_points / previous_close * 100.0
        if previous_close not in (None, 0) else None
    )

    session_start = entry_ts.normalize() + pd.Timedelta(hours=9, minutes=15)
    minutes_from_open = max(
        0.0, (entry_ts - session_start).total_seconds() / 60.0
    )

    opening_end = session_start + pd.Timedelta(minutes=15)
    opening = current[
        (current["timestamp"] >= session_start)
        & (current["timestamp"] < opening_end)
    ]
    if entry_ts >= opening_end and len(opening) >= 15:
        or_high = float(opening["high"].max())
        or_low = float(opening["low"].min())
    else:
        or_high = None
        or_low = None

    bars5 = _completed_5m(current, entry_ts)
    atr = _atr14(bars5)
    ema9, ema21, trend = _ema_trend(bars5)

    return {
        "signal_id": signal.get("signal_id"),
        "instrument_key": instrument_key,
        "trading_date": str(signal.get("trading_date")),
        "entry_timestamp": entry_ts.isoformat(),
        "session_open": session_open,
        "previous_close": previous_close,
        "previous_high": previous_high,
        "previous_low": previous_low,
        "gap_points": gap_points,
        "gap_pct": gap_pct,
        "minutes_from_open": minutes_from_open,
        "price_from_open_points": entry_price - session_open,
        "price_from_open_pct": (
            (entry_price - session_open) / session_open * 100.0
            if session_open else None
        ),
        "session_high_so_far": high_so_far,
        "session_low_so_far": low_so_far,
        "session_range_so_far": range_so_far,
        "session_range_position": (
            (entry_price - low_so_far) / range_so_far
            if range_so_far > 0 else 0.5
        ),
        "distance_to_previous_high": (
            entry_price - previous_high if previous_high is not None else None
        ),
        "distance_to_previous_low": (
            entry_price - previous_low if previous_low is not None else None
        ),
        "opening_range_15_high": or_high,
        "opening_range_15_low": or_low,
        "opening_range_15_position": _range_position(
            entry_price, or_high, or_low
        ),
        "atr14_5m": atr,
        "ema9_5m": ema9,
        "ema21_5m": ema21,
        "trend_5m": trend,
        "realized_volatility_30m_pct": _rv30(current),
    }


def write_market_context_csv(rows, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows))
    for col in CONTEXT_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    frame.loc[:, list(CONTEXT_COLUMNS)].to_csv(output_path, index=False)
    return output_path
