from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
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
    WORKING_REFERENCE_CONFIRMED_FLAT = "WORKING_REFERENCE_CONFIRMED_FLAT"
    WORKING_REFERENCE_NOT_CONFIRMED = "WORKING_REFERENCE_NOT_CONFIRMED"
    FULL_DIRECTIONAL_ALIGNMENT = "FULL_DIRECTIONAL_ALIGNMENT"
    ACTIVE_TRADE_BLOCK = "ACTIVE_TRADE_BLOCK"
    PREVIOUS_TRADE_NOT_CLOSED = "PREVIOUS_TRADE_NOT_CLOSED"
    RSI_NOT_ALIGNED = "RSI_NOT_ALIGNED"
    VWAP_NOT_ALIGNED = "VWAP_NOT_ALIGNED"
    MIDPOINT_NOT_ALIGNED = "MIDPOINT_NOT_ALIGNED"
    CONTEXT_STALE = "CONTEXT_STALE"
    ENTRY_WINDOW_CLOSED = "ENTRY_WINDOW_CLOSED"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    REVERSAL_ALREADY_CONSUMED = "REVERSAL_ALREADY_CONSUMED"
    NO_ADMISSIBLE_CONDITION = "NO_ADMISSIBLE_CONDITION"


DEFAULT_ENTRY_CUTOFF = time(15, 0)


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
    entry_cutoff: time | None = DEFAULT_ENTRY_CUTOFF,
    strategy_version: str = "RED_BAR_V2",
) -> CandidateAdmissionDecision:
    """Apply the Red Bar V2 candidate gate without creating or closing orders.

    ``entry_cutoff`` is the last wall-clock time a *new* candidate may be
    admitted; pass None to disable it. Only entries are affected -- this function
    judges nothing but new candidates, so an open position keeps running under
    the exit policy after the window shuts.
    """
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
    context_time = (
        direction_decision.context_timestamp.time()
        if direction_decision.context_timestamp is not None
        else None
    )
    # Unknown time counts as open. A missing context timestamp is already a hard
    # CONTEXT_STALE reject below, so this never widens the window -- it only keeps
    # the reported reason accurate about which check actually failed.
    entry_window_open = (
        entry_cutoff is None or context_time is None or context_time < entry_cutoff
    )
    conditions = {
        "reference_ready": direction_decision.reference_timestamp is not None,
        "context_fresh": direction_decision.context_fresh,
        "entry_window_open": entry_window_open,
        "rsi_aligned": direction_decision.rsi_aligned,
        # The canonical RedBar + VWAP check. It was computed by the strategy
        # and then dropped here, so the audit trail could never write a
        # `check:redbar_vwap_aligned` row and the UI silently skipped the one
        # gate it advertises first.
        "redbar_vwap_aligned": direction_decision.redbar_vwap_aligned,
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

    # A closed window dominates every alignment question, so it is asked before
    # them: a perfectly aligned 15:10 candle is still not a tradeable entry, and
    # reporting VWAP_NOT_ALIGNED for it would send the reader looking at the
    # wrong thing.
    if not entry_window_open:
        return result(
            False,
            AdmissionCode.ENTRY_WINDOW_CLOSED,
            f"New entries close at {entry_cutoff.isoformat(timespec='minutes')}; "
            "open positions continue under the exit policy.",
        )

    if duplicate_signal:
        return result(False, AdmissionCode.DUPLICATE_SIGNAL, "An identical deterministic candidate has already been processed.")

    if reversal_event_id is not None and reversal_already_consumed:
        return result(False, AdmissionCode.REVERSAL_ALREADY_CONSUMED, "This reversal event has already generated a candidate or trade.")

    if trade_state.active_trade_count > 0 or trade_state.lifecycle_state == TradeLifecycleState.CONFLICT:
        return result(False, AdmissionCode.ACTIVE_TRADE_BLOCK, "An active or conflicting trade state prevents overlapping entry.")

    if trade_state.pending_trade_count > 0 or not trade_state.previous_trade_closed:
        return result(False, AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED, "The previous trade or pending order has not reached terminal CLOSED state.")

    # The working reference is judged on structure alone, so it is settled before
    # the VWAP and midpoint checks -- those describe the Red Bar's gate and this
    # path never consults a VWAP at all. Running it through them would reject
    # every deputy entry on a check it was designed not to use.
    if direction_decision.entry_type == "WORKING":
        if direction_decision.trend_strength != "CONFIRMED":
            return result(
                False,
                AdmissionCode.WORKING_REFERENCE_NOT_CONFIRMED,
                "The close crossed the working reference midpoint but has not "
                "taken out its high or low, so no entry is triggered.",
            )
        return result(
            True,
            AdmissionCode.WORKING_REFERENCE_CONFIRMED_FLAT,
            "The close has taken out the working reference extreme outside the "
            "Red Bar band while execution is flat.",
        )

    # RSI is informational and must not gate admission. Both futures gates
    # (initial and reversal) treat it that way, so ``rsi_aligned`` is recorded
    # in ``conditions`` for the audit trail only. AdmissionCode.RSI_NOT_ALIGNED
    # is retained because historical rows still carry it.
    if not direction_decision.vwap_aligned:
        return result(False, AdmissionCode.VWAP_NOT_ALIGNED, "The completed candle is not on the required side of VWAP.")

    # No reversal exemption. The reversal path used to be admitted on the VWAP
    # alone, with the midpoint downgraded to a grade, which let it enter with
    # price on the wrong side of the very level the strategy is named for. Inside
    # the Red Bar's band every entry answers to the Red Bar's own rule.
    if not direction_decision.midpoint_aligned:
        return result(False, AdmissionCode.MIDPOINT_NOT_ALIGNED, "Entry requires alignment with the fixed Red Bar midpoint.")

    if direction_decision.entry_type == "REVERSAL":
        return result(
            True,
            AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT,
            "The opposite 5-minute reversal clears the fixed midpoint and the "
            "futures VWAP together while execution is flat.",
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

    # Reached only when every named gate passed but no event type claimed the
    # decision -- e.g. NO_DIRECTIONAL_ALIGNMENT. This used to report
    # MIDPOINT_NOT_ALIGNED with a reason that contradicted it, so a reader
    # chasing a midpoint problem found a perfectly aligned midpoint.
    return result(False, AdmissionCode.NO_ADMISSIBLE_CONDITION, "No admissible Red Bar V2 candidate condition is fully aligned.")
