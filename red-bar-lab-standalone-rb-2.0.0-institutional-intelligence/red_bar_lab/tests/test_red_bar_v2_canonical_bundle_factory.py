from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    ContextStatus,
    EntryType,
    RedBarV2State,
    red_bar_v2_bundle_from_dict,
    red_bar_v2_bundle_to_dict,
)
from red_bar_lab.services.red_bar_v2_canonical import (
    LegacyV2DecisionEvidence,
    LegacyV2MarketMetadata,
    create_red_bar_v2_signal_bundle,
    resolve_red_bar_v2_canonical,
)
from red_bar_lab.services.red_bar_v2_historical_replay import ReplayEvent

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)
REFERENCE_AT = datetime(2026, 8, 24, 9, 20, tzinfo=IST)
RESOLVED_AT = datetime(2026, 8, 24, 10, 5, 1, tzinfo=IST)
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def metadata():
    return LegacyV2MarketMetadata(
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        evaluated_at=EVALUATED_AT,
        source_name="LEGACY_REPLAY",
        source_version="1",
        context_status=ContextStatus.FRESH,
        maximum_age_seconds=120,
        latest_index_1m=EVALUATED_AT,
        latest_index_5m=EVALUATED_AT,
        latest_futures_1m=EVALUATED_AT,
        latest_futures_5m=EVALUATED_AT,
        underlying_instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        futures_expiry=date(2026, 8, 27),
        futures_volume_available=True,
        futures_vwap_available=True,
        reason_code="READY",
        reason="Ready",
        reference_id="REF",
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )


def evidence(*, provisional=False):
    return LegacyV2DecisionEvidence(
        underlying_instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="5m" if provisional else "1m",
        index_close=24790.0 if provisional else 24810.0,
        rsi_value=62.0,
        bullish_rsi_threshold=60.0,
        bearish_rsi_threshold=40.0,
        futures_comparison_price=24815.0,
        futures_vwap=24800.0,
        futures_volume=150000.0,
        futures_fresh=True,
        index_context_timestamp=EVALUATED_AT,
        futures_source_timestamp=EVALUATED_AT,
        reference_id="REF",
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )


def event(*, allowed=True, provisional=False):
    return ReplayEvent(
        timestamp=EVALUATED_AT,
        event_type="CANDIDATE_ADMISSION",
        direction="BULLISH" if allowed else None,
        option_side="CE" if allowed else None,
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT" if provisional else "INITIAL_BULLISH_ALIGNMENT",
        candidate_allowed=allowed,
        trade_id="RBV2-1" if allowed else None,
        details={
            "entry_type": ("REVERSAL" if provisional else "INITIAL") if allowed else None,
            "trend_strength": ("PROVISIONAL" if provisional else "CONFIRMED") if allowed else None,
            "admission_reason": "Legacy result",
            "reference_timestamp": REFERENCE_AT.isoformat(),
            "context_timestamp": EVALUATED_AT.isoformat(),
            "conditions": {
                "rsi_aligned": True,
                "vwap_aligned": True,
                "midpoint_aligned": not provisional,
            },
        },
    )


def resolve(*, allowed=True, provisional=False):
    return resolve_red_bar_v2_canonical(
        replay=SimpleNamespace(
            instrument_key=UNDERLYING,
            trading_date=TRADING_DATE.isoformat(),
            reference_timestamp=REFERENCE_AT,
            reference_midpoint=24800.0,
        ),
        health=SimpleNamespace(status="READY", futures_instrument_key=FUTURES),
        replay_event=event(allowed=allowed, provisional=provisional),
        market_metadata=metadata(),
        evidence=evidence(provisional=provisional) if allowed else None,
        source_replay_id="REPLAY-1",
        resolved_at=RESOLVED_AT,
    )


def test_allowed_initial_resolution_creates_bundle_with_separate_instruments():
    result = resolve()
    assert result.section_2.admission_outcome is AdmissionOutcome.ALLOWED
    assert result.section_3 is not None
    assert result.section_3.entry_type is EntryType.INITIAL
    assert result.section_3.instrument_key == UNDERLYING
    assert result.section_3.decision.futures_vwap.instrument_key == FUTURES


def test_waiting_or_rejected_resolution_creates_no_bundle():
    result = resolve(allowed=False)
    assert result.section_2.admission_outcome is AdmissionOutcome.REJECTED
    assert result.section_3 is None


def test_provisional_reversal_resolution_creates_supported_bundle():
    result = resolve(provisional=True)
    assert result.section_2.current_state is RedBarV2State.PROVISIONAL_BULLISH
    assert result.section_3 is not None
    assert result.section_3.entry_type is EntryType.REVERSAL
    assert result.section_3.evaluation_timeframe == "5m"


def test_repeated_resolution_produces_identical_underlying_identity():
    first = resolve(provisional=True).section_3
    second = resolve(provisional=True).section_3
    assert first is not None and second is not None
    assert first.signal_id == second.signal_id
    assert first.bundle_id == second.bundle_id
    assert first.idempotency_key == second.idempotency_key


def test_underlying_instrument_changes_signal_identity_but_futures_source_does_not():
    bundle = resolve().section_3
    assert bundle is not None
    alternate = create_red_bar_v2_signal_bundle(
        instrument_key="NSE_INDEX|Nifty Bank",
        decision=bundle.decision,
        created_at=RESOLVED_AT,
    )
    assert alternate is not None
    assert alternate.signal_id != bundle.signal_id
    assert alternate.decision.futures_vwap.instrument_key == bundle.decision.futures_vwap.instrument_key


def test_explicit_underlying_round_trips_through_serialization():
    bundle = resolve(provisional=True).section_3
    assert bundle is not None
    assert red_bar_v2_bundle_from_dict(red_bar_v2_bundle_to_dict(bundle)) == bundle


def test_bundle_factory_returns_none_for_non_allowed_decision():
    rejected = resolve(allowed=False).section_2
    assert create_red_bar_v2_signal_bundle(
        instrument_key=UNDERLYING,
        decision=rejected,
        created_at=RESOLVED_AT,
    ) is None
