from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

RED_BAR = "RED_BAR"
DIRECTIONAL_REGIME = "DIRECTIONAL_REGIME"
RSI_EXTREME_REVERSAL = "RSI_EXTREME_REVERSAL"
VALID_STRATEGY_IDS = frozenset({RED_BAR, DIRECTIONAL_REGIME, RSI_EXTREME_REVERSAL})


@dataclass(frozen=True)
class StrategySignalBundle:
    bundle_id: str
    strategy_id: str
    instrument_key: str
    direction: str
    option_side: str
    detected_at: str
    fresh_until: str
    primary_signal_id: str
    primary_setup_type: str
    supporting_signal_ids: tuple[str, ...] = ()
    supporting_setup_types: tuple[str, ...] = ()
    trigger_level: float | None = None
    invalidation_level: float | None = None
    bundle_state: str = "CREATED"
    execution_allowed: bool = False
    entry_slots_allowed: int = 1
    entry_slots_consumed: int = 0
    canonical_event_identity: str = ""

    def __post_init__(self) -> None:
        if self.strategy_id not in VALID_STRATEGY_IDS:
            raise ValueError(f"Unsupported strategy_id: {self.strategy_id}")
        if self.direction not in {"BULLISH", "BEARISH"}:
            raise ValueError(f"Unsupported direction: {self.direction}")
        expected_side = "CE" if self.direction == "BULLISH" else "PE"
        if self.option_side != expected_side:
            raise ValueError(
                f"option_side={self.option_side} does not match direction={self.direction}"
            )
        if self.entry_slots_allowed < 1:
            raise ValueError("entry_slots_allowed must be at least one")
        if not 0 <= self.entry_slots_consumed <= self.entry_slots_allowed:
            raise ValueError("entry_slots_consumed must be within the allowed capacity")

    def as_record(self) -> dict[str, object]:
        return asdict(self)


def infer_strategy_id(record: Mapping[str, object]) -> str:
    """Infer ownership for legacy records without rewriting historical data."""
    explicit = str(record.get("strategy_id") or "").upper().strip()
    if explicit in VALID_STRATEGY_IDS:
        return explicit
    source = str(record.get("signal_source") or record.get("source") or "").upper()
    bundle_id = str(record.get("bundle_id") or "").upper()
    if "RSI_EXTREME_REVERSAL" in source or bundle_id.startswith("RSI-BND-"):
        return RSI_EXTREME_REVERSAL
    if source in {"RED_BAR", "NEXT_RED_CANDLE"} or bundle_id.startswith("RB-BND-"):
        return RED_BAR
    return DIRECTIONAL_REGIME
