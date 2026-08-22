from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    ContextStatus,
    Direction,
    EntryType,
    RedBarV2Section1Outcome,
    RedBarV2State,
    TrendStrength,
)
from red_bar_lab.intelligence.red_bar_v2_futures_context import RedBarV2VwapSourceHealth
from red_bar_lab.services.red_bar_v2_canonical import (
    LegacyMappingError,
    LegacyV2DecisionEvidence,
    LegacyV2MarketMetadata,
    build_canonical_decision,
    build_canonical_input_readiness,
)
from red_bar_lab.services.red_bar_v2_historical_replay import ReplayEvent

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)
REFERENCE_AT = datetime(2026, 8, 24, 9, 20, tzinfo=IST)
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def replay(*, with_reference=True, instrument_key=UNDERLYING):
    return SimpleNamespace(
        instrument_key=instrument_key,
        trading_date=TRADING_DATE.isoformat(),
        reference_timestamp=REFERENCE_AT if with_reference else None,
        reference_midpoint=24800.0 if with_reference else None,
    )


def health(
    *,
    status="READY",
    price_key=UNDERLYING,
    rsi_key=UNDERLYING,
    futures_key=FUTURES,
):
    return RedBarV2VwapSourceHealth(
        status=status,
        reason="FULL_TIMESTAMP_ALIGNMENT" if status == "READY" else "BLOCKED",
        price_source_instrument=price_key,
        rsi_source_instrument=rsi_key,
        vwap_source_instrument=futures_key,
        timeframe="1M",
        index_rows=50,
        futures_rows=50,
        aligned_rows=50,
        alignment_coverage_pct=100.0,
        positive_volume_rows=50,
        index_timestamp=EVALUATED_AT,
        futures_timestamp=EVALUATED_AT,
        last_aligned_timestamp=EVALUATED_AT,
    )


def metadata(*, status=ContextStatus.FRESH, with_reference=True):
    return LegacyV2MarketMetadata(
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        evaluated_at=EVALUATED_AT,
        source_name="LEGACY_REPLAY",
        source_version="1",
        context_status=status,
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
        reason="Legacy event-time inputs are aligned",
        reference_id="REF-20260824-0920" if with_reference else None,
        reference_timestamp=REFERENCE_AT if with_reference else None,
        reference_high=24820.0 if with_reference else None,
        reference_low=24780.0 if with_reference else None,
        reference_midpoint=24800.0 if with_reference else None,
        reference_source="NEXT_RED_CANDLE" if with_reference else None,
    )


def evidence(*, direction="BULLISH", entry_type="INITIAL", midpoint_aligned=True):
    bullish = direction == "BULLISH"
    return LegacyV2DecisionEvidence(
        underlying_instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m" if entry_type == "INITIAL" else "5m",
        index_close=(24810.0 if midpoint_aligned else 24790.0) if bullish else (24790.0 if midpoint_aligned else 24810.0),
        rsi_value=62.0 if bullish else 38.0,
        bullish_rsi_threshold=60.0,
        bearish_rsi_threshold=40.0,
        futures_comparison_price=24815.0 if bullish else 24785.0,
        futures_vwap=24800.0,
        futures_volume=150000.0,
        futures_fresh=True,
        index_context_timestamp=EVALUATED_AT,
        futures_source_timestamp=EVALUATED_AT,
        reference_id="REF-20260824-0920",
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )


def event(*, direction="BULLISH", entry_type="INITIAL", strength="CONFIRMED", allowed=True):
    bullish = direction == "BULLISH"
    midpoint_aligned = strength == "CONFIRMED"
    return ReplayEvent(
        timestamp=EVALUATED_AT,
        event_type="CANDIDATE_ADMISSION",
        direction=direction,
        option_side="CE" if bullish else "PE",
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT" if entry_type == "REVERSAL" else "INITIAL_BULLISH_ALIGNMENT" if bullish else "INITIAL_BEARISH_ALIGNMENT",
        candidate_allowed=allowed,
        trade_id="RBV2-0001" if allowed else None,
        details={
            "entry_type": entry_type,
            "trend_strength": strength,
            "admission_reason": "Legacy admission result",
            "reference_timestamp": REFERENCE_AT.isoformat(),
            "context_timestamp": EVALUATED_AT.isoformat(),
            "conditions": {
                "rsi_aligned": True,
                "vwap_aligned": True,
                "midpoint_aligned": midpoint_aligned,
            },
        },
    )


def readiness(**kwargs):
    with_reference = kwargs.get("with_reference", True)
    return build_canonical_input_readiness(
        replay=replay(with_reference=with_reference),
        health=health(),
        market_metadata=metadata(**kwargs),
    )


def test_section_one_uses_replay_and_health_authority():
    assert readiness().outcome is RedBarV2Section1Outcome.REFERENCE_READY
    assert readiness(with_reference=False).outcome is RedBarV2Section1Outcome.REFERENCE_WAITING
    assert readiness(status=ContextStatus.STALE).outcome is RedBarV2Section1Outcome.CANDLES_STALE
    assert readiness(status=ContextStatus.MISALIGNED).outcome is RedBarV2Section1Outcome.SESSION_MISALIGNED

    unavailable = build_canonical_input_readiness(
        replay=replay(), health=health(status="BLOCKED"), market_metadata=metadata()
    )
    assert unavailable.outcome is RedBarV2Section1Outcome.VWAP_SOURCE_NOT_READY


def test_section_one_rejects_authoritative_disagreement():
    with pytest.raises(LegacyMappingError, match="underlying instrument"):
        build_canonical_input_readiness(
            replay=replay(instrument_key="OTHER"), health=health(), market_metadata=metadata()
        )
    with pytest.raises(LegacyMappingError, match="price source instrument"):
        build_canonical_input_readiness(
            replay=replay(), health=health(price_key="OTHER"), market_metadata=metadata()
        )
    with pytest.raises(LegacyMappingError, match="RSI source instrument"):
        build_canonical_input_readiness(
            replay=replay(), health=health(rsi_key="OTHER"), market_metadata=metadata()
        )
    with pytest.raises(LegacyMappingError, match="VWAP source instrument"):
        build_canonical_input_readiness(
            replay=replay(), health=health(futures_key="OTHER"), market_metadata=metadata()
        )


@pytest.mark.parametrize(
    "direction,expected_state,expected_side",
    [
        ("BULLISH", RedBarV2State.CONFIRMED_BULLISH, "CE"),
        ("BEARISH", RedBarV2State.CONFIRMED_BEARISH, "PE"),
    ],
)
def test_real_initial_event_maps_without_recalculation(direction, expected_state, expected_side):
    result = build_canonical_decision(
        replay_event=event(direction=direction),
        readiness=readiness(),
        evidence=evidence(direction=direction),
    )
    assert result.admission_outcome is AdmissionOutcome.ALLOWED
    assert result.entry_type is EntryType.INITIAL
    assert result.current_state is expected_state
    assert result.option_side.value == expected_side


@pytest.mark.parametrize(
    "direction,midpoint_aligned,expected_state,expected_strength",
    [
        ("BULLISH", True, RedBarV2State.CONFIRMED_BULLISH, TrendStrength.CONFIRMED),
        ("BEARISH", True, RedBarV2State.CONFIRMED_BEARISH, TrendStrength.CONFIRMED),
        ("BULLISH", False, RedBarV2State.PROVISIONAL_BULLISH, TrendStrength.PROVISIONAL),
        ("BEARISH", False, RedBarV2State.PROVISIONAL_BEARISH, TrendStrength.PROVISIONAL),
    ],
)
def test_real_reversal_event_preserves_confirmed_and_provisional_semantics(direction, midpoint_aligned, expected_state, expected_strength):
    strength = "CONFIRMED" if midpoint_aligned else "PROVISIONAL"
    result = build_canonical_decision(
        replay_event=event(direction=direction, entry_type="REVERSAL", strength=strength),
        readiness=readiness(),
        evidence=evidence(direction=direction, entry_type="REVERSAL", midpoint_aligned=midpoint_aligned),
    )
    assert result.current_state is expected_state
    assert result.trend_strength is expected_strength
    assert result.evaluation_timeframe == "5m"


def test_real_rejected_event_maps_without_bundle_evidence():
    result = build_canonical_decision(
        replay_event=event(allowed=False), readiness=readiness(), evidence=None
    )
    assert result.admission_outcome is AdmissionOutcome.REJECTED
    assert result.current_state is RedBarV2State.SIGNAL_WAITING


def test_allowed_event_requires_complete_event_time_evidence():
    with pytest.raises(LegacyMappingError, match="complete event-time evidence"):
        build_canonical_decision(replay_event=event(), readiness=readiness(), evidence=None)


def test_adapter_rejects_direction_evidence_disagreement():
    with pytest.raises(Exception):
        build_canonical_decision(
            replay_event=event(direction="BULLISH"),
            readiness=readiness(),
            evidence=evidence(direction="BEARISH"),
        )
