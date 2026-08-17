from __future__ import annotations

import pandas as pd

from red_bar_lab.execution.directional_regime_background import (
    _completed_five_minute,
    _normalize_one_minute,
)
from red_bar_lab.execution.rsi_extreme_reversal import _rsi


IST = "Asia/Kolkata"


def preparation_cutoff(trading_date: str, now: object | None = None) -> pd.Timestamp:
    selected = pd.Timestamp(trading_date)
    current = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
    if current.tzinfo is None:
        current = current.tz_localize(IST)
    else:
        current = current.tz_convert(IST)
    if selected.date() == current.date():
        return current
    return (selected + pd.Timedelta(days=1)).tz_localize(IST)


def prepare_completed_one_minute(
    candles: pd.DataFrame,
    trading_date: str,
    *,
    now: object | None = None,
) -> pd.DataFrame:
    cutoff = preparation_cutoff(trading_date, now)
    return _normalize_one_minute([candles], cutoff)


def prepare_completed_five_minute(
    one_minute: pd.DataFrame,
    trading_date: str,
    *,
    now: object | None = None,
) -> pd.DataFrame:
    cutoff = preparation_cutoff(trading_date, now)
    return _completed_five_minute(one_minute, cutoff)


def latest_wilder_rsi(one_minute: pd.DataFrame, period: int = 7) -> float | None:
    if one_minute.empty or "close" not in one_minute.columns:
        return None
    values = _rsi(one_minute["close"], period).dropna()
    return float(values.iloc[-1]) if not values.empty else None
