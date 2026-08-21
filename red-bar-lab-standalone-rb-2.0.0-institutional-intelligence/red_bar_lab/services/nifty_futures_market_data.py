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
    futures_vwap: float | None = None
    futures_vwap_timestamp: str | None = None
    futures_close_vs_vwap_points: float | None = None
    futures_close_vs_vwap_atr: float | None = None
    futures_vwap_slope: float | None = None
    futures_vwap_acceptance: str = "UNAVAILABLE"
    candle_count: int = 0
    completed_candles: tuple[object, ...] = ()
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


def _completed_candles(candles: list[object], *, now: datetime, interval_minutes: int) -> list[object]:
    interval = max(1, int(interval_minutes))
    current_bucket = now.replace(second=0, microsecond=0)
    current_bucket -= timedelta(minutes=current_bucket.minute % interval)
    expected_completed = current_bucket - timedelta(minutes=interval)
    dated = []
    for candle in candles:
        stamp = _timestamp(candle, reference=now)
        if stamp is not None and stamp <= expected_completed:
            dated.append((stamp, candle))
    return [candle for _, candle in sorted(dated, key=lambda item: item[0])]


def _futures_vwap(completed: list[object], *, now: datetime) -> dict[str, Any]:
    rows: list[tuple[datetime, float, float, float, float, float]] = []
    for candle in completed:
        stamp = _timestamp(candle, reference=now)
        high = _number(_value(candle, ("high",), 2))
        low = _number(_value(candle, ("low",), 3))
        close = _number(_value(candle, ("close", "closing_price"), 4))
        volume = _number(_value(candle, ("volume", "vol", "traded_volume"), 5))
        if stamp is None or None in (high, low, close, volume) or float(volume) <= 0:
            continue
        rows.append((stamp, float(high), float(low), float(close), float(volume), (float(high)+float(low)+float(close))/3.0))
    if len(rows) < 2:
        return {"vwap": None, "timestamp": None, "points": None, "atr_gap": None, "slope": None, "acceptance": "UNAVAILABLE"}
    cumulative_volume = 0.0
    cumulative_value = 0.0
    series: list[float] = []
    true_ranges: list[float] = []
    previous_close: float | None = None
    for _, high, low, close, volume, typical in rows:
        cumulative_volume += volume
        cumulative_value += typical * volume
        series.append(cumulative_value / cumulative_volume)
        true_ranges.append(max(high-low, abs(high-previous_close) if previous_close is not None else 0.0, abs(low-previous_close) if previous_close is not None else 0.0))
        previous_close = close
    vwap = series[-1]
    slope = vwap - series[max(0, len(series)-6)]
    latest_close = rows[-1][3]
    points = latest_close - vwap
    atr_window = true_ranges[-14:]
    atr = sum(atr_window) / len(atr_window) if atr_window else 0.0
    atr_gap = points / atr if atr > 0 else None
    prior_close = rows[-2][3]
    prior_vwap = series[-2]
    if abs(points) <= max(1.0, atr * 0.10):
        acceptance = "NEAR_VWAP"
    elif latest_close > vwap and slope > 0:
        acceptance = "VWAP_RECLAIM" if prior_close <= prior_vwap else "ABOVE_RISING_VWAP"
    elif latest_close < vwap and slope < 0:
        acceptance = "VWAP_REJECTION" if prior_close >= prior_vwap else "BELOW_FALLING_VWAP"
    else:
        acceptance = "NEAR_VWAP"
    return {
        "vwap": round(vwap, 4),
        "timestamp": rows[-1][0].isoformat(),
        "points": round(points, 4),
        "atr_gap": round(atr_gap, 4) if atr_gap is not None else None,
        "slope": round(slope, 4),
        "acceptance": acceptance,
    }


def assess_nifty_futures_market_data(provider, *, contract: NiftyFuturesMonitorResult, now: datetime, interval_minutes: int = 1, stale_after_seconds: int = 120) -> NiftyFuturesMarketData:
    """Fetch active NIFTY futures candles and expose volume/OI/VWAP diagnostics."""
    if contract.status != "READY" or not contract.instrument_key:
        return NiftyFuturesMarketData(status="UNAVAILABLE", reason="Active NIFTY futures contract is unavailable.", error=contract.error)
    try:
        payload = provider.intraday_candles(contract.instrument_key, interval_minutes=interval_minutes)
    except Exception as exc:
        return NiftyFuturesMarketData(status="ERROR", reason="Active NIFTY futures candle request failed.", instrument_key=contract.instrument_key, trading_symbol=contract.trading_symbol, expiry=contract.expiry, error=f"{type(exc).__name__}:{exc}")
    candles = _normalise_candles(payload)
    readiness = assess_underlying_candle_freshness(candles, now=now, interval_minutes=interval_minutes, stale_after_seconds=stale_after_seconds)
    completed = _completed_candles(candles, now=now, interval_minutes=interval_minutes)
    latest = completed[-1] if completed else None
    latest_volume = _number(_value(latest, ("volume", "vol", "traded_volume"), 5)) if latest is not None else None
    latest_oi = _number(_value(latest, ("oi", "open_interest", "openInterest"), 6)) if latest is not None else None
    latest_close = _number(_value(latest, ("close", "closing_price"), 4)) if latest is not None else None
    latest_timestamp = _value(latest, ("timestamp", "time", "datetime", "date"), 0) if latest is not None else None
    volume = assess_underlying_volume_authority(instrument_key=contract.instrument_key, volume=latest_volume)
    vwap = _futures_vwap(completed, now=now)
    status = "READY" if latest is not None else "MISSING"
    reason = "Latest completed NIFTY futures candle, volume, OI and VWAP evidence were collected." if latest is not None else "No completed NIFTY futures candle is available."
    return NiftyFuturesMarketData(status=status, reason=reason, instrument_key=contract.instrument_key, trading_symbol=contract.trading_symbol, expiry=contract.expiry, candle_readiness=readiness, volume_authority=volume, latest_close=latest_close, latest_volume=latest_volume, latest_oi=latest_oi, latest_timestamp=str(latest_timestamp) if latest_timestamp is not None else None, futures_vwap=vwap["vwap"], futures_vwap_timestamp=vwap["timestamp"], futures_close_vs_vwap_points=vwap["points"], futures_close_vs_vwap_atr=vwap["atr_gap"], futures_vwap_slope=vwap["slope"], futures_vwap_acceptance=vwap["acceptance"], candle_count=len(candles), completed_candles=tuple(completed))


def futures_market_log_values(result: NiftyFuturesMarketData) -> tuple[str, ...]:
    readiness = result.candle_readiness
    volume = result.volume_authority
    return (result.status, result.reason, readiness.status if readiness else "NA", volume.status if volume else "NA", "NA" if result.latest_close is None else f"{result.latest_close:.2f}", "NA" if result.latest_volume is None else f"{result.latest_volume:.1f}", "NA" if result.latest_oi is None else f"{result.latest_oi:.1f}", result.latest_timestamp or "NA", str(result.candle_count), result.error or "NONE")
