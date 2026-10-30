
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime

from .domain import IST, PCRConfig


@dataclass(frozen=True)
class MarketConfigurationGuard:
    ok: bool
    status: str
    reason_code: str | None
    configured_expiry: str
    today: str
    new_entries_allowed: bool


def validate_option_expiry(
    config: PCRConfig,
    *,
    today: date | None = None,
) -> MarketConfigurationGuard:
    today = today or datetime.now(IST).date()
    expiry = config.expiry
    if expiry < today:
        return MarketConfigurationGuard(
            ok=False,
            status="BLOCKED",
            reason_code="EXPIRED_OPTION_EXPIRY",
            configured_expiry=expiry.isoformat(),
            today=today.isoformat(),
            new_entries_allowed=False,
        )
    return MarketConfigurationGuard(
        ok=True,
        status="PASS",
        reason_code=None,
        configured_expiry=expiry.isoformat(),
        today=today.isoformat(),
        new_entries_allowed=True,
    )


def guard_to_dict(guard: MarketConfigurationGuard) -> dict:
    return asdict(guard)
