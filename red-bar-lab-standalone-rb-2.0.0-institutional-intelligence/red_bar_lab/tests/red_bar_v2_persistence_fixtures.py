from datetime import date, datetime, timedelta, timezone

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    ContextStatus,
    Direction,
    EntryType,
    FuturesVwapEvidence,
    MarketTimestampEvidence,
    MidpointEvidence,
    OptionSide,
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2Reference,
    RedBarV2Section1Outcome,
    RedBarV2State,
    RsiEvidence,
    TrendStrength,
)
from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalResolution,
    RedBarV2ParityResult,
    create_red_bar_v2_signal_bundle,
)

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
REFERENCE_AT = datetime(2026, 8, 24, 9, 20, tzinfo=IST)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)
RESOLVED_AT = datetime(2026, 8, 24, 10, 5, 1, tzinfo=IST)
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def make_resolution(*, allowed: bool = True, provisional: bool = False):
    reference = RedBarV2Reference(
        reference_id="RBV2-REF-2026-08-24-0920",
        trading_date=TRADING_DATE,
        timestamp=REFERENCE_AT,
        high=24820.0,
        low=24780.0,
        midpoint=24800.0,
        source="NEXT_RED_CANDLE",
    )
    timestamps = MarketTimestampEvidence(
        latest_index_1m=EVALUATED_AT,
        latest_index_5m=EVALUATED_AT,
        latest_futures_1m=EVALUATED_AT,
        latest_futures_5m=EVALUATED_AT,
        evaluated_at=EVALUATED_AT,
        context_status=ContextStatus.FRESH,
        maximum_age_seconds=120,
        reason="Authoritative futures context aligned",
    )
    readiness = RedBarV2InputReadiness(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        outcome=RedBarV2Section1Outcome.REFERENCE_READY,
        reference=reference,
        timestamps=timestamps,
        futures_instrument_key=FUTURES,
        futures_expiry=date(2026, 8, 27),
        futures_volume_available=True,
        futures_vwap_available=True,
        source_name="FUTURES_AWARE_REPLAY",
        source_version="1",
        reason_code="READY",
        reason="Ready",
    )
    entry_type = EntryType.REVERSAL if provisional else EntryType.INITIAL
    direction = Direction.BULLISH if allowed else None
    option_side = OptionSide.CE if allowed else None
    strength = TrendStrength.PROVISIONAL if provisional else TrendStrength.CONFIRMED if allowed else None
    state = RedBarV2State.PROVISIONAL_BULLISH if provisional else RedBarV2State.CONFIRMED_BULLISH if allowed else RedBarV2State.SIGNAL_WAITING
    decision = RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="5m" if provisional else "1m",
        entry_type=entry_type if allowed else None,
        previous_state=RedBarV2State.REFERENCE_READY,
        current_state=state,
        direction=direction,
        option_side=option_side,
        trend_strength=strength,
        reference=reference,
        rsi=RsiEvidence(62.0, 55.0, 45.0, True, False) if allowed else None,
        futures_vwap=FuturesVwapEvidence(FUTURES, 24815.0, 24800.0, 150000.0, True, False, True) if allowed else None,
        midpoint=MidpointEvidence(24790.0 if provisional else 24810.0, 24800.0, not provisional, provisional) if allowed else None,
        context_status=ContextStatus.FRESH,
        admission_outcome=AdmissionOutcome.ALLOWED if allowed else AdmissionOutcome.REJECTED,
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT" if provisional else "INITIAL_BULLISH_ALIGNMENT" if allowed else "ACTIVE_TRADE_BLOCK",
        admission_reason="Fixture canonical decision",
    )
    bundle = create_red_bar_v2_signal_bundle(
        instrument_key=UNDERLYING,
        decision=decision,
        created_at=RESOLVED_AT,
    ) if allowed else None
    resolution = RedBarV2CanonicalResolution(
        section_1=readiness,
        section_2=decision,
        section_3=bundle,
        source_replay_id="REPLAY-PERSISTENCE-1",
        resolved_at=RESOLVED_AT,
    )
    parity = RedBarV2ParityResult(
        matches=True,
        mismatches=(),
        legacy_direction=direction.value if direction else None,
        canonical_direction=direction,
        legacy_option_side=option_side.value if option_side else None,
        canonical_option_side=option_side,
        legacy_allowed=allowed,
        canonical_allowed=allowed,
        legacy_entry_type=entry_type.value if allowed else None,
        canonical_entry_type=entry_type if allowed else None,
        legacy_timeframe=decision.evaluation_timeframe,
        canonical_timeframe=decision.evaluation_timeframe,
        legacy_trend_strength=strength.value if strength else None,
        canonical_trend_strength=strength,
        legacy_admission_code=decision.admission_code,
        canonical_admission_code=decision.admission_code,
    )
    return resolution, parity
