from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    CandidateAdmissionDecision,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import observe_trade_state
from red_bar_lab.intelligence.market_context import build_latest_snapshot
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2State,
    build_red_bar_v2_reference,
    evaluate_initial_direction,
    evaluate_midpoint_upgrade,
    evaluate_reversal_direction,
)


@dataclass(frozen=True)
class RedBarV2LegacyConfig:
    enabled: bool = False
    execution_enabled: bool = False
    strategy_version: str = "RED_BAR_V2"


@dataclass(frozen=True)
class RedBarV2LegacyResult:
    enabled: bool
    execution_enabled: bool
    direction_decision: RedBarV2DirectionDecision | None
    admission_decision: CandidateAdmissionDecision | None
    order: Mapping[str, Any] | None
    status: str


class RedBarV2LegacyAdapter:
    """Additive bridge from Red Bar V2 decisions to the legacy paper engine.

    The adapter never closes positions and never changes the legacy exit path.
    Execution is opt-in and defaults to shadow-only evaluation.
    """

    def __init__(self, *, config: RedBarV2LegacyConfig | None = None):
        self.config = config or RedBarV2LegacyConfig()

    def evaluate(
        self,
        *,
        candles: pd.DataFrame,
        instrument_key: str,
        evaluation_time: datetime | pd.Timestamp,
        trade_rows: Iterable[Mapping[str, Any]],
        previous_direction: str | None = None,
        current_state: RedBarV2State | None = None,
        duplicate_signal: bool = False,
        reversal_already_consumed: bool = False,
    ) -> RedBarV2LegacyResult:
        if not self.config.enabled:
            return RedBarV2LegacyResult(
                enabled=False,
                execution_enabled=self.config.execution_enabled,
                direction_decision=None,
                admission_decision=None,
                order=None,
                status="DISABLED",
            )

        reference = build_red_bar_v2_reference(
            candles,
            instrument_key=instrument_key,
            evaluation_time=evaluation_time,
        )
        trade_state = observe_trade_state(trade_rows, instrument_key=instrument_key)

        if current_state in {
            RedBarV2State.PROVISIONAL_BULLISH,
            RedBarV2State.PROVISIONAL_BEARISH,
        }:
            snapshot = build_latest_snapshot(
                candles,
                instrument_key=instrument_key,
                timeframe="1M",
                evaluation_time=evaluation_time,
                expected_timestamp=pd.Timestamp(evaluation_time) - pd.Timedelta(minutes=1),
            )
            direction = evaluate_midpoint_upgrade(
                reference,
                snapshot,
                current_state=current_state,
            )
        elif previous_direction:
            snapshot = build_latest_snapshot(
                candles,
                instrument_key=instrument_key,
                timeframe="5M",
                evaluation_time=evaluation_time,
                expected_timestamp=pd.Timestamp(evaluation_time) - pd.Timedelta(minutes=5),
            )
            direction = evaluate_reversal_direction(
                reference,
                snapshot,
                previous_direction=previous_direction,
            )
        else:
            snapshot = build_latest_snapshot(
                candles,
                instrument_key=instrument_key,
                timeframe="1M",
                evaluation_time=evaluation_time,
                expected_timestamp=pd.Timestamp(evaluation_time) - pd.Timedelta(minutes=1),
            )
            direction = evaluate_initial_direction(reference, snapshot)

        admission = evaluate_candidate_admission(
            direction,
            trade_state,
            duplicate_signal=duplicate_signal,
            reversal_already_consumed=reversal_already_consumed,
            strategy_version=self.config.strategy_version,
        )
        status = "ADMITTED" if admission.candidate_allowed else "BLOCKED"
        if admission.candidate_allowed and not self.config.execution_enabled:
            status = "SHADOW_ADMITTED"

        return RedBarV2LegacyResult(
            enabled=True,
            execution_enabled=self.config.execution_enabled,
            direction_decision=direction,
            admission_decision=admission,
            order=None,
            status=status,
        )

    def execute_admitted(
        self,
        *,
        result: RedBarV2LegacyResult,
        paper_engine: Any,
        zerodha: Any,
        contract: Any,
        quantity: int,
        underlying_name: str,
        underlying_price: float | None,
        stop_price: float | None = None,
        target1_price: float | None = None,
        target2_price: float | None = None,
    ) -> RedBarV2LegacyResult:
        admission = result.admission_decision
        if not result.enabled or not self.config.execution_enabled:
            return result
        if admission is None or not admission.candidate_allowed:
            return result

        order = paper_engine.open_long_option(
            zerodha=zerodha,
            contract=contract,
            quantity=quantity,
            signal_id=admission.decision_id,
            underlying_name=underlying_name,
            underlying_price=underlying_price,
            stop_price=stop_price,
            target1_price=target1_price,
            target2_price=target2_price,
            reason=f"{self.config.strategy_version}:{admission.admission_code.value}",
            policy_metadata={
                "execution_strategy_source": self.config.strategy_version,
                "signal_sources": [self.config.strategy_version],
                "merge_status": "LEGACY_ADAPTER",
            },
        )
        return RedBarV2LegacyResult(
            enabled=True,
            execution_enabled=True,
            direction_decision=result.direction_decision,
            admission_decision=admission,
            order=order,
            status="ORDER_OPENED",
        )
