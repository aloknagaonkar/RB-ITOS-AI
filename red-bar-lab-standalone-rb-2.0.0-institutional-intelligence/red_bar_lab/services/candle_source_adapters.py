from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from red_bar_lab.storage.artifacts import ArtifactLayout


def _interval_minutes(timeframe: str) -> int:
    value = str(timeframe or "1m").strip().lower()
    if value.endswith("m"):
        value = value[:-1]
    return max(1, int(value))


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, pd.DataFrame):
        if frame.empty:
            return []
        return frame.to_dict("records")
    return [dict(row) for row in frame]


def build_live_persisted_candle_reader(settings, *, provider: str = "upstox"):
    layout = ArtifactLayout(settings)

    def read(*, instrument_key: str, timeframe: str, cutoff_timestamp: str):
        interval = _interval_minutes(timeframe)
        path = layout.live_session_path(provider, instrument_key, interval)
        if not path.exists():
            return []
        return _records(pd.read_csv(path))

    return read


def build_historical_candle_reader(historical):
    def read(*, instrument_key: str, timeframe: str, cutoff_timestamp: str):
        interval = _interval_minutes(timeframe)
        cutoff = pd.Timestamp(cutoff_timestamp)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("Asia/Kolkata")
        else:
            cutoff = cutoff.tz_convert("Asia/Kolkata")
        frame = historical.read_day(
            instrument_key,
            date.fromisoformat(cutoff.date().isoformat()),
            interval_minutes=interval,
        )
        return _records(frame)

    return read


__all__ = [
    "build_live_persisted_candle_reader",
    "build_historical_candle_reader",
]
