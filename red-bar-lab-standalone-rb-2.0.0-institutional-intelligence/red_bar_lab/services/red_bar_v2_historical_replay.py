from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    CandidateAdmissionDecision,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import observe_trade_state
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
class ReplayEvent:
    timestamp: datetime
    event_type: str
    direction: str | None
    option_side: str | None
    admission_code: str | None
    candidate_allowed: bool | None
    trade_id: str | None
    details: dict[str, object]


@dataclass(frozen=True)
class RedBarV2ReplayResult:
    instrument_key: str
    trading_date: str
    reference_timestamp: datetime | None
    reference_midpoint: float | None
    events: tuple[ReplayEvent, ...]
    admitted_candidates: int
    blocked_candidates: int
    closed_trades: int
    final_trade_state: str

    def to_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for event in self.events:
            row = asdict(event)
            row["timestamp"] = event.timestamp.isoformat()
            records.append(row)
        return records


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("Historical replay requires one-minute OHLCV candles.")
    data = frame.copy()
    if "timestamp" in data.columns:
        data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
        data = data.dropna(subset=["timestamp"]).set_index("timestamp")
    elif not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Candles require a timestamp column or DatetimeIndex.")
    required = ["open", "high", "low", "close", "volume"]
    missing = [name for name in required if name not in data.columns]
    if missing:
        raise ValueError(f"Missing replay columns: {', '.join(missing)}")
    return data.sort_index()[required].copy()


def _trade_row(trade_id: str, decision: CandidateAdmissionDecision, timestamp: datetime) -> dict[str, object]:
    return {
        "trade_id": trade_id,
        "instrument_key": decision.conditions.get("instrument_key"),
        "option_side": decision.option_side,
        "status": "ACTIVE",
        "entry_timestamp": timestamp,
        "updated_at": timestamp,
    }


def _event_is_due(decision: RedBarV2DirectionDecision, evaluation_time: pd.Timestamp) -> bool:
    if decision.context_timestamp is None:
        return False
    event_time = pd.Timestamp(decision.context_timestamp)
    if evaluation_time.tzinfo is not None and event_time.tzinfo is None:
        event_time = event_time.tz_localize(evaluation_time.tzinfo)
    elif evaluation_time.tzinfo is None and event_time.tzinfo is not None:
        event_time = event_time.tz_localize(None)
    return event_time <= evaluation_time


def _decision_evidence_details(
    *,
    decision: RedBarV2DirectionDecision,
    reference: object,
    context: MarketIndicatorSnapshot,
    underlying_instrument_key: str,
    futures_instrument_key: str,
) -> dict[str, object]:
    """Expose values already used by the frozen calculation; do not recalculate."""
    return {
        "underlying_instrument_key": underlying_instrument_key,
        "futures_instrument_key": futures_instrument_key,
        "evaluation_timeframe": "1m" if context.timeframe == "1M" else "5m",
        "index_close": float(decision.close_price),
        "rsi_value": float(decision.rsi_value),
        "bullish_rsi_threshold": 55.0,
        "bearish_rsi_threshold": 45.0,
        "futures_comparison_price": float(context.candle_close),
        "futures_vwap": float(decision.vwap_value),
        "futures_volume": float(context.candle_volume),
        "futures_fresh": bool(decision.context_fresh),
        "index_context_timestamp": context.candle_timestamp.isoformat(),
        "futures_source_timestamp": context.candle_timestamp.isoformat(),
        "reference_id": (
            f"RBV2-REF-{reference.trading_date}-"
            f"{reference.reference_timestamp.isoformat()}"
        ),
        "reference_high": float(reference.reference_high),
        "reference_low": float(reference.reference_low),
        "reference_midpoint": float(reference.midpoint),
        "reference_source": str(reference.level_type),
    }


def replay_red_bar_v2_day(
    candles: pd.DataFrame,
    *,
    instrument_key: str,
    exit_timestamps: Iterable[datetime | pd.Timestamp] = (),
    futures_instrument_key: str | None = None,
) -> RedBarV2ReplayResult:
    """Replay one session through validated V2 components without changing authority."""
    frame = _normalise(candles)
    evidence_futures_key = futures_instrument_key or instrument_key
    exits = sorted(pd.Timestamp(value) for value in exit_timestamps)
    events: list[ReplayEvent] = []
    trade_rows: list[dict[str, object]] = []
    processed_candidates: set[str] = set()
    consumed_reversals: set[str] = set()
    processed_5m_contexts: set[str] = set()
    initial_processed = False
    pending_reversal: RedBarV2DirectionDecision | None = None
    pending_reversal_context: MarketIndicatorSnapshot | None = None
    current_direction: str | None = None
    provisional_state: RedBarV2State | None = None
    reference = None
    exit_index = 0
    admitted = 0
    blocked = 0
    closed = 0

    for candle_timestamp in frame.index:
        evaluation_time = pd.Timestamp(candle_timestamp) + pd.Timedelta(minutes=1)

        while exit_index < len(exits) and exits[exit_index] <= evaluation_time:
            active = next((row for row in reversed(trade_rows) if row["status"] == "ACTIVE"), None)
            if active is not None:
                active["status"] = "CLOSED"
                active["exit_timestamp"] = exits[exit_index].to_pydatetime()
                active["updated_at"] = exits[exit_index].to_pydatetime()
                closed += 1
                events.append(ReplayEvent(
                    timestamp=exits[exit_index].to_pydatetime(),
                    event_type="TRADE_CLOSED",
                    direction=current_direction,
                    option_side=str(active.get("option_side") or "") or None,
                    admission_code=None,
                    candidate_allowed=None,
                    trade_id=str(active["trade_id"]),
                    details={"source": "REPLAY_EXIT_FIXTURE"},
                ))
            exit_index += 1

        reference = build_red_bar_v2_reference(frame, instrument_key=instrument_key, evaluation_time=evaluation_time)
        if reference is None:
            continue
        trade_state = observe_trade_state(trade_rows, instrument_key=instrument_key)

        decision: RedBarV2DirectionDecision | None = None
        decision_context: MarketIndicatorSnapshot | None = None
        if pending_reversal is not None:
            decision = pending_reversal
            decision_context = pending_reversal_context
        elif current_direction is None and not initial_processed:
            snapshot_1m = build_latest_snapshot(
                frame, instrument_key=instrument_key, timeframe="1M",
                evaluation_time=evaluation_time, expected_timestamp=candle_timestamp,
            )
            initial = evaluate_initial_direction(reference, snapshot_1m)
            if _event_is_due(initial, evaluation_time):
                decision = initial
                decision_context = snapshot_1m
                if initial.direction is not None:
                    initial_processed = True
        elif current_direction is not None and evaluation_time.minute % 5 == 0:
            snapshot_5m = build_latest_snapshot(
                frame, instrument_key=instrument_key, timeframe="5M",
                evaluation_time=evaluation_time,
                expected_timestamp=evaluation_time - pd.Timedelta(minutes=5),
            )
            if snapshot_5m is not None:
                key = snapshot_5m.candle_timestamp.isoformat()
                if key not in processed_5m_contexts:
                    processed_5m_contexts.add(key)
                    reversal = evaluate_reversal_direction(
                        reference, snapshot_5m, previous_direction=current_direction,
                    )
                    if reversal.direction is not None and reversal.direction != current_direction and _event_is_due(reversal, evaluation_time):
                        decision = reversal
                        decision_context = snapshot_5m
                        pending_reversal = reversal
                        pending_reversal_context = snapshot_5m

        if decision is not None:
            admission = evaluate_candidate_admission(decision, trade_state, duplicate_signal=False, reversal_already_consumed=False)
            duplicate = admission.decision_id in processed_candidates
            consumed = bool(admission.reversal_event_id and admission.reversal_event_id in consumed_reversals)
            admission = evaluate_candidate_admission(
                decision, trade_state, duplicate_signal=duplicate,
                reversal_already_consumed=consumed,
            )

            if admission.candidate_allowed:
                processed_candidates.add(admission.decision_id)
                if admission.reversal_event_id:
                    consumed_reversals.add(admission.reversal_event_id)
                admitted += 1
                trade_id = f"RBV2-{admitted:04d}"
                row = _trade_row(trade_id, admission, evaluation_time.to_pydatetime())
                row["instrument_key"] = instrument_key
                trade_rows.append(row)
                current_direction = admission.direction
                provisional_state = (
                    RedBarV2State.PROVISIONAL_BULLISH
                    if admission.direction == "BULLISH" and admission.trend_strength == "PROVISIONAL"
                    else RedBarV2State.PROVISIONAL_BEARISH
                    if admission.direction == "BEARISH" and admission.trend_strength == "PROVISIONAL"
                    else None
                )
                pending_reversal = None
                pending_reversal_context = None
            else:
                blocked += 1
                trade_id = None
                if admission.admission_code not in {AdmissionCode.ACTIVE_TRADE_BLOCK, AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED}:
                    pending_reversal = None
                    pending_reversal_context = None

            details: dict[str, object] = {
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
            }
            if decision_context is not None and decision.close_price is not None and decision.rsi_value is not None and decision.vwap_value is not None:
                details.update(_decision_evidence_details(
                    decision=decision,
                    reference=reference,
                    context=decision_context,
                    underlying_instrument_key=instrument_key,
                    futures_instrument_key=evidence_futures_key,
                ))
            events.append(ReplayEvent(
                timestamp=evaluation_time.to_pydatetime(),
                event_type="CANDIDATE_ADMISSION",
                direction=admission.direction,
                option_side=admission.option_side,
                admission_code=admission.admission_code.value,
                candidate_allowed=admission.candidate_allowed,
                trade_id=trade_id,
                details=details,
            ))

        if provisional_state is not None:
            active_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
            if active_state.active_trade is not None:
                snapshot_1m = build_latest_snapshot(
                    frame, instrument_key=instrument_key, timeframe="1M",
                    evaluation_time=evaluation_time, expected_timestamp=candle_timestamp,
                )
                upgrade = evaluate_midpoint_upgrade(reference, snapshot_1m, current_state=provisional_state)
                if upgrade.event_type.value == "FULL_DIRECTIONAL_ALIGNMENT" and _event_is_due(upgrade, evaluation_time):
                    events.append(ReplayEvent(
                        timestamp=evaluation_time.to_pydatetime(),
                        event_type="STATE_UPGRADE",
                        direction=upgrade.direction,
                        option_side=upgrade.option_side,
                        admission_code=AdmissionCode.FULL_DIRECTIONAL_ALIGNMENT.value,
                        candidate_allowed=False,
                        trade_id=active_state.active_trade.trade_id,
                        details={"from": provisional_state.value, "to": upgrade.state.value},
                    ))
                    provisional_state = None

    final_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
    trading_date = pd.Timestamp(frame.index[0]).date().isoformat()
    return RedBarV2ReplayResult(
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
