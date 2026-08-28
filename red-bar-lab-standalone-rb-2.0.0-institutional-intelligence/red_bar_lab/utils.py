"""Shared utility functions used across the Red Bar codebase."""

from __future__ import annotations

from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def safe_float(value: Any, default: float | None = None) -> float | None:
    """Convert a value to float, returning default if not possible.

    Replaces the 28+ duplicated _num() functions across the codebase.
    Call with default=0.0 to get the old _num(value, default=0.0) behavior.
    Call without default to get the old _num(value) -> float | None behavior.
    """
    try:
        if value is None or pd.isna(value):
            return float(default) if default is not None else None
        return float(value)
    except (TypeError, ValueError):
        return float(default) if default is not None else None


def safe_pct(current: float | None, previous: float | None) -> float | None:
    """Compute percentage change, returning None if not possible.

    This replaces the duplicated _pct() static methods found in
    institutional_flow, oi_velocity, and premium_flow.
    """
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def to_ist(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert DataFrame timestamps to IST, deduplicate and sort.

    This replaces the duplicated _to_ist() functions found in
    level_engine, signal_engine, and trade_engine.
    """
    if frame is None or frame.empty:
        return pd.DataFrame(columns=("timestamp", "open", "high", "low", "close", "volume"))
    result = frame.copy()
    ts = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.loc[ts.notna()].copy()
    result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
    return (
        result.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
