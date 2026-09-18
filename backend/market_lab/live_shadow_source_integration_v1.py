from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .live_nifty_futures_oi_producer_v1 import FuturesOIObservation
from .live_observational_shadow_runtime_adapter_v1 import (
    CompletedFiveMinuteCheckpoint,
    CompletedOptionMinute as ShadowOptionMinute,
)
from .live_option_minute_source_v1 import CompletedOptionMinute, OptionMinuteHealth


def attach_futures_state(
    checkpoint: CompletedFiveMinuteCheckpoint,
    futures: FuturesOIObservation,
) -> CompletedFiveMinuteCheckpoint:
    if not futures.health_allowed:
        raise ValueError(f"Futures data unhealthy: {futures.health_reason}")
    if futures.timestamp != checkpoint.timestamp:
        raise ValueError("Futures timestamp must exactly match shadow checkpoint timestamp")

    return CompletedFiveMinuteCheckpoint(
        session_date=checkpoint.session_date,
        timestamp=checkpoint.timestamp,
        all3_state=checkpoint.all3_state,
        spot=checkpoint.spot,
        futures_oi_state=futures.state,
    )


def to_shadow_option_minute(
    bar: CompletedOptionMinute,
    health: OptionMinuteHealth,
) -> ShadowOptionMinute:
    if not health.allowed:
        raise ValueError(f"Option minute unhealthy: {health.reason}")
    return ShadowOptionMinute(
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
    )
