from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VOLUME_APPLICABLE = "APPLICABLE"
VOLUME_NOT_APPLICABLE = "NOT_APPLICABLE"
VOLUME_MISSING = "MISSING"
VOLUME_INVALID = "INVALID"

_INDEX_PREFIXES = ("NSE_INDEX|", "BSE_INDEX|")


@dataclass(frozen=True)
class UnderlyingVolumeAuthority:
    status: str
    reason: str
    volume: float | None
    source: str

    @property
    def usable(self) -> bool:
        return self.status == VOLUME_APPLICABLE and self.volume is not None


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def is_cash_index_instrument(instrument_key: object) -> bool:
    key = str(instrument_key or "").strip().upper()
    return any(key.startswith(prefix) for prefix in _INDEX_PREFIXES)


def assess_underlying_volume_authority(
    *,
    instrument_key: object,
    volume: object,
) -> UnderlyingVolumeAuthority:
    """Classify whether underlying volume is meaningful for diagnostics.

    Cash index values are calculated indices rather than directly traded
    instruments. Their candle volume is therefore deliberately marked
    NOT_APPLICABLE instead of missing, zero, or weak. Traded instruments keep
    their reported volume and remain eligible for downstream volume analysis.
    """

    key = str(instrument_key or "").strip()
    if is_cash_index_instrument(key):
        return UnderlyingVolumeAuthority(
            status=VOLUME_NOT_APPLICABLE,
            reason=(
                "Cash index volume is not a traded-volume authority; use the "
                "active futures contract for volume and OI confirmation."
            ),
            volume=None,
            source="INDEX_PRICE_ONLY",
        )

    parsed = _number(volume)
    if parsed is None:
        return UnderlyingVolumeAuthority(
            status=VOLUME_MISSING,
            reason="Traded-instrument volume is missing.",
            volume=None,
            source="TRADED_INSTRUMENT",
        )
    if parsed < 0:
        return UnderlyingVolumeAuthority(
            status=VOLUME_INVALID,
            reason="Traded-instrument volume is negative or invalid.",
            volume=None,
            source="TRADED_INSTRUMENT",
        )

    return UnderlyingVolumeAuthority(
        status=VOLUME_APPLICABLE,
        reason="Traded-instrument volume is available.",
        volume=parsed,
        source="TRADED_INSTRUMENT",
    )
