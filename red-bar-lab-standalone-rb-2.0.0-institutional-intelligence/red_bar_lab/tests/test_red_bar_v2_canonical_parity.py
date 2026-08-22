from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from red_bar_lab.domain.red_bar_v2 import ContextStatus
from red_bar_lab.services.red_bar_v2_canonical import (
    LegacyV2DecisionEvidence,
    LegacyV2MarketMetadata,
    compare_legacy_to_canonical,
    resolve_red_bar_v2_canonical,
)

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)
REFERENCE_AT = datetime(2026, 8, 24, 9, 20, tzinfo=IST)


def _event():
    return SimpleNamespace(
        candidate_allowed=True,
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT",
        admission_reason="Legacy provisional reversal",
        direction="BULLISH",
        option_side="CE",
        entry_type="REVERSAL",
        trend_strength="PROVISIONAL",
        reference_timestamp=REFERENCE_AT.isoformat(),
        context_timestamp=EVALUATED_AT.isoformat(),
        conditions={
            "rsi_aligned": True,
            "vwap_aligned": True,
            "midpoint_aligned": False,
        },
    )


def _resolution():
    metadata = LegacyV2MarketMetadata(
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
        futures_instrument_key="NSE_FO|NIFTY-FUT",
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
    evidence = LegacyV2DecisionEvidence(
        instrument_key="NSE_FO|NIFTY-FUT",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="5m",
        index_close=24790.0,
        rsi_value=62.0,
        bullish_rsi_threshold=60.0,
        bearish_rsi_threshold=40.0,
        futures_comparison_price=24815.0,
        futures_vwap=24800.0,
        futures_volume=150000.0,
        futures_fresh=True,
        reference_id="REF",
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )
    event = _event()
    resolution = resolve_red_bar_v2_canonical(
        replay=SimpleNamespace(),
        health=SimpleNamespace(),
        replay_event=event,
        market_metadata=metadata,
        evidence=evidence,
        source_replay_id="REPLAY-1",
        resolved_at=EVALUATED_AT,
    )
    return event, resolution


def test_matching_provisional_reversal_parity():
    event, resolution = _resolution()
    parity = compare_legacy_to_canonical(
        legacy_event=event,
        canonical_decision=resolution.section_2,
        legacy_timeframe="5m",
    )
    assert parity.matches is True
    assert parity.mismatches == ()


def test_parity_mismatch_is_observable_only():
    event, resolution = _resolution()
    event.option_side = "PE"
    parity = compare_legacy_to_canonical(
        legacy_event=event,
        canonical_decision=resolution.section_2,
        legacy_timeframe="5m",
    )
    assert parity.matches is False
    assert "option_side" in parity.mismatches
    assert resolution.section_3 is not None
