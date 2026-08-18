from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

import pandas as pd

from red_bar_lab.execution.red_bar_v2_legacy_adapter import (
    RedBarV2LegacyAdapter,
    RedBarV2LegacyConfig,
    RedBarV2LegacyResult,
)
from red_bar_lab.services.red_bar_v2_shadow_worker import (
    RedBarV2ShadowWorker,
    RedBarV2WorkerConfig,
    RedBarV2WorkerEvent,
    RedBarV2WorkerState,
)
from red_bar_lab.strategy.red_bar_v2 import RedBarV2State


PARITY_FIELDS = (
    "event_type",
    "directional_state",
    "direction",
    "option_side",
    "entry_type",
    "trend_strength",
    "candidate_allowed",
    "admission_code",
    "decision_id",
    "reversal_event_id",
    "trade_lifecycle_state",
)


@dataclass(frozen=True)
class NormalizedParityDecision:
    event_type: str | None
    directional_state: str | None
    direction: str | None
    option_side: str | None
    entry_type: str | None
    trend_strength: str | None
    candidate_allowed: bool | None
    admission_code: str | None
    decision_id: str | None
    reversal_event_id: str | None
    trade_lifecycle_state: str | None
    semantic_status: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParityMismatch:
    field: str
    legacy_value: Any
    worker_value: Any


@dataclass(frozen=True)
class RedBarV2ParityReport:
    evaluated_at: datetime
    legacy: NormalizedParityDecision
    worker: NormalizedParityDecision
    matched: bool
    mismatches: tuple[ParityMismatch, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "matched": self.matched,
            "legacy": self.legacy.to_record(),
            "worker": self.worker.to_record(),
            "mismatches": [asdict(item) for item in self.mismatches],
        }


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _semantic_status(*, entry_type: str | None, midpoint_aligned: bool, allowed: bool | None) -> str:
    if entry_type == "STATE_UPGRADE" and midpoint_aligned:
        return "STATE_EVENT"
    if allowed:
        return "CANDIDATE_ADMITTED"
    return "CANDIDATE_BLOCKED"


def normalize_legacy_result(result: RedBarV2LegacyResult) -> NormalizedParityDecision:
    direction = result.direction_decision
    admission = result.admission_decision
    trade_state = None
    if admission is not None:
        trade_state = admission.conditions.get("trade_state")
    return NormalizedParityDecision(
        event_type=_value(direction.event_type) if direction else None,
        directional_state=_value(direction.state) if direction else None,
        direction=direction.direction if direction else None,
        option_side=direction.option_side if direction else None,
        entry_type=direction.entry_type if direction else None,
        trend_strength=direction.trend_strength if direction else None,
        candidate_allowed=admission.candidate_allowed if admission else None,
        admission_code=_value(admission.admission_code) if admission else None,
        decision_id=admission.decision_id if admission else None,
        reversal_event_id=admission.reversal_event_id if admission else None,
        trade_lifecycle_state=_value(trade_state),
        semantic_status=_semantic_status(
            entry_type=direction.entry_type if direction else None,
            midpoint_aligned=bool(direction and direction.midpoint_aligned),
            allowed=admission.candidate_allowed if admission else None,
        ),
    )


def normalize_worker_event(event: RedBarV2WorkerEvent) -> NormalizedParityDecision:
    direction = event.direction_decision
    admission = event.admission_decision
    return NormalizedParityDecision(
        event_type=_value(direction.event_type) if direction else None,
        directional_state=_value(direction.state) if direction else None,
        direction=direction.direction if direction else None,
        option_side=direction.option_side if direction else None,
        entry_type=direction.entry_type if direction else None,
        trend_strength=direction.trend_strength if direction else None,
        candidate_allowed=admission.candidate_allowed if admission else None,
        admission_code=_value(admission.admission_code) if admission else None,
        decision_id=admission.decision_id if admission else None,
        reversal_event_id=admission.reversal_event_id if admission else None,
        trade_lifecycle_state=(
            _value(event.trade_state.lifecycle_state) if event.trade_state is not None else None
        ),
        semantic_status=_semantic_status(
            entry_type=direction.entry_type if direction else None,
            midpoint_aligned=bool(direction and direction.midpoint_aligned),
            allowed=admission.candidate_allowed if admission else None,
        ),
    )


def compare_normalized(
    legacy: NormalizedParityDecision,
    worker: NormalizedParityDecision,
    *,
    evaluated_at: datetime | pd.Timestamp,
) -> RedBarV2ParityReport:
    mismatches = tuple(
        ParityMismatch(field=field, legacy_value=getattr(legacy, field), worker_value=getattr(worker, field))
        for field in (*PARITY_FIELDS, "semantic_status")
        if getattr(legacy, field) != getattr(worker, field)
    )
    return RedBarV2ParityReport(
        evaluated_at=pd.Timestamp(evaluated_at).to_pydatetime(),
        legacy=legacy,
        worker=worker,
        matched=not mismatches,
        mismatches=mismatches,
    )


def run_legacy_worker_parity(
    *,
    candles: pd.DataFrame,
    instrument_key: str,
    evaluation_time: datetime | pd.Timestamp,
    trade_rows: Iterable[Mapping[str, Any]],
    state: RedBarV2WorkerState | None = None,
    strategy_version: str = "RED_BAR_V2",
) -> RedBarV2ParityReport:
    current = state or RedBarV2WorkerState()
    rows = tuple(dict(row) for row in trade_rows)
    legacy = RedBarV2LegacyAdapter(
        config=RedBarV2LegacyConfig(
            enabled=True,
            execution_enabled=False,
            strategy_version=strategy_version,
        )
    ).evaluate(
        candles=candles,
        instrument_key=instrument_key,
        evaluation_time=evaluation_time,
        trade_rows=rows,
        previous_direction=current.previous_direction,
        current_state=(
            current.directional_state
            if current.directional_state
            in {RedBarV2State.PROVISIONAL_BULLISH, RedBarV2State.PROVISIONAL_BEARISH}
            else None
        ),
        duplicate_signal=False,
        reversal_already_consumed=False,
    )
    worker = RedBarV2ShadowWorker(
        config=RedBarV2WorkerConfig(
            enabled=True,
            shadow_only=True,
            strategy_version=strategy_version,
        )
    ).evaluate(
        candles=candles,
        instrument_key=instrument_key,
        evaluation_time=evaluation_time,
        trade_rows=rows,
        state=current,
    )
    return compare_normalized(
        normalize_legacy_result(legacy),
        normalize_worker_event(worker),
        evaluated_at=evaluation_time,
    )


def normalize_replay_candidate(event: Any) -> NormalizedParityDecision:
    details = dict(getattr(event, "details", {}) or {})
    return NormalizedParityDecision(
        event_type=details.get("event_type"),
        directional_state=details.get("directional_state"),
        direction=getattr(event, "direction", None),
        option_side=getattr(event, "option_side", None),
        entry_type=details.get("entry_type"),
        trend_strength=details.get("trend_strength"),
        candidate_allowed=getattr(event, "candidate_allowed", None),
        admission_code=getattr(event, "admission_code", None),
        decision_id=details.get("decision_id"),
        reversal_event_id=details.get("reversal_event_id"),
        trade_lifecycle_state=details.get("trade_lifecycle_state"),
        semantic_status=_semantic_status(
            entry_type=details.get("entry_type"),
            midpoint_aligned=bool(details.get("midpoint_aligned")),
            allowed=getattr(event, "candidate_allowed", None),
        ),
    )
