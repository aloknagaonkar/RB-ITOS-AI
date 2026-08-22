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
    midpoint_price: float,
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
            midpoint_price,
            24800.0,
            midpoint_price > 24800.0,
            midpoint_price < 24800.0,
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
        midpoint_price=24810.0,
        current_state=RedBarV2State.CONFIRMED_BULLISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    bearish = _decision(
        direction=Direction.BEARISH,
        entry_type=EntryType.INITIAL,
        midpoint_price=24790.0,
        current_state=RedBarV2State.CONFIRMED_BEARISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    assert bullish.evaluation_timeframe == "1m"
    assert bearish.evaluation_timeframe == "1m"


def test_initial_requires_midpoint_and_cannot_be_provisional():
    with pytest.raises(DomainValidationError, match="INITIAL admission requires midpoint alignment"):
        _decision(
            direction=Direction.BULLISH,
            entry_type=EntryType.INITIAL,
            midpoint_price=24790.0,
            current_state=RedBarV2State.PROVISIONAL_BULLISH,
            trend_strength=TrendStrength.PROVISIONAL,
        )
    confirmed = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.INITIAL,
        midpoint_price=24810.0,
        current_state=RedBarV2State.CONFIRMED_BULLISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    with pytest.raises(DomainValidationError):
        replace(
            confirmed,
            current_state=RedBarV2State.PROVISIONAL_BULLISH,
            trend_strength=TrendStrength.PROVISIONAL,
        )


def test_valid_confirmed_reversals():
    bullish = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.REVERSAL,
        midpoint_price=24810.0,
        current_state=RedBarV2State.CONFIRMED_BULLISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    bearish = _decision(
        direction=Direction.BEARISH,
        entry_type=EntryType.REVERSAL,
        midpoint_price=24790.0,
        current_state=RedBarV2State.CONFIRMED_BEARISH,
        trend_strength=TrendStrength.CONFIRMED,
    )
    assert bullish.evaluation_timeframe == "5m"
    assert bearish.evaluation_timeframe == "5m"


@pytest.mark.parametrize(
    ("direction", "midpoint_price", "state"),
    [
        (Direction.BULLISH, 24790.0, RedBarV2State.PROVISIONAL_BULLISH),
        (Direction.BEARISH, 24810.0, RedBarV2State.PROVISIONAL_BEARISH),
        (Direction.BULLISH, 24800.0, RedBarV2State.PROVISIONAL_BULLISH),
        (Direction.BEARISH, 24800.0, RedBarV2State.PROVISIONAL_BEARISH),
    ],
)
def test_valid_provisional_reversal_without_midpoint_confirmation(
    direction, midpoint_price, state
):
    value = _decision(
        direction=direction,
        entry_type=EntryType.REVERSAL,
        midpoint_price=midpoint_price,
        current_state=state,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    assert value.trend_strength is TrendStrength.PROVISIONAL


def test_reversal_state_and_strength_must_match_midpoint():
    with pytest.raises(DomainValidationError, match="REVERSAL state and trend_strength"):
        _decision(
            direction=Direction.BULLISH,
            entry_type=EntryType.REVERSAL,
            midpoint_price=24790.0,
            current_state=RedBarV2State.CONFIRMED_BULLISH,
            trend_strength=TrendStrength.CONFIRMED,
        )
    with pytest.raises(DomainValidationError, match="REVERSAL state and trend_strength"):
        _decision(
            direction=Direction.BULLISH,
            entry_type=EntryType.REVERSAL,
            midpoint_price=24810.0,
            current_state=RedBarV2State.PROVISIONAL_BULLISH,
            trend_strength=TrendStrength.PROVISIONAL,
        )


def test_reversal_still_requires_rsi_and_vwap_direction():
    value = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.REVERSAL,
        midpoint_price=24790.0,
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    with pytest.raises(DomainValidationError):
        replace(value, rsi=RsiEvidence(38.0, 60.0, 40.0, False, True))


def test_provisional_reversal_bundle_round_trip_and_identity_determinism():
    decision = _decision(
        direction=Direction.BULLISH,
        entry_type=EntryType.REVERSAL,
        midpoint_price=24790.0,
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
        trend_strength=TrendStrength.PROVISIONAL,
    )
    first = _bundle(decision)
    second = _bundle(decision)
    assert first.signal_id == second.signal_id
    assert first.bundle_id == second.bundle_id
    assert first.idempotency_key == second.idempotency_key
    assert red_bar_v2_bundle_from_dict(red_bar_v2_bundle_to_dict(first)) == first
