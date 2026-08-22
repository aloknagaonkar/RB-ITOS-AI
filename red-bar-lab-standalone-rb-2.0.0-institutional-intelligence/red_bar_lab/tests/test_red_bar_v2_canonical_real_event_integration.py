from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from red_bar_lab.domain.red_bar_v2 import ContextStatus, RedBarV2State
from red_bar_lab.intelligence.red_bar_v2_futures_context import RedBarV2VwapSourceHealth
from red_bar_lab.services.red_bar_v2_canonical import (
    CanonicalResolutionError,
    LegacyV2DecisionEvidence,
    LegacyV2MarketMetadata,
    benchmark_resolver_mapping,
    evidence_to_event_details,
    resolve_red_bar_v2_canonical,
)
from red_bar_lab.services.red_bar_v2_historical_replay import ReplayEvent

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)
REFERENCE_AT = datetime(2026, 8, 24, 9, 20, tzinfo=IST)
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def evidence(*, underlying=UNDERLYING) -> LegacyV2DecisionEvidence:
    return LegacyV2DecisionEvidence(
        underlying_instrument_key=underlying,
        futures_instrument_key=FUTURES,
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="5m",
        index_close=24790.0,
        rsi_value=62.0,
        bullish_rsi_threshold=55.0,
        bearish_rsi_threshold=45.0,
        futures_comparison_price=24815.0,
        futures_vwap=24800.0,
        futures_volume=150000.0,
        futures_fresh=True,
        index_context_timestamp=EVALUATED_AT,
        futures_source_timestamp=EVALUATED_AT,
        reference_id=f"RBV2-REF-{TRADING_DATE.isoformat()}-{REFERENCE_AT.isoformat()}",
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )


def metadata() -> LegacyV2MarketMetadata:
    value = evidence()
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
        reference_id=value.reference_id,
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )


def health() -> RedBarV2VwapSourceHealth:
    return RedBarV2VwapSourceHealth(
        status="READY",
        reason="FULL_TIMESTAMP_ALIGNMENT",
        price_source_instrument=UNDERLYING,
        rsi_source_instrument=UNDERLYING,
        vwap_source_instrument=FUTURES,
        timeframe="5M",
        index_rows=50,
        futures_rows=50,
        aligned_rows=50,
        alignment_coverage_pct=100.0,
        positive_volume_rows=50,
        index_timestamp=EVALUATED_AT,
        futures_timestamp=EVALUATED_AT,
        last_aligned_timestamp=EVALUATED_AT,
    )


def event_from_evidence(value: LegacyV2DecisionEvidence) -> ReplayEvent:
    details = evidence_to_event_details(value)
    details.update(
        {
            "entry_type": "REVERSAL",
            "trend_strength": "PROVISIONAL",
            "admission_reason": "Opposite 5-minute RSI/VWAP reversal is aligned",
            "context_timestamp": EVALUATED_AT.isoformat(),
            "conditions": {
                "rsi_aligned": True,
                "vwap_aligned": True,
                "midpoint_aligned": False,
            },
        }
    )
    return ReplayEvent(
        timestamp=EVALUATED_AT,
        event_type="CANDIDATE_ADMISSION",
        direction="BULLISH",
        option_side="CE",
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT",
        candidate_allowed=True,
        trade_id="RBV2-0001",
        details=details,
    )


def resolve(event: ReplayEvent):
    return resolve_red_bar_v2_canonical(
        replay=SimpleNamespace(
            instrument_key=UNDERLYING,
            trading_date=TRADING_DATE.isoformat(),
            reference_timestamp=REFERENCE_AT,
            reference_midpoint=24800.0,
        ),
        health=health(),
        replay_event=event,
        market_metadata=metadata(),
        evidence=None,
        source_replay_id="REPLAY-REAL-1",
        resolved_at=EVALUATED_AT,
    )


def test_resolver_consumes_authoritative_evidence_from_real_replay_event_details():
    result = resolve(event_from_evidence(evidence()))
    assert result.section_2.current_state is RedBarV2State.PROVISIONAL_BULLISH
    assert result.section_3 is not None
    assert result.section_3.instrument_key == UNDERLYING
    assert result.section_3.decision.futures_vwap.instrument_key == FUTURES


def test_resolver_rejects_event_underlying_disagreement():
    with pytest.raises(CanonicalResolutionError, match="underlying instrument"):
        resolve(event_from_evidence(evidence(underlying="OTHER")))


def test_actual_mapping_benchmark_is_recorded_under_target():
    prepared = event_from_evidence(evidence())
    average_ms = benchmark_resolver_mapping(100, lambda: resolve(prepared))
    assert average_ms < 5.0
