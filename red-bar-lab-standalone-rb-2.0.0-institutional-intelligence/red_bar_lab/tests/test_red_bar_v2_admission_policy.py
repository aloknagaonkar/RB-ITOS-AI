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
    at=datetime(2026, 8, 21, 10, 0),
):
    return RedBarV2DirectionDecision(
        event_type=event,
        state=state,
        direction=direction,
        option_side=side,
        entry_type=entry_type,
        trend_strength=strength,
        context_timestamp=at if fresh else None,
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


def test_initial_alignment_requires_vwap_and_midpoint():
    # RSI is informational: an unaligned RSI must not block admission.
    allowed = evaluate_candidate_admission(_direction(rsi=False), _trade())
    assert allowed.candidate_allowed is True
    assert allowed.admission_code != AdmissionCode.RSI_NOT_ALIGNED
    assert allowed.conditions["rsi_aligned"] is False

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


def test_a_reversal_that_clears_both_halves_of_the_gate_is_admitted_when_flat():
    """A reversal is a Red Bar entry, so it answers to the Red Bar's own gate.

    Inside the band the senior reference is in force, and its rule is the index
    close against the frozen midpoint *and* the futures against their VWAP. A
    reversal is admitted on exactly those terms and no others.
    """
    decision = _direction(
        event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
        state=RedBarV2State.PROVISIONAL_BULLISH,
        entry_type="REVERSAL",
        strength="PROVISIONAL",
    )
    result = evaluate_candidate_admission(decision, _trade())
    assert result.candidate_allowed is True
    assert result.admission_code == AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT
    assert result.trend_strength == "PROVISIONAL"
    assert result.reversal_event_id == build_reversal_event_id(decision)


def test_a_reversal_on_the_vwap_alone_is_refused():
    """The exemption that let the VWAP enter by itself is gone.

    A reversal used to be admitted on the VWAP with the midpoint downgraded to a
    grade, which could open a position with price on the wrong side of the very
    level the strategy is named for. PROVISIONAL still trades -- the grade says
    how much of the reference candle was taken out, not whether the gate passed.
    """
    decision = _direction(
        event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
        state=RedBarV2State.PROVISIONAL_BULLISH,
        entry_type="REVERSAL",
        strength="PROVISIONAL",
        midpoint=False,
    )
    result = evaluate_candidate_admission(decision, _trade())
    assert result.candidate_allowed is False
    assert result.admission_code == AdmissionCode.MIDPOINT_NOT_ALIGNED


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


def test_a_working_reference_entry_is_judged_on_structure_alone():
    """The deputy path consults no VWAP, so the VWAP gate must not judge it.

    Running it through the Red Bar's gate would reject every deputy entry on a
    check the path was designed not to use -- a futures outage would suppress a
    purely structural entry, which is the suppression cascade in a new costume.
    """
    decision = _direction(
        event=RedBarV2EventType.WORKING_BULLISH_BREAKOUT,
        entry_type="WORKING",
        vwap=False,
        midpoint=False,
    )
    result = evaluate_candidate_admission(decision, _trade())
    assert result.candidate_allowed is True
    assert result.admission_code == AdmissionCode.WORKING_REFERENCE_CONFIRMED_FLAT


def test_a_working_reference_entry_needs_the_whole_candle():
    """Crossing the deputy's midpoint is a setup; clearing its extreme is entry.

    The stop is measured from that same extreme, so a close that has taken it out
    is already about 1R ahead. PROVISIONAL is emitted rather than swallowed, and
    it is the admission policy that refuses it -- so the audit trail keeps every
    candle that crossed the midpoint without finishing the job.
    """
    decision = _direction(
        event=RedBarV2EventType.WORKING_BULLISH_BREAKOUT,
        state=RedBarV2State.PROVISIONAL_BULLISH,
        entry_type="WORKING",
        strength="PROVISIONAL",
        vwap=False,
        midpoint=False,
    )
    result = evaluate_candidate_admission(decision, _trade())
    assert result.candidate_allowed is False
    assert result.admission_code == AdmissionCode.WORKING_REFERENCE_NOT_CONFIRMED


def test_no_new_entry_is_admitted_after_the_cutoff():
    """A closed window dominates every alignment question, so it is asked first.

    Reporting VWAP_NOT_ALIGNED for a 15:10 candle would send the reader looking
    at the wrong thing. Only entries are affected: an open position keeps running
    under the exit policy, which is judged elsewhere.
    """
    late = _direction(at=datetime(2026, 8, 21, 15, 10))
    result = evaluate_candidate_admission(late, _trade())
    assert result.candidate_allowed is False
    assert result.admission_code == AdmissionCode.ENTRY_WINDOW_CLOSED
    assert result.conditions["entry_window_open"] is False

    # The same candle a minute before the cutoff is a normal entry, and passing
    # None disables the window for a study that wants the whole session.
    assert evaluate_candidate_admission(
        _direction(at=datetime(2026, 8, 21, 14, 59)), _trade()
    ).candidate_allowed is True
    assert evaluate_candidate_admission(
        late, _trade(), entry_cutoff=None
    ).candidate_allowed is True


def test_the_cutoff_is_asked_before_every_alignment_question():
    """Two failures at once must report the dominant one."""
    result = evaluate_candidate_admission(
        _direction(at=datetime(2026, 8, 21, 15, 10), vwap=False, midpoint=False),
        _trade(),
    )
    assert result.admission_code == AdmissionCode.ENTRY_WINDOW_CLOSED


def test_an_unclaimed_decision_reports_that_and_not_a_midpoint_problem():
    """The fallback used to name a gate that had just passed.

    NO_DIRECTIONAL_ALIGNMENT clears every named check and then claims nothing, so
    the old MIDPOINT_NOT_ALIGNED fallback sent a reader chasing a midpoint that
    was perfectly aligned.
    """
    result = evaluate_candidate_admission(
        _direction(
            event=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
            state=RedBarV2State.NEUTRAL,
            direction=None,
            side=None,
            entry_type=None,
            strength=None,
        ),
        _trade(),
    )
    assert result.candidate_allowed is False
    assert result.admission_code == AdmissionCode.NO_ADMISSIBLE_CONDITION


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
