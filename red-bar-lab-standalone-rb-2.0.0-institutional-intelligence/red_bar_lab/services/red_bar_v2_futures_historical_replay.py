from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import observe_trade_state
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2VwapSourceHealth,
    build_red_bar_v2_futures_snapshot,
)
from red_bar_lab.services.red_bar_v2_historical_replay import (
    RedBarV2ReplayResult,
    ReplayEvent,
    _event_is_due,
    _normalise,
    _trade_row,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2State,
    build_red_bar_v2_reference,
    evaluate_midpoint_upgrade,
)
from red_bar_lab.strategy.red_bar_v2_futures import (
    evaluate_initial_direction_futures,
    evaluate_reversal_direction_futures,
)


def replay_red_bar_v2_day_with_futures_vwap(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
    exit_timestamps: Iterable[datetime | pd.Timestamp] = (),
) -> tuple[RedBarV2ReplayResult, RedBarV2VwapSourceHealth]:
    """Replay Red Bar V2 with index RSI/midpoint and genuine futures VWAP.

    This historical-only entry point is additive. The stable single-source
    replay remains unchanged. Every evaluation uses completed candles only,
    requires matching latest timestamps and fails closed when futures volume
    or VWAP is unavailable.
    """
    frame = _normalise(index_candles)
    futures_frame = _normalise(futures_candles)
    exits = sorted(pd.Timestamp(value) for value in exit_timestamps)
    events: list[ReplayEvent] = []
    trade_rows: list[dict[str, object]] = []
    processed_candidates: set[str] = set()
    consumed_reversals: set[str] = set()
    processed_5m_contexts: set[str] = set()
    initial_processed = False
    pending_reversal: RedBarV2DirectionDecision | None = None
    current_direction: str | None = None
    provisional_state: RedBarV2State | None = None
    reference = None
    exit_index = 0
    admitted = 0
    blocked = 0
    closed = 0
    latest_health: RedBarV2VwapSourceHealth | None = None

    for candle_timestamp in frame.index:
        evaluation_time = pd.Timestamp(candle_timestamp) + pd.Timedelta(minutes=1)

        while exit_index < len(exits) and exits[exit_index] <= evaluation_time:
            active = next(
                (row for row in reversed(trade_rows) if row["status"] == "ACTIVE"),
                None,
            )
            if active is not None:
                active["status"] = "CLOSED"
                active["exit_timestamp"] = exits[exit_index].to_pydatetime()
                active["updated_at"] = exits[exit_index].to_pydatetime()
                closed += 1
                events.append(
                    ReplayEvent(
                        timestamp=exits[exit_index].to_pydatetime(),
                        event_type="TRADE_CLOSED",
                        direction=current_direction,
                        option_side=str(active.get("option_side") or "") or None,
                        admission_code=None,
                        candidate_allowed=None,
                        trade_id=str(active["trade_id"]),
                        details={"source": "REPLAY_EXIT_FIXTURE"},
                    )
                )
            exit_index += 1

        reference = build_red_bar_v2_reference(
            frame,
            instrument_key=instrument_key,
            evaluation_time=evaluation_time,
        )
        if reference is None:
            continue

        trade_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
        decision: RedBarV2DirectionDecision | None = None
        decision_health: RedBarV2VwapSourceHealth | None = None

        if pending_reversal is not None:
            decision = pending_reversal
        elif current_direction is None and not initial_processed:
            snapshot, decision_health = build_red_bar_v2_futures_snapshot(
                frame,
                futures_frame,
                instrument_key=instrument_key,
                vwap_instrument_key=vwap_instrument_key,
                timeframe="1M",
                evaluation_time=evaluation_time,
                expected_timestamp=candle_timestamp,
            )
            latest_health = decision_health
            initial = evaluate_initial_direction_futures(reference, snapshot)
            if _event_is_due(initial, evaluation_time):
                decision = initial
                if initial.direction is not None:
                    initial_processed = True
        elif current_direction is not None and evaluation_time.minute % 5 == 0:
            snapshot, decision_health = build_red_bar_v2_futures_snapshot(
                frame,
                futures_frame,
                instrument_key=instrument_key,
                vwap_instrument_key=vwap_instrument_key,
                timeframe="5M",
                evaluation_time=evaluation_time,
                expected_timestamp=evaluation_time - pd.Timedelta(minutes=5),
            )
            latest_health = decision_health
            if snapshot is not None:
                key = snapshot.candle_timestamp.isoformat()
                if key not in processed_5m_contexts:
                    processed_5m_contexts.add(key)
                    reversal = evaluate_reversal_direction_futures(
                        reference,
                        snapshot,
                        previous_direction=current_direction,
                    )
                    if (
                        reversal.direction is not None
                        and reversal.direction != current_direction
                        and _event_is_due(reversal, evaluation_time)
                    ):
                        decision = reversal
                        pending_reversal = reversal

        if decision is not None:
            admission = evaluate_candidate_admission(
                decision,
                trade_state,
                duplicate_signal=False,
                reversal_already_consumed=False,
            )
            duplicate = admission.decision_id in processed_candidates
            consumed = bool(
                admission.reversal_event_id
                and admission.reversal_event_id in consumed_reversals
            )
            admission = evaluate_candidate_admission(
                decision,
                trade_state,
                duplicate_signal=duplicate,
                reversal_already_consumed=consumed,
            )

            if admission.candidate_allowed:
                processed_candidates.add(admission.decision_id)
                if admission.reversal_event_id:
                    consumed_reversals.add(admission.reversal_event_id)
                admitted += 1
                trade_id = f"RBV2-FVWAP-{admitted:04d}"
                row = _trade_row(
                    trade_id,
                    admission,
                    evaluation_time.to_pydatetime(),
                )
                row["instrument_key"] = instrument_key
                trade_rows.append(row)
                current_direction = admission.direction
                provisional_state = (
                    RedBarV2State.PROVISIONAL_BULLISH
                    if admission.direction == "BULLISH"
                    and admission.trend_strength == "PROVISIONAL"
                    else RedBarV2State.PROVISIONAL_BEARISH
                    if admission.direction == "BEARISH"
                    and admission.trend_strength == "PROVISIONAL"
                    else None
                )
                pending_reversal = None
            else:
                blocked += 1
                trade_id = None
                if admission.admission_code not in {
                    AdmissionCode.ACTIVE_TRADE_BLOCK,
                    AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED,
                }:
                    pending_reversal = None

            details = {
                "entry_type": admission.entry_type,
                "trend_strength": admission.trend_strength,
                "decision_id": admission.decision_id,
                "reversal_event_id": admission.reversal_event_id,
                "admission_reason": admission.admission_reason,
                "reference_timestamp": admission.reference_timestamp,
                "context_timestamp": admission.context_timestamp,
                "active_trade_count": admission.active_trade_count,
                "previous_trade_status": admission.previous_trade_status,
                "conditions": dict(admission.conditions),
                "price_source_instrument": instrument_key,
                "rsi_source_instrument": instrument_key,
                "vwap_source_instrument": vwap_instrument_key,
                "execution_scope": "HISTORICAL_REPLAY_ONLY",
            }
            if decision_health is not None:
                details["vwap_source_health"] = decision_health.to_dict()
            events.append(
                ReplayEvent(
                    timestamp=evaluation_time.to_pydatetime(),
                    event_type="CANDIDATE_ADMISSION",
                    direction=admission.direction,
                    option_side=admission.option_side,
                    admission_code=admission.admission_code.value,
                    candidate_allowed=admission.candidate_allowed,
                    trade_id=trade_id,
                    details=details,
                )
            )

        if provisional_state is not None:
            active_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
            if active_state.active_trade is not None:
                snapshot, health = build_red_bar_v2_futures_snapshot(
                    frame,
                    futures_frame,
                    instrument_key=instrument_key,
                    vwap_instrument_key=vwap_instrument_key,
                    timeframe="1M",
                    evaluation_time=evaluation_time,
                    expected_timestamp=candle_timestamp,
                )
                latest_health = health
                upgrade = evaluate_midpoint_upgrade(
                    reference,
                    snapshot,
                    current_state=provisional_state,
                )
                if (
                    upgrade.event_type.value == "FULL_DIRECTIONAL_ALIGNMENT"
                    and _event_is_due(upgrade, evaluation_time)
                ):
                    events.append(
                        ReplayEvent(
                            timestamp=evaluation_time.to_pydatetime(),
                            event_type="STATE_UPGRADE",
                            direction=upgrade.direction,
                            option_side=upgrade.option_side,
                            admission_code=AdmissionCode.FULL_DIRECTIONAL_ALIGNMENT.value,
                            candidate_allowed=False,
                            trade_id=active_state.active_trade.trade_id,
                            details={
                                "from": provisional_state.value,
                                "to": upgrade.state.value,
                                "vwap_source_health": health.to_dict(),
                            },
                        )
                    )
                    provisional_state = None

    if latest_health is None:
        _, latest_health = build_red_bar_v2_futures_snapshot(
            frame,
            futures_frame,
            instrument_key=instrument_key,
            vwap_instrument_key=vwap_instrument_key,
            timeframe="1M",
            evaluation_time=pd.Timestamp(frame.index[-1]) + pd.Timedelta(minutes=1),
            expected_timestamp=frame.index[-1],
        )

    final_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
    trading_date = pd.Timestamp(frame.index[0]).date().isoformat()
    result = RedBarV2ReplayResult(
        instrument_key=instrument_key,
        trading_date=trading_date,
        reference_timestamp=reference.reference_timestamp if reference else None,
        reference_midpoint=reference.midpoint if reference else None,
        events=tuple(events),
        admitted_candidates=admitted,
        blocked_candidates=blocked,
        closed_trades=closed,
        final_trade_state=final_state.lifecycle_state.value,
    )
    return result, latest_health
