from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from red_bar_lab.intelligence.directional_features import latest_directional_features
from red_bar_lab.intelligence.directional_regime import classify_directional_regime
from red_bar_lab.intelligence.directional_transition import (
    ShadowDirectionalTransition,
    evaluate_shadow_directional_transition,
)


@dataclass(frozen=True)
class ShadowDirectionalService:
    """Observation-only façade for Sprint 4.2.

    This service deliberately has no dependency on candidate generation,
    committee evaluation, portfolio risk, order placement, or exits.
    """

    def evaluate(
        self,
        completed_five_minute_candles: pd.DataFrame,
        *,
        red_bar_context: Mapping[str, object] | None = None,
    ) -> ShadowDirectionalTransition:
        features = latest_directional_features(completed_five_minute_candles)
        regime = classify_directional_regime(features)
        return evaluate_shadow_directional_transition(
            features,
            regime=regime,
            red_bar_context=red_bar_context,
        )
