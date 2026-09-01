from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from math import isfinite
from typing import Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.intelligence.market_context import wilder_rsi

from .combined_pcr import CombinedMarketPcr
from .contract_selection import research_direction


IST = ZoneInfo("Asia/Kolkata")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def completed_five_minute_close(evaluated_at: datetime) -> datetime | None:
    """Return the latest completed regular-session five-minute boundary."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    local = evaluated_at.astimezone(IST)
    if local.weekday() >= 5 or local.time() < time(9, 20) or local.time() > time(15, 30, 59, 999999):
        return None
    minute = local.minute - (local.minute % 5)
    close = local.replace(minute=minute, second=0, microsecond=0)
    return close if close.time() >= time(9, 20) else None


def completed_one_minute_close(evaluated_at: datetime) -> datetime | None:
    """Return the latest completed regular-session one-minute boundary."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    local = evaluated_at.astimezone(IST)
    if local.weekday() >= 5 or local.time() < time(9, 15) or local.time() > time(15, 30, 59, 999999):
        return None
    close = local.replace(second=0, microsecond=0)
    return close if close.time() >= time(9, 15) else None


@dataclass(frozen=True, slots=True)
class FiveMinutePcrObservation:
    """Immutable PCR evidence associated with one completed NIFTY 5m candle."""

    underlying: str
    candle_close_timestamp: datetime
    source_timestamp: datetime
    overall_pcr: float
    overall_direction: str
    total_ce_oi: float
    total_pe_oi: float
    ce_day_oi_change: float | None
    pe_day_oi_change: float | None
    morning_pcr: float | None
    combined_score: float | None
    combined_direction: str
    combined_coverage: float
    quality_state: str
    combined_index_pcr: float | None = None
    top_ten_pcr: float | None = None
    research_direction: str = "UNAVAILABLE"
    ce_day_oi_change_pct: float | None = None
    pe_day_oi_change_pct: float | None = None
    nifty_spot: float | None = None
    rsi: float | None = None
    vwap: float | None = None

    def __post_init__(self) -> None:
        for name in ("candle_close_timestamp", "source_timestamp"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not self.underlying.strip():
            raise ValueError("underlying cannot be empty")
        if self.overall_pcr < 0 or self.total_ce_oi < 0 or self.total_pe_oi < 0:
            raise ValueError("PCR and OI values cannot be negative")
        if not 0 <= self.combined_coverage <= 1:
            raise ValueError("combined_coverage invalid")

    def payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OneMinutePcrObservation:
    """Immutable PCR evidence associated with one completed NIFTY 1m candle."""

    underlying: str
    candle_close_timestamp: datetime
    source_timestamp: datetime
    overall_pcr: float
    overall_direction: str
    total_ce_oi: float
    total_pe_oi: float
    ce_day_oi_change: float | None
    pe_day_oi_change: float | None
    morning_pcr: float | None
    combined_score: float | None
    combined_direction: str
    combined_coverage: float
    quality_state: str
    combined_index_pcr: float | None = None
    top_ten_pcr: float | None = None
    research_direction: str = "UNAVAILABLE"
    ce_day_oi_change_pct: float | None = None
    pe_day_oi_change_pct: float | None = None
    nifty_spot: float | None = None
    rsi: float | None = None
    vwap: float | None = None

    def __post_init__(self) -> None:
        for name in ("candle_close_timestamp", "source_timestamp"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not self.underlying.strip():
            raise ValueError("underlying cannot be empty")
        if self.overall_pcr < 0 or self.total_ce_oi < 0 or self.total_pe_oi < 0:
            raise ValueError("PCR and OI values cannot be negative")
        if not 0 <= self.combined_coverage <= 1:
            raise ValueError("combined_coverage invalid")

    def payload(self) -> dict[str, object]:
        return asdict(self)


def build_five_minute_pcr_observation(
    *,
    projection: Mapping[str, object],
    combined: CombinedMarketPcr,
    evaluated_at: datetime,
    rsi: float | None = None,
    vwap: float | None = None,
) -> FiveMinutePcrObservation | None:
    """Build a record only when contemporaneous completed-candle PCR exists."""
    close = completed_five_minute_close(evaluated_at)
    if close is None:
        return None
    source_raw = projection.get("source_timestamp")
    if not isinstance(source_raw, str):
        return None
    try:
        source = datetime.fromisoformat(source_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if source.tzinfo is None or source.utcoffset() is None:
        return None
    # Never attach evidence collected before the candle closed to that candle.
    if source.astimezone(timezone.utc) < close.astimezone(timezone.utc):
        return None

    current = _mapping(projection.get("current_panel"))
    aggregate = _mapping(current.get("aggregate"))
    pcr = _number(aggregate.get("pcr"))
    ce_oi = _number(aggregate.get("total_ce_oi"))
    pe_oi = _number(aggregate.get("total_pe_oi"))
    if pcr is None or ce_oi is None or pe_oi is None:
        return None
    evidence = _mapping(aggregate.get("direction_evidence"))
    morning = _mapping(projection.get("morning_panel"))
    morning_aggregate = _mapping(morning.get("aggregate"))
    quality = _mapping(projection.get("quality"))
    total_row = next(
        (
            row for row in current.get("rows", ())
            if isinstance(row, Mapping) and str(row.get("position", "")).upper() == "TOTAL"
        ),
        {},
    )
    current_direction = str(evidence.get("direction") or "UNAVAILABLE").upper()
    morning_evidence = _mapping(morning_aggregate.get("direction_evidence"))
    morning_direction = str(
        morning_evidence.get("direction") or "UNAVAILABLE"
    ).upper()
    resolved_direction, _ = research_direction(
        combined_direction=combined.direction,
        combined_ready=combined.index_pcr is not None,
        current_direction=current_direction,
        current_ready=True,
        morning_direction=morning_direction,
    )
    top_ten = next(
        (
            component for component in combined.components
            if component.name == "NIFTY TOP 10"
        ),
        None,
    )
    return FiveMinutePcrObservation(
        underlying=str(projection.get("underlying") or "NIFTY 50"),
        candle_close_timestamp=close,
        source_timestamp=source,
        overall_pcr=pcr,
        overall_direction=str(evidence.get("direction") or "UNAVAILABLE").upper(),
        total_ce_oi=ce_oi,
        total_pe_oi=pe_oi,
        ce_day_oi_change=_number(total_row.get("ce_previous_day_change")),
        pe_day_oi_change=_number(total_row.get("pe_previous_day_change")),
        morning_pcr=_number(morning_aggregate.get("pcr")),
        combined_score=combined.score,
        combined_direction=combined.direction,
        combined_coverage=combined.coverage,
        quality_state=str(quality.get("state") or "UNAVAILABLE").upper(),
        combined_index_pcr=combined.index_pcr,
        top_ten_pcr=None if top_ten is None else top_ten.pcr,
        research_direction=resolved_direction,
        ce_day_oi_change_pct=_number(total_row.get("ce_previous_day_change_pct")),
        pe_day_oi_change_pct=_number(total_row.get("pe_previous_day_change_pct")),
        nifty_spot=_number(current.get("spot")),
        rsi=_number(rsi),
        vwap=_number(vwap),
    )


def build_one_minute_pcr_observation(
    *,
    projection: Mapping[str, object],
    combined: CombinedMarketPcr,
    evaluated_at: datetime,
    rsi: float | None = None,
    vwap: float | None = None,
) -> OneMinutePcrObservation | None:
    close = completed_one_minute_close(evaluated_at)
    if close is None:
        return None
    source_raw = projection.get("source_timestamp")
    if not isinstance(source_raw, str):
        return None
    try:
        source = datetime.fromisoformat(source_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if source.tzinfo is None or source.utcoffset() is None:
        return None
    if source.astimezone(timezone.utc) < close.astimezone(timezone.utc):
        return None
    current = _mapping(projection.get("current_panel"))
    aggregate = _mapping(current.get("aggregate"))
    pcr = _number(aggregate.get("pcr"))
    ce_oi = _number(aggregate.get("total_ce_oi"))
    pe_oi = _number(aggregate.get("total_pe_oi"))
    if pcr is None or ce_oi is None or pe_oi is None:
        return None
    evidence = _mapping(aggregate.get("direction_evidence"))
    morning = _mapping(projection.get("morning_panel"))
    morning_aggregate = _mapping(morning.get("aggregate"))
    quality = _mapping(projection.get("quality"))
    total_row = next(
        (
            row for row in current.get("rows", ())
            if isinstance(row, Mapping) and str(row.get("position", "")).upper() == "TOTAL"
        ),
        {},
    )
    current_direction = str(evidence.get("direction") or "UNAVAILABLE").upper()
    morning_evidence = _mapping(morning_aggregate.get("direction_evidence"))
    morning_direction = str(
        morning_evidence.get("direction") or "UNAVAILABLE"
    ).upper()
    resolved_direction, _ = research_direction(
        combined_direction=combined.direction,
        combined_ready=combined.index_pcr is not None,
        current_direction=current_direction,
        current_ready=True,
        morning_direction=morning_direction,
    )
    top_ten = next(
        (
            component for component in combined.components
            if component.name == "NIFTY TOP 10"
        ),
        None,
    )
    return OneMinutePcrObservation(
        underlying=str(projection.get("underlying") or "NIFTY 50"),
        candle_close_timestamp=close,
        source_timestamp=source,
        overall_pcr=pcr,
        overall_direction=str(evidence.get("direction") or "UNAVAILABLE").upper(),
        total_ce_oi=ce_oi,
        total_pe_oi=pe_oi,
        ce_day_oi_change=_number(total_row.get("ce_previous_day_change")),
        pe_day_oi_change=_number(total_row.get("pe_previous_day_change")),
        morning_pcr=_number(morning_aggregate.get("pcr")),
        combined_score=combined.score,
        combined_direction=combined.direction,
        combined_coverage=combined.coverage,
        quality_state=str(quality.get("state") or "UNAVAILABLE").upper(),
        combined_index_pcr=combined.index_pcr,
        top_ten_pcr=None if top_ten is None else top_ten.pcr,
        research_direction=resolved_direction,
        ce_day_oi_change_pct=_number(total_row.get("ce_previous_day_change_pct")),
        pe_day_oi_change_pct=_number(total_row.get("pe_previous_day_change_pct")),
        nifty_spot=_number(current.get("spot")),
        rsi=_number(rsi),
        vwap=_number(vwap),
    )


def completed_five_minute_rsi(
    candles: object,
    *,
    candle_close: datetime,
    period: int = 14,
) -> float | None:
    """Calculate RSI using only five-minute candles completed by the boundary."""
    if not isinstance(candles, pd.DataFrame) or candles.empty:
        return None
    if "timestamp" not in candles.columns or "close" not in candles.columns:
        return None
    frame = candles.loc[:, ["timestamp", "close"]].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna().sort_values("timestamp")
    if frame.empty:
        return None
    boundary = pd.Timestamp(candle_close)
    timestamps = frame["timestamp"]
    if timestamps.dt.tz is None:
        boundary = boundary.tz_localize(None)
    else:
        boundary = boundary.tz_convert(timestamps.dt.tz)
    # Provider timestamps identify candle opens; a bar is usable after +5 minutes.
    completed = frame.loc[timestamps + pd.Timedelta(minutes=5) <= boundary]
    if len(completed) <= period:
        return None
    series = wilder_rsi(completed["close"], period=period).dropna()
    return None if series.empty else round(float(series.iloc[-1]), 2)


def aligned_futures_vwap(
    snapshots: list[Mapping[str, object]],
    *,
    candle_close: datetime,
    maximum_lag_seconds: float = 120.0,
) -> float | None:
    """Select a futures VWAP timestamped at or immediately before the boundary."""
    close_utc = candle_close.astimezone(timezone.utc)
    for row in snapshots:
        raw_timestamp = row.get("futures_vwap_timestamp")
        value = _number(row.get("futures_vwap") or row.get("vwap"))
        if not isinstance(raw_timestamp, str) or value is None:
            continue
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            continue
        lag = (close_utc - timestamp.astimezone(timezone.utc)).total_seconds()
        if 0 <= lag <= maximum_lag_seconds:
            return value
    return None


__all__ = [
    "FiveMinutePcrObservation",
    "OneMinutePcrObservation",
    "build_five_minute_pcr_observation",
    "build_one_minute_pcr_observation",
    "completed_five_minute_rsi",
    "completed_five_minute_close",
    "completed_one_minute_close",
    "aligned_futures_vwap",
]
