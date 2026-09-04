"""The Red Bar V2 entry ladder: the 21 checkpoints a candidate walks in order.

This module is the catalog only. It knows the sequence, which recorded evidence
answers each checkpoint, and which codes mean a checkpoint stopped the candidate.
It reads no database and decides nothing.

Two halves, because the entry path has two halves. Checkpoints 1-12 are the
admission gates evaluated inside ``evaluate_candidate_admission``; checkpoints
13-21 are the order path recorded by ``automation._record_state``.

The ordering of the admission half is *not* taken from ``AdmissionCode``'s
declaration order -- the enum is grouped by kind, not by precedence, so
``CONTEXT_STALE`` is declared thirteenth and evaluated second. It is taken from
the order the codes are returned in ``evaluate_candidate_admission``, and
``test_red_bar_v2_entry_ladder.py`` pins that by scanning the policy's own
source. A gate reordered in the policy and not here fails that test rather than
quietly mis-describing which check stopped the trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from red_bar_lab.execution.red_bar_v2_admission_policy import AdmissionCode


ADMISSION_PHASE = "ADMISSION"
ORDER_PATH_PHASE = "ORDER_PATH"

#: Codes that are members of ``AdmissionCode`` but are never returned by the
#: policy, so they own no checkpoint. ``RSI_NOT_ALIGNED`` is retained in the
#: enum only because historical rows carry it -- RSI was retired as a gate and
#: is now recorded as evidence instead.
RETIRED_ADMISSION_CODES = frozenset({AdmissionCode.RSI_NOT_ALIGNED.value})

#: Evidence steps that are recorded but gate nothing. They render in the
#: EVIDENCE ONLY block, never as a ladder rung.
EVIDENCE_ONLY_STEPS = (
    "check:rsi_informational",
    "check:zone_geometry",
    "check:pcr_informational",
)

@dataclass(frozen=True)
class EntryCheckpoint:
    """One rung of the ladder.

    ``blocking_codes`` are the values that mean *this* checkpoint refused the
    candidate. For the admission half they are ``AdmissionCode`` values; for the
    order path they are ``execution_state_events.state`` values.

    ``pass_states`` (order path only) are states whose presence proves the
    checkpoint was cleared. A checkpoint with neither a blocking state nor a
    pass state in the record is *not reached* -- never a pass.

    ``applies_to`` restricts the checkpoint to entry types that actually run it.
    An empty tuple means every path. The WORKING path is judged on structure
    alone and returns before the VWAP and midpoint checks, so those two are
    ``n/a`` for a deputy entry rather than failures.

    ``reason_tokens`` are substrings looked for in an order-path event's detail
    string, for gates that are recorded as a token inside a reason rather than
    as a state of their own.
    """

    number: int
    key: str
    title: str
    phase: str
    blocking_codes: tuple[str, ...] = ()
    pass_states: tuple[str, ...] = ()
    reason_tokens: tuple[str, ...] = ()
    evidence_step: str | None = None
    condition_key: str | None = None
    #: True when the condition passes by being False (``duplicate_signal``).
    condition_inverted: bool = False
    applies_to: tuple[str, ...] = ()
    detail_keys: tuple[str, ...] = field(default_factory=tuple)

    def applies_to_entry_type(self, entry_type: str | None) -> bool:
        """Whether this checkpoint is on the path a given entry type walks.

        An unknown entry type is treated as applicable: the alternative is
        hiding a rung because the record is thin, which reads as though the
        strategy skipped a check it did not skip.
        """
        if not self.applies_to:
            return True
        if not entry_type:
            return True
        return entry_type in self.applies_to

_ADMISSION_CHECKPOINTS: tuple[EntryCheckpoint, ...] = (
    EntryCheckpoint(
        number=1,
        key="reference_ready",
        title="Reference ready",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.REFERENCE_NOT_READY.value,),
        evidence_step="check:reference_ready",
        condition_key="reference_ready",
        detail_keys=("reference_timestamp", "governing_reference", "state"),
    ),
    EntryCheckpoint(
        number=2,
        key="context_fresh",
        title="Context fresh",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.CONTEXT_STALE.value,),
        evidence_step="check:context_fresh",
        condition_key="context_fresh",
        detail_keys=("context_timestamp",),
    ),
    EntryCheckpoint(
        number=3,
        key="entry_window_open",
        title="Entry window open (15:00 cutoff)",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.ENTRY_WINDOW_CLOSED.value,),
        evidence_step="check:entry_window_open",
        condition_key="entry_window_open",
        detail_keys=("context_timestamp", "entry_cutoff"),
    ),
    EntryCheckpoint(
        number=4,
        key="not_duplicate",
        title="Not a duplicate candidate",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.DUPLICATE_SIGNAL.value,),
        evidence_step="check:duplicate_signal",
        condition_key="duplicate_signal",
        condition_inverted=True,
        detail_keys=("decision_id",),
    ),
    EntryCheckpoint(
        number=5,
        key="reversal_not_consumed",
        title="Reversal not already consumed",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.REVERSAL_ALREADY_CONSUMED.value,),
        evidence_step="check:reversal_already_consumed",
        condition_key="reversal_already_consumed",
        condition_inverted=True,
        detail_keys=("reversal_event_id",),
    ),
    EntryCheckpoint(
        number=6,
        key="no_active_trade",
        title="No active trade",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.ACTIVE_TRADE_BLOCK.value,),
        evidence_step="check:active_trade",
        condition_key="active_trade_count",
        detail_keys=("active_trade_count", "trade_state"),
    ),
    EntryCheckpoint(
        number=7,
        key="previous_trade_closed",
        title="Previous trade closed",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED.value,),
        evidence_step="check:previous_trade_closed",
        condition_key="previous_trade_closed",
        detail_keys=("pending_trade_count", "previous_trade_status"),
    ),
    EntryCheckpoint(
        number=8,
        key="working_reference_confirmed",
        title="Deputy reference confirmed",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.WORKING_REFERENCE_NOT_CONFIRMED.value,),
        evidence_step="check:working_reference_confirmed",
        applies_to=("WORKING",),
        detail_keys=("trend_strength", "working_body_ratio", "governing_reference"),
    ),
    EntryCheckpoint(
        number=9,
        key="vwap_aligned",
        title="Futures VWAP aligned",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.VWAP_NOT_ALIGNED.value,),
        evidence_step="check:vwap_aligned",
        condition_key="vwap_aligned",
        applies_to=("INITIAL", "REVERSAL", "STATE_UPGRADE"),
        detail_keys=("futures_vwap", "index_close", "redbar_vwap_aligned"),
    ),
    EntryCheckpoint(
        number=10,
        key="midpoint_aligned",
        title="Red Bar midpoint aligned",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.MIDPOINT_NOT_ALIGNED.value,),
        evidence_step="check:midpoint_aligned",
        condition_key="midpoint_aligned",
        applies_to=("INITIAL", "REVERSAL", "STATE_UPGRADE"),
        detail_keys=(
            "reference_midpoint",
            "index_close",
            "midpoint_distance_points",
            "zone_position",
        ),
    ),
    EntryCheckpoint(
        number=11,
        key="admitted",
        title="Admitted as a candidate",
        phase=ADMISSION_PHASE,
        blocking_codes=(AdmissionCode.NO_ADMISSIBLE_CONDITION.value,),
        evidence_step="admission_decision",
        detail_keys=(
            "entry_type",
            "direction",
            "option_side",
            "trend_strength",
            "admission_reason",
        ),
    ),
    EntryCheckpoint(
        number=12,
        key="entry_risk_plan",
        title="Stop priceable, risk 8-60 points",
        phase=ADMISSION_PHASE,
        blocking_codes=(
            "NO_TRIGGER_CANDLE",
            "STOP_ON_WRONG_SIDE",
            "RISK_BELOW_FLOOR",
            "RISK_ABOVE_CAP",
        ),
        evidence_step="entry_risk_plan",
        detail_keys=(
            "risk_stop_price",
            "risk_points",
            "risk_stop_trigger",
            "risk_plan_code",
        ),
    ),
)

#: The terminal codes that mean the ladder cleared the whole admission half.
#: Reaching any of them proves checkpoints 1-11 were all satisfied on the path
#: the candidate actually walked.
ADMITTING_CODES = frozenset(
    {
        AdmissionCode.INITIAL_BULLISH_ALIGNMENT.value,
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT.value,
        AdmissionCode.WORKING_REFERENCE_CONFIRMED_FLAT.value,
        AdmissionCode.FULL_DIRECTIONAL_ALIGNMENT.value,
    }
)

_ORDER_PATH_CHECKPOINTS: tuple[EntryCheckpoint, ...] = (
    EntryCheckpoint(
        number=13,
        key="strategy_enabled_and_capacity",
        title="Strategy enabled, entry capacity free",
        phase=ORDER_PATH_PHASE,
        blocking_codes=(
            "STRATEGY_DISABLED",
            "ENTRY_CAPACITY_REACHED",
            "RSI_ENTRY_CAPACITY",
        ),
    ),
    EntryCheckpoint(
        number=14,
        key="opportunity_evaluated",
        title="Opportunity evaluated",
        phase=ORDER_PATH_PHASE,
        pass_states=("OPPORTUNITY_EVALUATED",),
    ),
    EntryCheckpoint(
        number=15,
        key="signal_fresh",
        title="Signal still fresh",
        phase=ORDER_PATH_PHASE,
        blocking_codes=("RED_BAR_V2_SIGNAL_EXPIRED", "CANDIDATE_EXPIRED"),
    ),
    EntryCheckpoint(
        number=16,
        key="risk_plan_accepted",
        title="Risk plan accepted by the order path",
        phase=ORDER_PATH_PHASE,
        blocking_codes=("RED_BAR_V2_RISK_PLAN_REJECTED",),
    ),
    EntryCheckpoint(
        number=17,
        key="tradable_contract",
        title="Tradable contract (spread, liquidity)",
        phase=ORDER_PATH_PHASE,
        # Recorded as tokens inside the opportunity reason rather than as states
        # of their own, because they are two of several blockers the engine
        # collects before deciding eligibility.
        reason_tokens=("SPREAD", "LIQUIDITY"),
        pass_states=("OPPORTUNITY_EVALUATED",),
    ),
    EntryCheckpoint(
        number=18,
        key="execution_committee",
        title="Execution committee queued it",
        phase=ORDER_PATH_PHASE,
        pass_states=("QUEUED",),
        blocking_codes=("DECISION_RECORDED", "SKIPPED_OPPORTUNITY"),
    ),
    EntryCheckpoint(
        number=19,
        key="portfolio_approved",
        title="Portfolio approved it",
        phase=ORDER_PATH_PHASE,
        pass_states=("PORTFOLIO_APPROVED", "OPPORTUNITY_EXTENSION_APPROVED"),
        blocking_codes=("PORTFOLIO_WATCHLIST",),
    ),
    EntryCheckpoint(
        number=20,
        key="executing",
        title="Order submitted",
        phase=ORDER_PATH_PHASE,
        pass_states=("EXECUTING",),
        blocking_codes=("ERROR",),
    ),
    EntryCheckpoint(
        number=21,
        key="open",
        title="Position open",
        phase=ORDER_PATH_PHASE,
        pass_states=("OPEN",),
    ),
)

#: The ladder, in the order a candidate walks it.
ENTRY_LADDER: tuple[EntryCheckpoint, ...] = (
    _ADMISSION_CHECKPOINTS + _ORDER_PATH_CHECKPOINTS
)

ADMISSION_CHECKPOINT_COUNT = len(_ADMISSION_CHECKPOINTS)


def admission_checkpoints() -> tuple[EntryCheckpoint, ...]:
    return _ADMISSION_CHECKPOINTS


def order_path_checkpoints() -> tuple[EntryCheckpoint, ...]:
    return _ORDER_PATH_CHECKPOINTS


def checkpoint_for_code(code: str | None) -> EntryCheckpoint | None:
    """The checkpoint a blocking code belongs to, or None if it blocks nothing."""
    if not code:
        return None
    for checkpoint in ENTRY_LADDER:
        if code in checkpoint.blocking_codes:
            return checkpoint
    return None


def gate_evidence_steps() -> tuple[str, ...]:
    """Every ``process_evidence`` step name the admission half reads."""
    return tuple(
        checkpoint.evidence_step
        for checkpoint in _ADMISSION_CHECKPOINTS
        if checkpoint.evidence_step
    )

