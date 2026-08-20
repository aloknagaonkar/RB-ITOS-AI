from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from red_bar_lab.execution.underlying_candle_readiness import (
    UnderlyingCandleReadiness,
    assess_underlying_candle_freshness,
)
from red_bar_lab.execution.underlying_volume_authority import (
    UnderlyingVolumeAuthority,
    assess_underlying_volume_authority,
)
from red_bar_lab.services.nifty_futures_monitoring import NiftyFuturesMonitorResult


@dataclass(frozen=True)
class NiftyFuturesMarketData:
    status: str
    reason: str
    instrument_key: str | None = None
    trading_symbol: str | None = None
    expiry: str | None = None
    candle_readiness: UnderlyingCandleReadiness | None = None
    volume_authority: UnderlyingVolumeAuthority | None = None
    latest_close: float | None = None
    latest_volume: float | None = None
    latest_oi: float | None = None
    latest_timestamp: str | None = None
    candle_count: int = 0
    error: str | None = None


def _normalise_candles(payload: object) -> list[object]:
    if payload is None:
        return []
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict("records")
        except TypeError:
            records = None
        if isinstance(records, list):
            return records
    if isinstance(payload, Mapping):
        for key in ("data", "candles", "rows"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return list(value)
        return [dict(payload)]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return list(payload)
    return []


def _value(candle: object, mapping_names: tuple[str, ...], index: int) -> object:
    if isinstance(candle, Mapping):
        for name in mapping_names:
            if name in candle:
                return candle.get(name)
        return None
    if isinstance(candle, Sequence) and not isinstance(candle, (str, bytes)):
        return candle[index] if len(candle) > index else None
    return None


def _timestamp(candle: object, *, reference: datetime) -> datetime | None:
    raw = _value(candle, ("timestamp", "time", "datetime", "date"), 0)
    if isinstance(raw, datetime):
        parsed = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None and reference.tzinfo is not None:
        parsed = parsed.replace(tzinfo=reference.tzinfo)
    if parsed.tzinfo is not None and reference.tzinfo is not None:
        parsed = parsed.astimezone(reference.tzinfo)
    return parsed


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_completed_candle(
    candles: list[object],
    *,
    now: datetime,
    interval_minutes: int,
) -> object | None:
    interval = max(1, int(interval_minutes))
    current_bucket = now.replace(second=0, microsecond=0)
    current_bucket -= timedelta(minutes=current_bucket.minute % interval)
    expected_completed = current_bucket - timedelta(minutes=interval)
    dated = []
    for candle in candles:
        stamp = _timestamp(candle, reference=now)
        if stamp is not None and stamp <= expected_completed:
            dated.append((stamp, candle))
    if dated:
        return max(dated, key=lambda item: item[0])[1]
    return None


def assess_nifty_futures_market_data(
    provider,
    *,
    contract: NiftyFuturesMonitorResult,
    now: datetime,
    interval_minutes: int = 1,
    stale_after_seconds: int = 120,
) -> NiftyFuturesMarketData:
    """Fetch active NIFTY futures candles and expose volume/OI diagnostics.

    This service is read-only and observational. It does not influence Red Bar
    admission, option selection, entries, exits, or paper execution.
    """

    if contract.status != "READY" or not contract.instrument_key:
        return NiftyFuturesMarketData(
            status="UNAVAILABLE",
            reason="Active NIFTY futures contract is unavailable.",
            error=contract.error,
        )

    try:
        payload = provider.intraday_candles(
            contract.instrument_key,
            interval_minutes=interval_minutes,
        )
    except Exception as exc:
        return NiftyFuturesMarketData(
            status="ERROR",
            reason="Active NIFTY futures candle request failed.",
            instrument_key=contract.instrument_key,
            trading_symbol=contract.trading_symbol,
            expiry=contract.expiry,
            error=f"{type(exc).__name__}:{exc}",
        )

    candles = _normalise_candles(payload)
    readiness = assess_underlying_candle_freshness(
        candles,
        now=now,
        interval_minutes=interval_minutes,
        stale_after_seconds=stale_after_seconds,
    )
    latest = _latest_completed_candle(
        candles,
        now=now,
        interval_minutes=interval_minutes,
    )
    latest_volume = _number(
        _value(latest, ("volume", "vol", "traded_volume"), 5)
    ) if latest is not None else None
    latest_oi = _number(
        _value(latest, ("oi", "open_interest", "openInterest"), 6)
    ) if latest is not None else None
    latest_close = _number(
        _value(latest, ("close", "closing_price"), 4)
    ) if latest is not None else None
    latest_timestamp = _value(
        latest, ("timestamp", "time", "datetime", "date"), 0
    ) if latest is not None else None
    volume = assess_underlying_volume_authority(
        instrument_key=contract.instrument_key,
        volume=latest_volume,
    )

    status = "READY" if latest is not None else "MISSING"
    reason = (
        "Latest completed NIFTY futures candle, volume and OI were collected."
        if latest is not None
        else "No completed NIFTY futures candle is available."
    )
    return NiftyFuturesMarketData(
        status=status,
        reason=reason,
        instrument_key=contract.instrument_key,
        trading_symbol=contract.trading_symbol,
        expiry=contract.expiry,
        candle_readiness=readiness,
        volume_authority=volume,
        latest_close=latest_close,
        latest_volume=latest_volume,
        latest_oi=latest_oi,
        latest_timestamp=(str(latest_timestamp) if latest_timestamp is not None else None),
        candle_count=len(candles),
    )


def futures_market_log_values(result: NiftyFuturesMarketData) -> tuple[str, ...]:
    readiness = result.candle_readiness
    volume = result.volume_authority
    return (
        result.status,
        result.reason,
        readiness.status if readiness else "NA",
        volume.status if volume else "NA",
        "NA" if result.latest_close is None else f"{result.latest_close:.2f}",
        "NA" if result.latest_volume is None else f"{result.latest_volume:.1f}",
        "NA" if result.latest_oi is None else f"{result.latest_oi:.1f}",
        result.latest_timestamp or "NA",
        str(result.candle_count),
        result.error or "NONE",
    )
