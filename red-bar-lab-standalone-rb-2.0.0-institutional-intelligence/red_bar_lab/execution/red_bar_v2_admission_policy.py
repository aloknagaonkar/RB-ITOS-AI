from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from typing import Any

from red_bar_lab.execution.trade_state_observer import (
    TradeLifecycleState,
    TradeStateSnapshot,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2State,
)


class AdmissionCode(str, Enum):
    REFERENCE_NOT_READY = "REFERENCE_NOT_READY"
    INITIAL_BULLISH_ALIGNMENT = "INITIAL_BULLISH_ALIGNMENT"
    INITIAL_BEARISH_ALIGNMENT = "INITIAL_BEARISH_ALIGNMENT"
    REVERSAL_CONTEXT_ALIGNED_FLAT = "REVERSAL_CONTEXT_ALIGNED_FLAT"
    FULL_DIRECTIONAL_ALIGNMENT = "FULL_DIRECTIONAL_ALIGNMENT"
    ACTIVE_TRADE_BLOCK = "ACTIVE_TRADE_BLOCK"
    PREVIOUS_TRADE_NOT_CLOSED = "PREVIOUS_TRADE_NOT_CLOSED"
    RSI_NOT_ALIGNED = "RSI_NOT_ALIGNED"
    VWAP_NOT_ALIGNED = "VWAP_NOT_ALIGNED"
    MIDPOINT_NOT_ALIGNED = "MIDPOINT_NOT_ALIGNED"
    CONTEXT_STALE = "CONTEXT_STALE"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    REVERSAL_ALREADY_CONSUMED = "REVERSAL_ALREADY_CONSUMED"


@dataclass(frozen=True)
class CandidateAdmissionDecision:
    decision_id: str
    candidate_allowed: bool
    admission_code: AdmissionCode
    admission_reason: str
    strategy_version: str
    direction: str | None
    option_side: str | None
    entry_type: str | None
    trend_strength: str | None
    reference_timestamp: str | None
    context_timestamp: str | None
    active_trade_count: int
    previous_trade_status: str | None
    reversal_event_id: str | None
    conditions: dict[str, Any]

    def to_storage_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["admission_code"] = self.admission_code.value
        return payload


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else (str(value) if value is not None else None)


def build_candidate_identity(
    decision: RedBarV2DirectionDecision,
    *,
    strategy_version: str = "RED_BAR_V2",
) -> str:
    raw = "|".join(
        [
            strategy_version,
            decision.direction or "NONE",
            decision.event_type.value,
            _iso(decision.context_timestamp) or "NONE",
            _iso(decision.reference_timestamp) or "NONE",
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def build_reversal_event_id(
    decision: RedBarV2DirectionDecision,
    *,
    strategy_version: str = "RED_BAR_V2",
) -> str | None:
    if decision.entry_type != "REVERSAL":
        return None
    raw = "|".join(
        [
            strategy_version,
            "REVERSAL",
            decision.direction or "NONE",
            _iso(decision.context_timestamp) or "NONE",
            _iso(decision.reference_timestamp) or "NONE",
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def evaluate_candidate_admission(
    direction_decision: RedBarV2DirectionDecision,
    trade_state: TradeStateSnapshot,
    *,
    duplicate_signal: bool = False,
    reversal_already_consumed: bool = False,
    strategy_version: str = "RED_BAR_V2",
) -> CandidateAdmissionDecision:
    """Apply the Red Bar V2 candidate gate without creating or closing orders."""
    reversal_event_id = build_reversal_event_id(
        direction_decision,
        strategy_version=strategy_version,
    )
    decision_id = build_candidate_identity(
        direction_decision,
        strategy_version=strategy_version,
    )
    previous_status = (
        trade_state.latest_executed_trade.lifecycle_state.value
        if trade_state.latest_executed_trade is not None
        else None
    )
    conditions = {
        "reference_ready": direction_decision.reference_timestamp is not None,
        "context_fresh": direction_decision.context_fresh,
        "rsi_aligned": direction_decision.rsi_aligned,
        "vwap_aligned": direction_decision.vwap_aligned,
        "midpoint_aligned": direction_decision.midpoint_aligned,
        "duplicate_signal": duplicate_signal,
        "reversal_already_consumed": reversal_already_consumed,
        "active_trade_count": trade_state.active_trade_count,
        "pending_trade_count": trade_state.pending_trade_count,
        "previous_trade_closed": trade_state.previous_trade_closed,
        "trade_state": trade_state.lifecycle_state.value,
    }

    def result(allowed: bool, code: AdmissionCode, reason: str) -> CandidateAdmissionDecision:
        return CandidateAdmissionDecision(
            decision_id=decision_id,
            candidate_allowed=allowed,
            admission_code=code,
            admission_reason=reason,
            strategy_version=strategy_version,
            direction=direction_decision.direction,
            option_side=direction_decision.option_side,
            entry_type=direction_decision.entry_type,
            trend_strength=direction_decision.trend_strength,
            reference_timestamp=_iso(direction_decision.reference_timestamp),
            context_timestamp=_iso(direction_decision.context_timestamp),
            active_trade_count=trade_state.active_trade_count,
            previous_trade_status=previous_status,
            reversal_event_id=reversal_event_id,
            conditions=conditions,
        )

    # Primary-code priority follows the frozen strategy specification.
    if direction_decision.state == RedBarV2State.REFERENCE_NOT_READY or direction_decision.reference_timestamp is None:
        return result(False, AdmissionCode.REFERENCE_NOT_READY, "The NEXT_RED_CANDLE reference has not been established.")

    if (
        direction_decision.event_type == RedBarV2EventType.CONTEXT_INVALID
        or not direction_decision.context_fresh
        or direction_decision.context_timestamp is None
    ):
        return result(False, AdmissionCode.CONTEXT_STALE, "The RSI/VWAP context is missing, stale, incomplete, or timestamp-misaligned.")

    if duplicate_signal:
        return result(False, AdmissionCode.DUPLICATE_SIGNAL, "An identical deterministic candidate has already been processed.")

    if reversal_event_id is not None and reversal_already_consumed:
        return result(False, AdmissionCode.REVERSAL_ALREADY_CONSUMED, "This reversal event has already generated a candidate or trade.")

    if trade_state.active_trade_count > 0 or trade_state.lifecycle_state == TradeLifecycleState.CONFLICT:
        return result(False, AdmissionCode.ACTIVE_TRADE_BLOCK, "An active or conflicting trade state prevents overlapping entry.")

    if trade_state.pending_trade_count > 0 or not trade_state.previous_trade_closed:
        return result(False, AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED, "The previous trade or pending order has not reached terminal CLOSED state.")

    # RSI is informational and must not gate admission. Both futures gates
    # (initial and reversal) treat it that way, so ``rsi_aligned`` is recorded
    # in ``conditions`` for the audit trail only. AdmissionCode.RSI_NOT_ALIGNED
    # is retained because historical rows still carry it.
    if not direction_decision.vwap_aligned:
        return result(False, AdmissionCode.VWAP_NOT_ALIGNED, "The completed candle is not on the required side of VWAP.")

    is_reversal = direction_decision.entry_type == "REVERSAL"
    if not direction_decision.midpoint_aligned and not is_reversal:
        return result(False, AdmissionCode.MIDPOINT_NOT_ALIGNED, "Initial entry requires alignment with the fixed Red Bar midpoint.")

    if is_reversal:
        return result(
            True,
            AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT,
            "Opposite 5-minute RSI/VWAP reversal is aligned and execution is flat; midpoint confirmation may remain provisional.",
        )

    if direction_decision.event_type == RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT:
        return result(True, AdmissionCode.INITIAL_BULLISH_ALIGNMENT, "Completed 1-minute candle has bullish RSI, VWAP, and midpoint alignment.")

    if direction_decision.event_type == RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT:
        return result(True, AdmissionCode.INITIAL_BEARISH_ALIGNMENT, "Completed 1-minute candle has bearish RSI, VWAP, and midpoint alignment.")

    if direction_decision.event_type == RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT:
        # A state upgrade is observable but must not create another candidate.
        if direction_decision.entry_type == "STATE_UPGRADE":
            return result(False, AdmissionCode.DUPLICATE_SIGNAL, "Midpoint confirmation upgrades the existing state and must not create a second candidate.")
        return result(True, AdmissionCode.FULL_DIRECTIONAL_ALIGNMENT, "RSI, VWAP, and the fixed midpoint are fully aligned while execution is flat.")

    return result(False, AdmissionCode.MIDPOINT_NOT_ALIGNED, "No admissible Red Bar V2 candidate condition is fully aligned.")
