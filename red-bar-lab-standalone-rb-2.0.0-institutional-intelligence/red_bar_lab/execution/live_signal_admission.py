from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


class AdmissionMode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


@dataclass(frozen=True)
class LiveSignalAdmissionDecision:
    allowed: bool
    decision: str
    reason: str
    mode: AdmissionMode
    signal_age_seconds: float | None
    market_hours_ok: bool
    freshness_ok: bool
    requires_opportunity_extension: bool


def _timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=IST)
    return stamp.astimezone(IST)


def _admission_mode(value: AdmissionMode | str) -> AdmissionMode:
    if isinstance(value, AdmissionMode):
        return value
    normalized = str(value).strip().upper()
    if normalized.startswith("ADMISSIONMODE."):
        normalized = normalized.split(".", 1)[1]
    return AdmissionMode(normalized)


def evaluate_live_signal_admission(
    *,
    confirmation_timestamp: object,
    now: datetime | None = None,
    mode: AdmissionMode | str = AdmissionMode.LIVE,
    max_signal_age_seconds: int = 180,
    allow_outside_market_hours: bool = False,
    allow_stale_signals: bool = False,
    enable_opportunity_extension: bool = True,
    market_open_time: time = time(9, 15),
    market_close_time: time = time(15, 25),
    already_executed: bool = False,
) -> LiveSignalAdmissionDecision:
    """Evaluate live admission without historical replay or performance evidence.

    This boundary intentionally accepts only current signal/session facts. Historical
    replay, historical win-rate, committee evidence and candidate ranking must not
    override its terminal decisions.
    """

    resolved_mode = _admission_mode(mode)
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)

    signal_time = _timestamp(confirmation_timestamp)
    if signal_time is None:
        return LiveSignalAdmissionDecision(
            allowed=False,
            decision="BLOCK",
            reason="SIGNAL_CONFIRMATION_TIMESTAMP_MISSING",
            mode=resolved_mode,
            signal_age_seconds=None,
            market_hours_ok=False,
            freshness_ok=False,
            requires_opportunity_extension=False,
        )

    age_seconds = (current - signal_time).total_seconds()
    if age_seconds < 0:
        return LiveSignalAdmissionDecision(
            allowed=False,
            decision="BLOCK",
            reason="SIGNAL_TIMESTAMP_IN_FUTURE",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=False,
            freshness_ok=False,
            requires_opportunity_extension=False,
        )

    if resolved_mode is AdmissionMode.REPLAY:
        return LiveSignalAdmissionDecision(
            allowed=True,
            decision="REPLAY_ONLY",
            reason="REPLAY_TIMESTAMP_ACCEPTED",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=True,
            freshness_ok=True,
            requires_opportunity_extension=False,
        )

    market_hours_ok = bool(
        current.weekday() < 5
        and market_open_time <= current.time() < market_close_time
    )
    if not market_hours_ok and not allow_outside_market_hours:
        return LiveSignalAdmissionDecision(
            allowed=False,
            decision="BLOCK",
            reason="OUTSIDE_AUTOMATIC_ENTRY_HOURS",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=False,
            freshness_ok=False,
            requires_opportunity_extension=False,
        )

    # A signal that already produced an order is still a valid live candidate
    # for monitoring (entry position management already happened). Do not
    # pathologicaly re-block/expire it on the 180-second age gate once the
    # order was opened; the freshness limit governs new entries, not
    # monitoring of an already-executed signal.
    if already_executed:
        return LiveSignalAdmissionDecision(
            allowed=True,
            decision="ADMIT",
            reason="SIGNAL_ALREADY_EXECUTED",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=market_hours_ok,
            freshness_ok=False,
            requires_opportunity_extension=False,
        )

    freshness_ok = age_seconds <= max(0, int(max_signal_age_seconds))
    if freshness_ok:
        return LiveSignalAdmissionDecision(
            allowed=True,
            decision="ADMIT",
            reason="LIVE_SIGNAL_FRESH",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=market_hours_ok,
            freshness_ok=True,
            requires_opportunity_extension=False,
        )

    if allow_stale_signals:
        return LiveSignalAdmissionDecision(
            allowed=True,
            decision="ADMIT_EXPLICIT_STALE_OVERRIDE",
            reason="STALE_SIGNAL_OVERRIDE_ENABLED",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=market_hours_ok,
            freshness_ok=False,
            requires_opportunity_extension=False,
        )

    if enable_opportunity_extension:
        return LiveSignalAdmissionDecision(
            allowed=True,
            decision="REQUIRE_OPPORTUNITY_EXTENSION",
            reason="STALE_SIGNAL_REQUIRES_LIVE_EXTENSION",
            mode=resolved_mode,
            signal_age_seconds=age_seconds,
            market_hours_ok=market_hours_ok,
            freshness_ok=False,
            requires_opportunity_extension=True,
        )

    return LiveSignalAdmissionDecision(
        allowed=False,
        decision="BLOCK",
        reason="MAX_SIGNAL_AGE_EXCEEDED",
        mode=resolved_mode,
        signal_age_seconds=age_seconds,
        market_hours_ok=market_hours_ok,
        freshness_ok=False,
        requires_opportunity_extension=False,
    )


__all__ = [
    "AdmissionMode",
    "LiveSignalAdmissionDecision",
    "evaluate_live_signal_admission",
]
