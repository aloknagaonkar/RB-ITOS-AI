from pathlib import Path

from red_bar_lab.intelligence.transition_sequence_state_machine import (
    TransitionSequenceStateMachine,
)
from red_bar_lab.services.transition_sequence_store import TransitionSequenceStore
from red_bar_lab.services.attribution_context import build_attribution_context


def bullish_snapshot(timestamp="2026-08-13T10:00:00"):
    return {
        "timestamp": timestamp,
        "instrument_key": "NSE_INDEX|Nifty 50",
        "previous_regime": "TRANSITION_BULLISH",
        "current_regime": "BULLISH",
        "bullish_score": 85,
        "bearish_score": 10,
        "break_level": 24364.5,
        "invalidation_level": 24342.25,
        "red_bar_support": "NOT_AVAILABLE",
        "evidence": [
            "5M_CLOSE_ABOVE_EMA10",
            "5M_EMA10_RISING",
            "1M_EMA10_ABOVE_EMA30",
            "1M_HIGHER_LOW",
            "1M_STRUCTURE_BREAKOUT",
        ],
    }


def test_new_bullish_transition_is_confirmed():
    state = TransitionSequenceStateMachine().advance(bullish_snapshot())
    assert state is not None
    assert state.direction == "BULLISH"
    assert state.status == "CONFIRMED"
    assert state.stage == "BULLISH_CONFIRMED"
    assert state.execution_allowed is False


def test_transition_id_is_preserved_while_active():
    first = TransitionSequenceStateMachine().advance({
        **bullish_snapshot("2026-08-13T10:00:00"),
        "current_regime": "TRANSITION_BULLISH",
    })
    second = TransitionSequenceStateMachine().advance(
        bullish_snapshot("2026-08-13T10:05:00"),
        previous=first.as_record(),
    )
    assert second.transition_id == first.transition_id
    assert second.stage_index >= first.stage_index


def test_direction_change_starts_new_transition():
    first = TransitionSequenceStateMachine().advance(bullish_snapshot())
    bearish = {
        **bullish_snapshot("2026-08-13T10:10:00"),
        "previous_regime": "TRANSITION_BEARISH",
        "current_regime": "BEARISH",
        "bullish_score": 5,
        "bearish_score": 90,
        "evidence": [
            "5M_CLOSE_BELOW_EMA10",
            "5M_EMA10_FALLING",
            "1M_EMA10_BELOW_EMA30",
            "1M_LOWER_HIGH",
            "1M_STRUCTURE_BREAKDOWN",
        ],
    }
    second = TransitionSequenceStateMachine().advance(
        bearish,
        previous=first.as_record(),
    )
    assert second.transition_id != first.transition_id
    assert second.direction == "BEARISH"


def test_store_and_attribution(tmp_path: Path):
    state = TransitionSequenceStateMachine().advance(bullish_snapshot())
    store = TransitionSequenceStore(tmp_path / "transition.jsonl")
    assert store.append_once(state.as_record()) is True
    assert store.append_once(state.as_record()) is False

    context = build_attribution_context(
        bullish_snapshot(),
        state.as_record(),
    )
    assert context.transition_id == state.transition_id
    assert context.signal_id is None
    assert context.execution_allowed is False
