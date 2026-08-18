from datetime import datetime

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    build_candidate_identity,
    build_reversal_event_id,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import (
    ObservedTrade,
    TradeLifecycleState,
    TradeStateSnapshot,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2State,
)


def _direction(
    *,
    event=RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
    state=RedBarV2State.CONFIRMED_BULLISH,
    direction="BULLISH",
    side="CE",
    entry_type="INITIAL",
    strength="CONFIRMED",
    rsi=True,
    vwap=True,
    midpoint=True,
    fresh=True,
    reference=True,
):
    return RedBarV2DirectionDecision(
        event_type=event,
        state=state,
        direction=direction,
        option_side=side,
        entry_type=entry_type,
        trend_strength=strength,
        context_timestamp=datetime(2026, 8, 21, 10, 0) if fresh else None,
        reference_timestamp=datetime(2026, 8, 21, 9, 25) if reference else None,
        close_price=105.0,
        rsi_value=60.0,
        vwap_value=102.0,
        rsi_aligned=rsi,
        vwap_aligned=vwap,
        midpoint_aligned=midpoint,
        context_fresh=fresh,
        reason="test",
    )


def _trade(state=TradeLifecycleState.FLAT, *, previous_closed=True, active=0, pending=0):
    latest = None
    active_trade = None
    if state in {TradeLifecycleState.ACTIVE, TradeLifecycleState.CLOSED}:
        latest = ObservedTrade(
            trade_id="T1",
            signal_id="S1",
            instrument_key="NIFTY",
            option_side="PE",
            raw_status=state.value,
            lifecycle_state=state,
            entry_timestamp=None,
            exit_timestamp=None,
            sequence_timestamp=None,
            source={},
        )
        if state == TradeLifecycleState.ACTIVE:
            active_trade = latest
    return TradeStateSnapshot(
        lifecycle_state=state,
        active_trade=active_trade,
        latest_executed_trade=latest,
        previous_trade_closed=previous_closed,
        has_pending_trade=pending > 0,
        active_trade_count=active,
        pending_trade_count=pending,
        conflict_reason="MULTIPLE_ACTIVE_TRADES" if state == TradeLifecycleState.CONFLICT else None,
    )


def test_reference_not_ready_has_highest_priority():
    result = evaluate_candidate_admission(
        _direction(reference=False, fresh=False),
        _trade(state=TradeLifecycleState.ACTIVE, previous_closed=False, active=1),
        duplicate_signal=True,
    )
    assert result.admission_code == AdmissionCode.REFERENCE_NOT_READY
    assert result.candidate_allowed is False


def test_stale_context_precedes_duplicate_and_trade_state():
    result = evaluate_candidate_admission(
        _direction(event=RedBarV2EventType.CONTEXT_INVALID, fresh=False),
        _trade(state=TradeLifecycleState.ACTIVE, previous_closed=False, active=1),
        duplicate_signal=True,
    )
    assert result.admission_code == AdmissionCode.CONTEXT_STALE


def test_duplicate_signal_blocks_before_active_trade_gate():
    result = evaluate_candidate_admission(
        _direction(),
        _trade(state=TradeLifecycleState.ACTIVE, previous_closed=False, active=1),
        duplicate_signal=True,
    )
    assert result.admission_code == AdmissionCode.DUPLICATE_SIGNAL


def test_consumed_reversal_blocks_before_active_trade_gate():
    result = evaluate_candidate_admission(
        _direction(
            event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
            state=RedBarV2State.PROVISIONAL_BULLISH,
            entry_type="REVERSAL",
            strength="PROVISIONAL",
            midpoint=False,
        ),
        _trade(state=TradeLifecycleState.ACTIVE, previous_closed=False, active=1),
        reversal_already_consumed=True,
    )
    assert result.admission_code == AdmissionCode.REVERSAL_ALREADY_CONSUMED


def test_active_trade_blocks_valid_candidate():
    result = evaluate_candidate_admission(
        _direction(),
        _trade(state=TradeLifecycleState.ACTIVE, previous_closed=False, active=1),
    )
    assert result.admission_code == AdmissionCode.ACTIVE_TRADE_BLOCK
    assert result.candidate_allowed is False


def test_pending_or_unclosed_previous_trade_blocks_candidate():
    result = evaluate_candidate_admission(
        _direction(),
        _trade(state=TradeLifecycleState.PENDING, previous_closed=False, pending=1),
    )
    assert result.admission_code == AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED


def test_initial_alignment_requires_rsi_vwap_and_midpoint():
    assert evaluate_candidate_admission(
        _direction(rsi=False), _trade()
    ).admission_code == AdmissionCode.RSI_NOT_ALIGNED
    assert evaluate_candidate_admission(
        _direction(vwap=False), _trade()
    ).admission_code == AdmissionCode.VWAP_NOT_ALIGNED
    assert evaluate_candidate_admission(
        _direction(midpoint=False), _trade()
    ).admission_code == AdmissionCode.MIDPOINT_NOT_ALIGNED


def test_initial_bullish_and_bearish_candidates_are_admitted_when_flat():
    bullish = evaluate_candidate_admission(_direction(), _trade())
    bearish = evaluate_candidate_admission(
        _direction(
            event=RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BEARISH,
            direction="BEARISH",
            side="PE",
        ),
        _trade(),
    )
    assert bullish.candidate_allowed is True
    assert bullish.admission_code == AdmissionCode.INITIAL_BULLISH_ALIGNMENT
    assert bearish.candidate_allowed is True
    assert bearish.admission_code == AdmissionCode.INITIAL_BEARISH_ALIGNMENT


def test_provisional_reversal_is_admitted_without_midpoint_when_flat():
    decision = _direction(
        event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
        state=RedBarV2State.PROVISIONAL_BULLISH,
        entry_type="REVERSAL",
        strength="PROVISIONAL",
        midpoint=False,
    )
    result = evaluate_candidate_admission(decision, _trade())
    assert result.candidate_allowed is True
    assert result.admission_code == AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT
    assert result.trend_strength == "PROVISIONAL"
    assert result.reversal_event_id == build_reversal_event_id(decision)


def test_midpoint_state_upgrade_does_not_create_second_candidate():
    result = evaluate_candidate_admission(
        _direction(
            event=RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT,
            entry_type="STATE_UPGRADE",
        ),
        _trade(),
    )
    assert result.candidate_allowed is False
    assert result.admission_code == AdmissionCode.DUPLICATE_SIGNAL


def test_candidate_and_reversal_identities_are_deterministic():
    initial = _direction()
    reversal = _direction(
        event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
        state=RedBarV2State.PROVISIONAL_BULLISH,
        entry_type="REVERSAL",
        strength="PROVISIONAL",
        midpoint=False,
    )
    assert build_candidate_identity(initial) == build_candidate_identity(initial)
    assert build_reversal_event_id(initial) is None
    assert build_reversal_event_id(reversal) == build_reversal_event_id(reversal)
