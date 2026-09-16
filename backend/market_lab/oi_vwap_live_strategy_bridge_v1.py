
from __future__ import annotations

from dataclasses import asdict

from .oi_vwap_live_feature_engine_v1 import OICheckpointFeature
from .oi_vwap_persistence_option_buying_v1 import (
    OICheckpoint,
    VWAPContext,
    OIVWAPPersistenceStrategyV1,
)


def to_strategy_checkpoint(
    current: OICheckpointFeature,
    *,
    previous_imbalance_5m: float,
) -> OICheckpoint:
    if current.previous_session_imbalance is None:
        raise ValueError("previous session imbalance unavailable")
    if current.pcr_change_5m is None:
        raise ValueError("PCR 5m change unavailable")

    return OICheckpoint(
        timestamp=current.timestamp,
        previous_imbalance_5m=previous_imbalance_5m,
        current_imbalance_5m=current.imbalance_5m,
        pcr_change_5m=current.pcr_change_5m,
        previous_session_imbalance=current.previous_session_imbalance,
        current_session_imbalance=current.session_imbalance,
        ce_delta_5m=current.ce_delta_5m,
        pe_delta_5m=current.pe_delta_5m,
    )


def to_strategy_vwap(feature) -> VWAPContext:
    return VWAPContext(
        candle_time=feature.candle_time,
        available_at=feature.available_at,
        close=feature.close,
        vwap=feature.cumulative_vwap,
    )
