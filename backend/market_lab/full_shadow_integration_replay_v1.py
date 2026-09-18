from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .live_nifty_futures_oi_producer_v1 import (
    CompletedFuturesCandle,
    LiveNiftyFuturesOIProducerV1,
)
from .live_normalized_feature_producer_v1 import (
    LiveNormalizedFeatureProducerV1,
)
from .live_observational_shadow_runtime_adapter_v1 import (
    ExactNextMinuteOpen,
    ExactOptionResolution,
    LiveShadowRuntimeAdapterV1,
)
from .live_option_minute_source_v1 import (
    CompletedOptionMinute,
    LiveOptionMinuteSourceV1,
)
from .live_shadow_source_integration_v1 import (
    attach_futures_state,
    to_shadow_option_minute,
)
from .live_normalized_shadow_bridge_v1 import to_shadow_checkpoint

MODEL = "FULL_SHADOW_INTEGRATION_REPLAY_V1"


@dataclass(frozen=True)
class ReplayResult:
    observation_id: str
    final_status: str
    exit_reason: str | None
    entry_price: float | None
    exit_price: float | None
    net_return_pct: float | None


class FullShadowIntegrationReplayV1:
    """
    Deterministic end-to-end replay for the observational shadow stack.

    No broker execution. No nearest-time/strike fallback.
    """

    def __init__(self, events_jsonl: str | Path):
        self.features = LiveNormalizedFeatureProducerV1()
        self.futures = LiveNiftyFuturesOIProducerV1()
        self.adapter = LiveShadowRuntimeAdapterV1(events_jsonl)

    def add_market_snapshot(self, snapshot):
        self.features.add_snapshot(snapshot)
        return self.features.build_current()

    def process_futures_candle(self, candle: CompletedFuturesCandle):
        return self.futures.process(candle)

    def detect_from_checkpoint(self, normalized):
        shadow_cp = to_shadow_checkpoint(
            normalized,
            futures_oi_state=None,
        )
        return self.adapter.on_new_all3(
            shadow_cp,
            normalized.previous_directional_all3,
        )

    def confirm_c2(
        self,
        observation_id: str,
        normalized_c2,
        futures_observation,
    ) -> str:
        base = to_shadow_checkpoint(
            normalized_c2,
            futures_oi_state=None,
        )
        enriched = attach_futures_state(base, futures_observation)
        return self.adapter.on_candle2(observation_id, enriched)

    def resolve_option(self, observation_id: str, normalized_c2) -> str:
        direction = self.adapter.states()[observation_id].direction
        instrument_key = (
            normalized_c2.ce_instrument_key
            if direction == "BULLISH"
            else normalized_c2.pe_instrument_key
        )
        if not instrument_key:
            self.adapter.shadow.incomplete(
                observation_id,
                normalized_c2.timestamp,
                "NO_EXACT_ATM_INSTRUMENT",
            )
            return "INCOMPLETE"

        return self.adapter.on_exact_option_resolved(
            observation_id,
            ExactOptionResolution(
                timestamp=normalized_c2.timestamp,
                atm_strike=normalized_c2.moving_atm,
                option_instrument_key=instrument_key,
            ),
        )

    def open_exact_next_minute(
        self,
        observation_id: str,
        *,
        timestamp,
        price: float,
    ) -> str:
        return self.adapter.on_exact_next_minute_open(
            observation_id,
            ExactNextMinuteOpen(timestamp=timestamp, price=price),
        )

    def replay_option_minutes(
        self,
        observation_id: str,
        bars: Iterable[CompletedOptionMinute],
    ) -> ReplayResult:
        state = self.adapter.states()[observation_id]
        if not state.option_instrument_key:
            raise ValueError("option must be resolved before option replay")

        source = LiveOptionMinuteSourceV1(state.option_instrument_key)

        for bar in bars:
            health = source.process(bar)
            if not health.allowed:
                self.adapter.shadow.incomplete(
                    observation_id,
                    bar.timestamp,
                    health.reason or "OPTION_MINUTE_UNHEALTHY",
                )
                break

            shadow_bar = to_shadow_option_minute(bar, health)
            status = self.adapter.on_option_minute(
                observation_id,
                shadow_bar,
            )
            if status in {"CLOSED", "REJECTED", "INCOMPLETE"}:
                break

        final = self.adapter.states()[observation_id]
        return ReplayResult(
            observation_id=observation_id,
            final_status=final.status,
            exit_reason=final.exit_reason,
            entry_price=final.entry_price,
            exit_price=final.exit_price,
            net_return_pct=final.net_return_pct,
        )
