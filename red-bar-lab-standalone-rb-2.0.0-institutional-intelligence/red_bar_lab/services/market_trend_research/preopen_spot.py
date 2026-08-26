from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class PreOpenSpotObservation:
    """One immutable provider observation of the NIFTY pre-open value."""

    underlying: str
    trading_date: date
    provider: str
    spot: float
    source_timestamp: datetime
    captured_at: datetime
    status: str = "AVAILABLE"

    def __post_init__(self) -> None:
        if self.provider not in {"NSE", "UPSTOX"}:
            raise ValueError("PREOPEN_PROVIDER_INVALID")
        if not isfinite(self.spot) or self.spot <= 0:
            raise ValueError("PREOPEN_SPOT_INVALID")
        for value in (self.source_timestamp, self.captured_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("PREOPEN_TIMESTAMP_NAIVE")


@dataclass(frozen=True, slots=True)
class PreOpenSpotResolution:
    selected: PreOpenSpotObservation | None
    nse: PreOpenSpotObservation | None
    upstox: PreOpenSpotObservation | None
    state: str
    difference_points: float | None
    difference_pct: float | None


class PreOpenSpotProvider(Protocol):
    def observe(self, *, captured_at: datetime) -> PreOpenSpotObservation: ...


class NsePreOpenSpotProvider:
    """Read the public NSE pre-open payload without sharing trading authority."""

    BASE_URL = "https://www.nseindia.com"

    def __init__(self, *, timeout_seconds: float = 5.0, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": (
                f"{self.BASE_URL}/market-data/"
                "pre-open-market-cm-and-emerge-market?cat=NE"
            ),
        })
        self._cookies_ready = False

    def _get(self, path: str, *, params: Mapping[str, str] | None = None) -> Mapping[str, object]:
        if not self._cookies_ready:
            landing = self.session.get(self.BASE_URL, timeout=self.timeout_seconds)
            landing.raise_for_status()
            self._cookies_ready = True
        response = self.session.get(
            f"{self.BASE_URL}{path}", params=params, timeout=self.timeout_seconds
        )
        if response.status_code in {401, 403}:
            self._cookies_ready = False
            landing = self.session.get(self.BASE_URL, timeout=self.timeout_seconds)
            landing.raise_for_status()
            self._cookies_ready = True
            response = self.session.get(
                f"{self.BASE_URL}{path}", params=params, timeout=self.timeout_seconds
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("NSE_PREOPEN_RESPONSE_MALFORMED")
        return payload

    @staticmethod
    def _spot(payload: Mapping[str, object]) -> float:
        nifty = payload.get("nifty_data")
        candidates: list[object] = []
        if isinstance(nifty, Mapping):
            candidates.extend(
                nifty.get(key) for key in ("lastPrice", "iep", "indicativePrice", "open")
            )
        candidates.extend(payload.get(key) for key in ("nifty", "niftyValue", "indicativeValue"))
        for candidate in candidates:
            try:
                value = float(str(candidate).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if isfinite(value) and value > 0:
                return value
        raise ValueError("NSE_PREOPEN_NIFTY_VALUE_UNAVAILABLE")

    @staticmethod
    def _timestamp(payload: Mapping[str, object], *, fallback: datetime) -> datetime:
        raw = payload.get("timestamp")
        nifty = payload.get("nifty_data")
        if raw is None and isinstance(nifty, Mapping):
            raw = nifty.get("timestamp") or nifty.get("lastUpdateTime")
        if isinstance(raw, str):
            for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %I:%M:%S %p"):
                try:
                    return datetime.strptime(raw.strip().removesuffix(" IST"), pattern).replace(tzinfo=IST)
                except ValueError:
                    continue
            try:
                parsed = datetime.fromisoformat(raw)
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)
            except ValueError:
                pass
        return fallback.astimezone(IST)

    def observe(self, *, captured_at: datetime) -> PreOpenSpotObservation:
        payload = self._get("/api/market-data-pre-open", params={"key": "NIFTY"})
        return PreOpenSpotObservation(
            underlying="NIFTY 50",
            trading_date=captured_at.astimezone(IST).date(),
            provider="NSE",
            spot=self._spot(payload),
            source_timestamp=self._timestamp(payload, fallback=captured_at),
            captured_at=captured_at,
        )


def resolve_preopen_spot(
    observations: tuple[PreOpenSpotObservation, ...],
    *,
    evaluated_at: datetime,
    maximum_age_seconds: float,
    conflict_tolerance_pct: float = 0.10,
) -> PreOpenSpotResolution:
    """Prefer fresh NSE evidence, falling back to fresh Upstox evidence."""

    fresh = tuple(
        item for item in observations
        if 0 <= (evaluated_at - item.source_timestamp).total_seconds() <= maximum_age_seconds
    )
    by_provider = {item.provider: item for item in fresh}
    nse = by_provider.get("NSE")
    upstox = by_provider.get("UPSTOX")
    difference = abs(nse.spot - upstox.spot) if nse and upstox else None
    difference_pct = (
        difference / nse.spot * 100.0 if difference is not None and nse else None
    )
    if nse and upstox:
        state = "CONFLICT" if difference_pct is not None and difference_pct > conflict_tolerance_pct else "ALIGNED"
        return PreOpenSpotResolution(nse, nse, upstox, state, difference, difference_pct)
    if nse:
        return PreOpenSpotResolution(nse, nse, None, "NSE_PRIMARY", None, None)
    if upstox:
        return PreOpenSpotResolution(upstox, None, upstox, "UPSTOX_FALLBACK", None, None)
    return PreOpenSpotResolution(None, None, None, "UNAVAILABLE", None, None)


__all__ = [
    "NsePreOpenSpotProvider",
    "PreOpenSpotObservation",
    "PreOpenSpotProvider",
    "PreOpenSpotResolution",
    "resolve_preopen_spot",
]
