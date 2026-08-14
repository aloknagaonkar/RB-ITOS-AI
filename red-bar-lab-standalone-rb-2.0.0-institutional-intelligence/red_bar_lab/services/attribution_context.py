from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AttributionContext:
    regime_snapshot_id: str
    transition_id: str
    signal_id: str | None
    candidate_id: str | None
    opportunity_id: str | None
    committee_decision_id: str | None
    trade_id: str | None
    primary_trigger: str | None
    supporting_signals: tuple[str, ...]
    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "supporting_signals": list(self.supporting_signals),
            "execution_allowed": False,
        }


def build_attribution_context(
    regime_snapshot: Mapping[str, object],
    transition: Mapping[str, object],
) -> AttributionContext:
    timestamp = str(regime_snapshot.get("timestamp") or "")
    instrument = str(regime_snapshot.get("instrument_key") or "UNKNOWN")
    snapshot_id = f"REG-{instrument}-{timestamp}".replace(":", "").replace(" ", "_")

    return AttributionContext(
        regime_snapshot_id=snapshot_id,
        transition_id=str(transition.get("transition_id") or ""),
        signal_id=None,
        candidate_id=None,
        opportunity_id=None,
        committee_decision_id=None,
        trade_id=None,
        primary_trigger=None,
        supporting_signals=tuple(regime_snapshot.get("evidence") or []),
        execution_allowed=False,
    )
