from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from red_bar_lab.execution.underlying_candle_readiness import (
    CANDLE_MARKET_CLOSED,
    CANDLE_MISSING,
    CANDLE_READY,
    UnderlyingCandleReadiness,
    assess_underlying_candle_freshness,
)
from red_bar_lab.execution.underlying_volume_authority import (
    UnderlyingVolumeAuthority,
    assess_underlying_volume_authority,
)

ALIGNMENT_CONSISTENT = "CONSISTENT"
ALIGNMENT_AFTER_HOURS_EXPECTED = "AFTER_HOURS_EXPECTED"
ALIGNMENT_SNAPSHOT_STALE_CANDLES_READY = "SNAPSHOT_STALE_CANDLES_READY"
ALIGNMENT_CANDLES_DEGRADED = "CANDLES_DEGRADED"


@dataclass(frozen=True)
class UnderlyingCandleMonitorDiagnostic:
    readiness: UnderlyingCandleReadiness
    bridge_alignment: str
    volume_authority: UnderlyingVolumeAuthority | None = None
    fetch_error: str | None = None


def _normalise_candles(payload: object) -> list[object]:
    """Normalise provider/DataFrame candle payloads for readiness assessment."""

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


def _candle_volume(candle: object) -> object:
    if isinstance(candle, Mapping):
        for key in ("volume", "vol", "traded_volume"):
            if key in candle:
                return candle.get(key)
        return None
    if isinstance(candle, Sequence) and not isinstance(candle, (str, bytes)):
        return candle[5] if len(candle) > 5 else None
    return None


def _latest_reported_volume(candles: Sequence[object]) -> object:
    for candle in reversed(candles):
        volume = _candle_volume(candle)
        if volume is not None and volume != "":
            return volume
    return None


def _bridge_alignment(
    readiness: UnderlyingCandleReadiness,
    bridge_reason: str | None,
) -> str:
    reason = str(bridge_reason or "").strip().upper()
    if readiness.status == CANDLE_MARKET_CLOSED:
        return ALIGNMENT_AFTER_HOURS_EXPECTED
    if reason == "V2_SNAPSHOT_STALE" and readiness.status == CANDLE_READY:
        return ALIGNMENT_SNAPSHOT_STALE_CANDLES_READY
    if readiness.status != CANDLE_READY:
        return ALIGNMENT_CANDLES_DEGRADED
    return ALIGNMENT_CONSISTENT


def assess_monitor_underlying_candles(
    provider,
    *,
    instrument_key: str,
    now: datetime,
    bridge_reason: str | None = None,
    interval_minutes: int = 1,
    stale_after_seconds: int = 120,
) -> UnderlyingCandleMonitorDiagnostic:
    """Fetch and assess underlying candles without execution authority.

    This diagnostic deliberately does not alter Red Bar V2 publishing or paper
    execution. It explains whether a stale V2 snapshot is accompanied by fresh,
    degraded, or after-hours underlying candles, and whether reported volume is
    a valid traded-volume authority for the instrument type.
    """

    try:
        payload = provider.intraday_candles(
            instrument_key,
            interval_minutes=interval_minutes,
        )
    except Exception as exc:
        readiness = UnderlyingCandleReadiness(
            CANDLE_MISSING,
            "Underlying candle provider request failed.",
        )
        return UnderlyingCandleMonitorDiagnostic(
            readiness=readiness,
            bridge_alignment=ALIGNMENT_CANDLES_DEGRADED,
            volume_authority=assess_underlying_volume_authority(
                instrument_key=instrument_key,
                volume=None,
            ),
            fetch_error=f"{type(exc).__name__}:{exc}",
        )

    candles = _normalise_candles(payload)
    readiness = assess_underlying_candle_freshness(
        candles,
        now=now,
        interval_minutes=interval_minutes,
        stale_after_seconds=stale_after_seconds,
    )
    return UnderlyingCandleMonitorDiagnostic(
        readiness=readiness,
        bridge_alignment=_bridge_alignment(readiness, bridge_reason),
        volume_authority=assess_underlying_volume_authority(
            instrument_key=instrument_key,
            volume=_latest_reported_volume(candles),
        ),
    )
