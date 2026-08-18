from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    CandidateAdmissionDecision,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import TradeStateSnapshot, observe_trade_state
from red_bar_lab.intelligence.market_context import MarketIndicatorSnapshot, build_latest_snapshot
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2State,
    build_red_bar_v2_reference,
    evaluate_initial_direction,
    evaluate_midpoint_upgrade,
    evaluate_reversal_direction,
)


@dataclass(frozen=True)
class RedBarV2WorkerConfig:
    enabled: bool = False
    shadow_only: bool = True
    strategy_version: str = "RED_BAR_V2"
    worker_name: str = "RED_BAR_V2_SHADOW_WORKER"


@dataclass(frozen=True)
class RedBarV2WorkerState:
    directional_state: RedBarV2State = RedBarV2State.NEUTRAL
    previous_direction: str | None = None
    processed_candidate_ids: frozenset[str] = frozenset()
    consumed_reversal_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RedBarV2WorkerEvent:
    worker_name: str
    strategy_version: str
    evaluated_at: datetime
    status: str
    direction_decision: RedBarV2DirectionDecision | None
    admission_decision: CandidateAdmissionDecision | None
    trade_state: TradeStateSnapshot | None
    next_state: RedBarV2WorkerState
    execution_requested: bool = False

    def to_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["evaluated_at"] = self.evaluated_at.isoformat()
        if self.direction_decision is not None:
            row["direction_decision"]["event_type"] = self.direction_decision.event_type.value
            row["direction_decision"]["state"] = self.direction_decision.state.value
        if self.admission_decision is not None:
            row["admission_decision"]["admission_code"] = self.admission_decision.admission_code.value
        row["next_state"]["directional_state"] = self.next_state.directional_state.value
        row["next_state"]["processed_candidate_ids"] = sorted(self.next_state.processed_candidate_ids)
        row["next_state"]["consumed_reversal_ids"] = sorted(self.next_state.consumed_reversal_ids)
        return row


class RedBarV2ShadowWorker:
    """Independent, side-effect-free Red Bar V2 strategy worker.

    The worker consumes immutable candle and execution snapshots and returns an
    immutable event plus proposed next state. It never writes to a database,
    opens an order, closes a position, or mutates the caller-provided state.
    """

    def __init__(self, *, config: RedBarV2WorkerConfig | None = None):
        self.config = config or RedBarV2WorkerConfig()

    def evaluate(
        self,
        *,
        candles: pd.DataFrame,
        instrument_key: str,
        evaluation_time: datetime | pd.Timestamp,
        trade_rows: Iterable[Mapping[str, Any]],
        state: RedBarV2WorkerState | None = None,
    ) -> RedBarV2WorkerEvent:
        current = state or RedBarV2WorkerState()
        evaluated_at = pd.Timestamp(evaluation_time).to_pydatetime()
        if not self.config.enabled:
            return RedBarV2WorkerEvent(
                worker_name=self.config.worker_name,
                strategy_version=self.config.strategy_version,
                evaluated_at=evaluated_at,
                status="DISABLED",
                direction_decision=None,
                admission_decision=None,
                trade_state=None,
                next_state=current,
                execution_requested=False,
            )

        reference = build_red_bar_v2_reference(
            candles,
            instrument_key=instrument_key,
            evaluation_time=evaluation_time,
        )
        trade_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
        direction = self._direction_decision(
            candles=candles,
            instrument_key=instrument_key,
            evaluation_time=evaluation_time,
            reference=reference,
            state=current,
        )

        preliminary = evaluate_candidate_admission(
            direction,
            trade_state,
            strategy_version=self.config.strategy_version,
        )
        admission = evaluate_candidate_admission(
            direction,
            trade_state,
            duplicate_signal=preliminary.decision_id in current.processed_candidate_ids,
            reversal_already_consumed=bool(
                preliminary.reversal_event_id
                and preliminary.reversal_event_id in current.consumed_reversal_ids
            ),
            strategy_version=self.config.strategy_version,
        )
        next_state = self._next_state(current, direction, admission)

        if direction.entry_type == "STATE_UPGRADE" and direction.midpoint_aligned:
            status = "STATE_UPGRADED"
        elif admission.candidate_allowed:
            status = "SHADOW_ADMITTED" if self.config.shadow_only else "EXECUTION_REQUESTED"
        else:
            status = "BLOCKED"

        return RedBarV2WorkerEvent(
            worker_name=self.config.worker_name,
            strategy_version=self.config.strategy_version,
            evaluated_at=evaluated_at,
            status=status,
            direction_decision=direction,
            admission_decision=admission,
            trade_state=trade_state,
            next_state=next_state,
            execution_requested=bool(admission.candidate_allowed and not self.config.shadow_only),
        )

    def _direction_decision(
        self,
        *,
        candles: pd.DataFrame,
        instrument_key: str,
        evaluation_time: datetime | pd.Timestamp,
        reference: Any,
        state: RedBarV2WorkerState,
    ) -> RedBarV2DirectionDecision:
        if state.directional_state in {
            RedBarV2State.PROVISIONAL_BULLISH,
            RedBarV2State.PROVISIONAL_BEARISH,
        }:
            snapshot = self._snapshot(
                candles=candles,
                instrument_key=instrument_key,
                evaluation_time=evaluation_time,
                timeframe="1M",
            )
            return evaluate_midpoint_upgrade(
                reference,
                snapshot,
                current_state=state.directional_state,
            )

        if state.previous_direction:
            snapshot = self._snapshot(
                candles=candles,
                instrument_key=instrument_key,
                evaluation_time=evaluation_time,
                timeframe="5M",
            )
            return evaluate_reversal_direction(
                reference,
                snapshot,
                previous_direction=state.previous_direction,
            )

        snapshot = self._snapshot(
            candles=candles,
            instrument_key=instrument_key,
            evaluation_time=evaluation_time,
            timeframe="1M",
        )
        return evaluate_initial_direction(reference, snapshot)

    @staticmethod
    def _snapshot(
        *,
        candles: pd.DataFrame,
        instrument_key: str,
        evaluation_time: datetime | pd.Timestamp,
        timeframe: str,
    ) -> MarketIndicatorSnapshot | None:
        interval = 1 if timeframe == "1M" else 5
        return build_latest_snapshot(
            candles,
            instrument_key=instrument_key,
            timeframe=timeframe,
            evaluation_time=evaluation_time,
            expected_timestamp=pd.Timestamp(evaluation_time) - pd.Timedelta(minutes=interval),
        )

    @staticmethod
    def _next_state(
        current: RedBarV2WorkerState,
        direction: RedBarV2DirectionDecision,
        admission: CandidateAdmissionDecision,
    ) -> RedBarV2WorkerState:
        processed = set(current.processed_candidate_ids)
        consumed = set(current.consumed_reversal_ids)
        next_direction = current.previous_direction
        next_directional_state = current.directional_state

        if direction.entry_type == "STATE_UPGRADE" and direction.midpoint_aligned:
            next_directional_state = direction.state
            next_direction = direction.direction or next_direction
        elif admission.candidate_allowed:
            processed.add(admission.decision_id)
            if admission.reversal_event_id:
                consumed.add(admission.reversal_event_id)
            next_directional_state = direction.state
            next_direction = direction.direction

        return RedBarV2WorkerState(
            directional_state=next_directional_state,
            previous_direction=next_direction,
            processed_candidate_ids=frozenset(processed),
            consumed_reversal_ids=frozenset(consumed),
        )
