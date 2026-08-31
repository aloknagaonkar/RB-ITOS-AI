from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

import pandas as pd

from red_bar_lab.intelligence.shadow_directional_service import (
    ShadowDirectionalService,
)
from red_bar_lab.services.shadow_directional_store import ShadowDirectionalStore


@dataclass(frozen=True)
class ShadowDirectionalObservationService:
    store: ShadowDirectionalStore
    engine: ShadowDirectionalService = field(
        default_factory=ShadowDirectionalService
    )

    def evaluate_and_store(
        self,
        *,
        instrument_key: str,
        completed_five_minute_candles: pd.DataFrame,
        red_bar_context: Mapping[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> tuple[dict[str, object], bool]:
        transition = self.engine.evaluate(
            completed_five_minute_candles,
            red_bar_context=red_bar_context,
        )
        record = transition.as_record()
        record.update(
            {
                "instrument_key": instrument_key,
                "candle_timestamp": record.get("timestamp"),
                "observed_at": (observed_at or datetime.now()).isoformat(),
                "execution_allowed": False,
                "source": "SHADOW_DIRECTIONAL_TRANSITION_ENGINE",
            }
        )
        inserted = self.store.append_once(record)
        return record, inserted
