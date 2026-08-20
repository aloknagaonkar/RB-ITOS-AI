from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

CANDLE_READY = "READY"
CANDLE_CURRENT_INCOMPLETE = "CURRENT_CANDLE_INCOMPLETE"
CANDLE_STALE = "STALE"
CANDLE_MARKET_CLOSED = "MARKET_CLOSED"
CANDLE_MISSING = "MISSING"
CANDLE_INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
CANDLE_TIMESTAMP_MISMATCH = "TIMESTAMP_MISMATCH"


@dataclass(frozen=True)
class UnderlyingCandleReadiness:
    status: str
    reason: str
    latest_timestamp: str | None = None
    candle_age_seconds: float | None = None
    expected_completed_timestamp: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == CANDLE_READY


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        number = float(value)
        if abs(number) > 10_000_000_000:
            number /= 1000.0
        try:
            parsed = datetime.fromtimestamp(number, tz=IST)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def _timestamp_from_candle(candle: object) -> object:
    if isinstance(candle, Mapping):
        for name in (
            "timestamp",
            "time",
            "datetime",
            "date",
            "candle_timestamp",
        ):
            if name in candle:
                return candle.get(name)
        return None
    if isinstance(candle, Sequence) and not isinstance(candle, (str, bytes)):
        return candle[0] if candle else None
    return None


def _market_window(now: datetime) -> tuple[datetime, datetime]:
    day = now.date()
    return (
        datetime.combine(day, time(9, 15), tzinfo=IST),
        datetime.combine(day, time(15, 30), tzinfo=IST),
    )


def assess_underlying_candle_freshness(
    candles: Sequence[object],
    *,
    now: datetime | None = None,
    interval_minutes: int = 1,
    stale_after_seconds: int = 120,
) -> UnderlyingCandleReadiness:
    """Assess the latest completed underlying candle without execution authority.

    The current in-progress interval is excluded. Outside cash-market hours the
    result is MARKET_CLOSED rather than STALE so historical end-of-session data
    is not misclassified as a provider failure.
    """

    observed = (now or datetime.now(IST)).astimezone(IST)
    interval = max(1, int(interval_minutes))
    stale_after = max(interval * 60, int(stale_after_seconds))

    market_open, market_close = _market_window(observed)
    if observed < market_open or observed > market_close + timedelta(minutes=interval):
        return UnderlyingCandleReadiness(
            CANDLE_MARKET_CLOSED,
            "Underlying candle freshness is not evaluated outside market hours.",
        )

    if not candles:
        return UnderlyingCandleReadiness(
            CANDLE_MISSING,
            "Underlying candle collection is empty.",
        )

    parsed: list[datetime] = []
    invalid_count = 0
    for candle in candles:
        timestamp = _parse_timestamp(_timestamp_from_candle(candle))
        if timestamp is None:
            invalid_count += 1
        else:
            parsed.append(timestamp)

    if not parsed:
        return UnderlyingCandleReadiness(
            CANDLE_INVALID_TIMESTAMP,
            "No underlying candle contains a valid timestamp.",
        )

    latest = max(parsed)
    interval_delta = timedelta(minutes=interval)
    current_bucket = observed.replace(second=0, microsecond=0)
    current_bucket -= timedelta(minutes=current_bucket.minute % interval)
    expected_completed = current_bucket - interval_delta

    # A provider can include the currently forming candle. Record that fact,
    # but use the preceding completed candle to assess actual freshness.
    completed = [timestamp for timestamp in parsed if timestamp <= expected_completed]
    has_current = any(timestamp > expected_completed for timestamp in parsed)
    if not completed:
        if has_current:
            return UnderlyingCandleReadiness(
                CANDLE_CURRENT_INCOMPLETE,
                "Only the current incomplete underlying candle is available.",
                latest_timestamp=latest.isoformat(),
                expected_completed_timestamp=expected_completed.isoformat(),
            )
        return UnderlyingCandleReadiness(
            CANDLE_TIMESTAMP_MISMATCH,
            "Underlying candles do not align with the expected completed interval.",
            latest_timestamp=latest.isoformat(),
            expected_completed_timestamp=expected_completed.isoformat(),
        )

    latest_completed = max(completed)
    age = max(0.0, (observed - latest_completed).total_seconds())
    lag = (expected_completed - latest_completed).total_seconds()

    if latest_completed.date() != observed.date():
        return UnderlyingCandleReadiness(
            CANDLE_TIMESTAMP_MISMATCH,
            "Latest completed underlying candle belongs to a different trading date.",
            latest_timestamp=latest_completed.isoformat(),
            candle_age_seconds=age,
            expected_completed_timestamp=expected_completed.isoformat(),
        )

    if lag > stale_after:
        return UnderlyingCandleReadiness(
            CANDLE_STALE,
            f"Latest completed underlying candle lags the expected interval by {lag:.0f} seconds.",
            latest_timestamp=latest_completed.isoformat(),
            candle_age_seconds=age,
            expected_completed_timestamp=expected_completed.isoformat(),
        )

    suffix = " Current incomplete candle was ignored." if has_current else ""
    return UnderlyingCandleReadiness(
        CANDLE_READY,
        "Latest completed underlying candle is aligned with the market interval." + suffix,
        latest_timestamp=latest_completed.isoformat(),
        candle_age_seconds=age,
        expected_completed_timestamp=expected_completed.isoformat(),
    )
