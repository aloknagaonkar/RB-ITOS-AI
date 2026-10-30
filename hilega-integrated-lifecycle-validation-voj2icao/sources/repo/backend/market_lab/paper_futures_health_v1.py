
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from .domain import IST
from .oi_vwap_live_feature_engine_v1 import FuturesVWAPFeature


@dataclass(frozen=True)
class FuturesDataHealth:
    ok: bool
    status: str
    reason_code: str | None
    candle_time: str | None
    available_at: str
    age_seconds: float | None
    new_entries_allowed: bool


def validate_futures_vwap_health(
    feature: FuturesVWAPFeature | None,
    *,
    now: datetime | None = None,
    max_completed_candle_age_seconds: int = 480,
) -> FuturesDataHealth:
    """
    For a completed 5m candle, an age tolerance >5m is required because the last
    eligible interval start is normally 5-10 minutes behind wall clock.
    Default 480s (8m) is intentionally conservative for the production guard.
    """
    now = now or datetime.now(IST)
    if feature is None:
        return FuturesDataHealth(
            ok=False,
            status="FAIL",
            reason_code="FUTURES_VWAP_MISSING",
            candle_time=None,
            available_at=now.isoformat(),
            age_seconds=None,
            new_entries_allowed=False,
        )

    candle_start = datetime.fromisoformat(feature.candle_time.replace("Z", "+00:00")).astimezone(IST)
    candle_complete = candle_start + timedelta(minutes=5)
    age = (now.astimezone(IST) - candle_complete).total_seconds()

    if age < -1:
        return FuturesDataHealth(
            ok=False,
            status="FAIL",
            reason_code="FUTURES_CANDLE_NOT_COMPLETED",
            candle_time=feature.candle_time,
            available_at=now.isoformat(),
            age_seconds=age,
            new_entries_allowed=False,
        )
    if age > max_completed_candle_age_seconds:
        return FuturesDataHealth(
            ok=False,
            status="FAIL",
            reason_code="FUTURES_VWAP_STALE",
            candle_time=feature.candle_time,
            available_at=now.isoformat(),
            age_seconds=age,
            new_entries_allowed=False,
        )

    return FuturesDataHealth(
        ok=True,
        status="PASS",
        reason_code=None,
        candle_time=feature.candle_time,
        available_at=now.isoformat(),
        age_seconds=age,
        new_entries_allowed=True,
    )


def health_to_dict(value: FuturesDataHealth) -> dict:
    return asdict(value)
