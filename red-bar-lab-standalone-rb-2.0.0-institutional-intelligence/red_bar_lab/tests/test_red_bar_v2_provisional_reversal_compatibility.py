"""A PROVISIONAL entry has to survive the contract layer intact.

Against a reference candle of high 24820.0, low 24780.0, midpoint 24800.0, the two
pieces of geometry are independent:

* the midpoint is the **gate** -- no entry of any type is admitted until the index
  close is strictly past it, so 24800.0 exactly fails closed;
* the reference candle's own extreme is the **grade** -- a close past it has taken
  the whole candle out and lands near +1R, because the initial stop is measured
  from that same extreme, so it is CONFIRMED. A close short of it is PROVISIONAL.

So a bullish 24810.0 is admissible and PROVISIONAL, a bullish 24825.0 is
admissible and CONFIRMED, and a bullish 24790.0 is not admissible at all. That
last case used to be the definition of a PROVISIONAL reversal, back when REVERSAL
was exempt from the gate and the midpoint doubled as the grade discriminator.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    BundleLifecycleStatus,
    ContextStatus,
    Direction,
    DomainValidationError,
    EntryType,
    FuturesVwapEvidence,
    MidpointEvidence,
    OptionSide,
    RedBarV2Decision,
    RedBarV2Reference,
    RedBarV2SignalBundle,
    RedBarV2State,
    RsiEvidence,
    TrendStrength,
    build_red_bar_v2_bundle_id,
    build_red_bar_v2_idempotency_key,
    build_red_bar_v2_signal_id,
    red_bar_v2_bundle_from_dict,
    red_bar_v2_bundle_to_dict,
)

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)


def _reference() -> RedBarV2Reference:
    return RedBarV2Reference(
        reference_id="RBV2-REF-20260824-0915",
        trading_date=TRADING_DATE,
        timestamp=datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        high=24820.0,
        low=24780.0,
        midpoint=24800.0,
        source="INDEX_1M",
    )


def _decision(
    *,
    direction: Direction,
    entry_type: EntryType,
    index_close: float,
    current_state: RedBarV2State,
    trend_strength: TrendStrength,
) -> RedBarV2Decision:
    bullish = direction is Direction.BULLISH
    return RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m" if entry_type is EntryType.INITIAL else "5m",
        entry_type=entry_type,
        previous_state=RedBarV2State.REFERENCE_READY,
        current_state=current_state,
        direction=direction,
        option_side=OptionSide.CE if bullish else OptionSide.PE,
        trend_strength=trend_strength,
        reference=_reference(),
        rsi=RsiEvidence(
            62.0 if bullish else 38.0,
            60.0,
            40.0,
            bullish,
            not bullish,
        ),
        futures_vwap=FuturesVwapEvidence(
            "NSE_FO|NIFTY-FUT",
            24815.0 if bullish else 24785.0,
            24800.0,
            150000.0,
            bullish,
            not bullish,
            True,
        ),
        midpoint=MidpointEvidence(
            index_close,
            24800.0,
            index_close > 24800.0,
            index_close < 24800.0,
        ),
        context_status=ContextStatus.FRESH,
        admission_outcome=AdmissionOutcome.ALLOWED,
        admission_code="RBV2_ALLOWED",
        admission_reason="Canonical compatibility fixture",
    )


def _bundle(decision: RedBarV2Decision) -> RedBarV2SignalBundle:
    assert decision.reference is not None
    assert decision.futures_vwap is not None
    assert decision.entry_type is not None
    assert decision.direction is not None
    assert decision.option_side is not None
    signal_id = build_red_bar_v2_signal_id(
        strategy_version=decision.strategy_version,
        instrument_key=decision.futures_vwap.instrument_key,
        trading_date=TRADING_DATE,
        reference_id=decision.reference.reference_id,
        evaluation_timestamp=decision.evaluation_timestamp,
        entry_type=decision.entry_type,
        direction=decision.direction,
    )
    return RedBarV2SignalBundle(
        schema_version="1.0",
        bundle_id=build_red_bar_v2_bundle_id(signal_id=signal_id, schema_version="1.0"),
        signal_id=signal_id,
        strategy_id="RED_BAR_V2",
        strategy_version=decision.strategy_version,
        trading_date=TRADING_DATE,
        evaluation_timestamp=decision.evaluation_timestamp,
        evaluation_timeframe=decision.evaluation_timeframe,
        entry_type=decision.entry_type,
        direction=decision.direction,
        option_side=decision.option_side,
        decision=decision,
        idempotency_key=build_red_bar_v2_idempotency_key(
            signal_id=signal_id,
            option_side=decision.option_side,
        ),
        lifecycle_status=BundleLifecycleStatus.AVAILABLE,
        created_at=datetime(2026, 8, 24, 10, 5, 1, tzinfo=IST),
    )


def test_valid_confirmed_initial_entries():
    bullish = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.INITIAL,
        index_close=24825.0,
        current_state=RedBarV2State.CONFIRMED_BULLISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    bearish = _decision(
        direction=Direction.BEARISH,
        entry_type=EntryType.INITIAL,
        index_close=24775.0,
        current_state=RedBarV2State.CONFIRMED_BEARISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    assert bullish.evaluation_timeframe == "1m"
    assert bearish.evaluation_timeframe == "1m"


def test_an_initial_entry_may_be_provisional():
    """The grade no longer decides admissibility, so INITIAL is not CONFIRMED-only.

    A first entry whose close cleared the midpoint but stopped inside the reference
    candle is a real setup with a real stop; it is simply worth less than one that
    took the candle out. Refusing to represent it here is what pushed the strategy
    into treating the midpoint as two things at once.
    """
    value = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.INITIAL,
        index_close=24810.0,
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    assert value.trend_strength is TrendStrength.PROVISIONAL
    assert value.entry_type is EntryType.INITIAL


def test_valid_confirmed_reversals():
    bullish = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.REVERSAL,
        index_close=24825.0,
        current_state=RedBarV2State.CONFIRMED_BULLISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    bearish = _decision(
        direction=Direction.BEARISH,
        entry_type=EntryType.REVERSAL,
        index_close=24775.0,
        current_state=RedBarV2State.CONFIRMED_BEARISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    assert bullish.evaluation_timeframe == "5m"
    assert bearish.evaluation_timeframe == "5m"


@pytest.mark.parametrize(
    ("direction", "index_close", "state"),
    [
        (Direction.BULLISH, 24810.0, RedBarV2State.PROVISIONAL_BULLISH),
        (Direction.BEARISH, 24790.0, RedBarV2State.PROVISIONAL_BEARISH),
    ],
)
def test_a_provisional_reversal_sits_between_the_midpoint_and_the_extreme(
    direction, index_close, state
):
    value = _decision(
        direction=direction,
        entry_type=EntryType.REVERSAL,
        index_close=index_close,
        current_state=state,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    assert value.trend_strength is TrendStrength.PROVISIONAL


@pytest.mark.parametrize("entry_type", [EntryType.INITIAL, EntryType.REVERSAL])
@pytest.mark.parametrize(
    ("direction", "index_close", "state"),
    [
        # On the wrong side of the level the strategy is named for.
        (Direction.BULLISH, 24790.0, RedBarV2State.PROVISIONAL_BULLISH),
        (Direction.BEARISH, 24810.0, RedBarV2State.PROVISIONAL_BEARISH),
        # Exactly on it: the comparison is strict, so a tie fails closed.
        (Direction.BULLISH, 24800.0, RedBarV2State.PROVISIONAL_BULLISH),
        (Direction.BEARISH, 24800.0, RedBarV2State.PROVISIONAL_BEARISH),
    ],
)
def test_no_entry_type_is_admitted_without_clearing_the_midpoint(
    entry_type, direction, index_close, state
):
    """REVERSAL is parametrized alongside INITIAL because it used to be exempt."""
    with pytest.raises(
        DomainValidationError, match="ALLOWED admission requires midpoint alignment"
    ):
        _decision(
            direction=direction,
            entry_type=entry_type,
            index_close=index_close,
            current_state=state,
            trend_strength=TrendStrength.PROVISIONAL,
        )


def test_state_and_strength_must_match_the_reference_candle_grade():
    with pytest.raises(
        DomainValidationError, match="must match the reference-candle grade"
    ):
        _decision(
            direction=Direction.BULLISH,
            entry_type=EntryType.REVERSAL,
            index_close=24810.0,
            current_state=RedBarV2State.CONFIRMED_BULLISH,
            trend_strength=TrendStrength.CONFIRMED,
        )
    with pytest.raises(
        DomainValidationError, match="must match the reference-candle grade"
    ):
        _decision(
            direction=Direction.BULLISH,
            entry_type=EntryType.REVERSAL,
            index_close=24825.0,
            current_state=RedBarV2State.PROVISIONAL_BULLISH,
            trend_strength=TrendStrength.PROVISIONAL,
        )


def test_reversal_still_requires_vwap_direction_but_tolerates_rsi():
    value = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.REVERSAL,
        index_close=24810.0,
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    # RSI is informational on the reversal path too: a bearish RSI reading is
    # recorded without invalidating a provisional bullish reversal.
    tolerated = replace(value, rsi=RsiEvidence(38.0, 60.0, 40.0, False, True))
    assert tolerated.trend_strength is TrendStrength.PROVISIONAL
    # Futures VWAP still decides direction and must agree with it.
    with pytest.raises(DomainValidationError, match="VWAP evidence must align with direction"):
        replace(
            value,
            futures_vwap=FuturesVwapEvidence(
                "NSE_FO|NIFTY-FUT",
                24785.0,
                24800.0,
                150000.0,
                False,
                True,
                True,
            ),
        )


def test_provisional_reversal_bundle_round_trip_and_identity_determinism():
    decision = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.REVERSAL,
        index_close=24810.0,
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    first = _bundle(decision)
    second = _bundle(decision)
    assert first.signal_id == second.signal_id
    assert first.bundle_id == second.bundle_id
    assert first.idempotency_key == second.idempotency_key
    assert red_bar_v2_bundle_from_dict(red_bar_v2_bundle_to_dict(first)) == first
