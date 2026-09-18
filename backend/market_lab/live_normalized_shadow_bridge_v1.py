from __future__ import annotations

from .live_normalized_feature_producer_v1 import LiveNormalizedCheckpoint
from .live_observational_shadow_runtime_adapter_v1 import (
    CompletedFiveMinuteCheckpoint,
)


def to_shadow_checkpoint(
    checkpoint: LiveNormalizedCheckpoint,
    *,
    futures_oi_state: str | None,
) -> CompletedFiveMinuteCheckpoint:
    """
    Convert a normalized ALL_3 checkpoint into the existing shadow adapter input.

    Futures OI is an explicit external dependency because the current production
    Snapshot collector does not contain a futures instrument/candle stream.
    """
    return CompletedFiveMinuteCheckpoint(
        session_date=checkpoint.session_date,
        timestamp=checkpoint.timestamp,
        all3_state=checkpoint.all3_state,
        spot=checkpoint.spot,
        futures_oi_state=futures_oi_state,
    )
