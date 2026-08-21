from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FeatureStoreReadiness:
    confirmed_signal_ids: tuple[str, ...]
    market_ready_ids: tuple[str, ...]
    volume_ready_ids: tuple[str, ...]
    option_ready_ids: tuple[str, ...]
    core_feature_ids: tuple[str, ...]
    hybrid_feature_ids: tuple[str, ...]

    @property
    def core_feature_count(self) -> int:
        return len(self.core_feature_ids)

    @property
    def hybrid_feature_count(self) -> int:
        return len(self.hybrid_feature_ids)


def _ids(values: Iterable[str]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def calculate_feature_store_readiness(
    *,
    confirmed_signal_ids: Iterable[str],
    market_ready_ids: Iterable[str],
    volume_ready_ids: Iterable[str],
    option_ready_ids: Iterable[str],
) -> FeatureStoreReadiness:
    """Calculate CORE/HYBRID readiness using exact signal-ID membership."""

    confirmed = _ids(confirmed_signal_ids)
    market = _ids(market_ready_ids) & confirmed
    volume = _ids(volume_ready_ids) & confirmed
    options = _ids(option_ready_ids) & confirmed
    core = market & volume
    hybrid = core & options

    ordered = lambda values: tuple(sorted(values))
    return FeatureStoreReadiness(
        confirmed_signal_ids=ordered(confirmed),
        market_ready_ids=ordered(market),
        volume_ready_ids=ordered(volume),
        option_ready_ids=ordered(options),
        core_feature_ids=ordered(core),
        hybrid_feature_ids=ordered(hybrid),
    )


__all__ = ["FeatureStoreReadiness", "calculate_feature_store_readiness"]
