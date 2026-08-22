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
from red_bar_lab.services.red_bar_v2_canonical import (
    LegacyMappingError,
    LegacyV2DecisionEvidence,
    LegacyV2MarketMetadata,
    build_canonical_decision,
    build_canonical_input_readiness,
)

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)
REFERENCE_AT = datetime(2026, 8, 24, 9, 20, tzinfo=IST)


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
        futures_instrument_key="NSE_FO|NIFTY-FUT",
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
    if bullish:
        index_close = 24810.0 if midpoint_aligned else 24790.0
        rsi = 62.0
        futures_price = 24815.0
    else:
        index_close = 24790.0 if midpoint_aligned else 24810.0
        rsi = 38.0
        futures_price = 24785.0
    return LegacyV2DecisionEvidence(
        instrument_key="NSE_FO|NIFTY-FUT",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m" if entry_type == "INITIAL" else "5m",
        index_close=index_close,
        rsi_value=rsi,
        bullish_rsi_threshold=60.0,
        bearish_rsi_threshold=40.0,
        futures_comparison_price=futures_price,
        futures_vwap=24800.0,
        futures_volume=150000.0,
        futures_fresh=True,
        reference_id="REF-20260824-0920",
        reference_timestamp=REFERENCE_AT,
        reference_high=24820.0,
        reference_low=24780.0,
        reference_midpoint=24800.0,
        reference_source="NEXT_RED_CANDLE",
    )


def event(*, direction="BULLISH", entry_type="INITIAL", strength="CONFIRMED", allowed=True):
    return SimpleNamespace(
        candidate_allowed=allowed,
        admission_code="ALLOWED" if allowed else "ACTIVE_TRADE_BLOCK",
        admission_reason="Legacy admission result",
        direction=direction,
        option_side="CE" if direction == "BULLISH" else "PE",
        entry_type=entry_type,
        trend_strength=strength,
        reference_timestamp=REFERENCE_AT.isoformat(),
        context_timestamp=EVALUATED_AT.isoformat(),
        conditions={},
    )


def readiness(**kwargs):
    return build_canonical_input_readiness(
        replay=SimpleNamespace(),
        health=SimpleNamespace(),
        market_metadata=metadata(**kwargs),
    )


def test_section_one_maps_ready_waiting_stale_and_misaligned():
    assert readiness().outcome is RedBarV2Section1Outcome.REFERENCE_READY
    assert readiness(with_reference=False).outcome is RedBarV2Section1Outcome.REFERENCE_WAITING
    assert readiness(status=ContextStatus.STALE).outcome is RedBarV2Section1Outcome.CANDLES_STALE
    assert readiness(status=ContextStatus.MISALIGNED).outcome is RedBarV2Section1Outcome.SESSION_MISALIGNED


@pytest.mark.parametrize(
    "direction,expected_state,expected_side",
    [
        ("BULLISH", RedBarV2State.CONFIRMED_BULLISH, "CE"),
        ("BEARISH", RedBarV2State.CONFIRMED_BEARISH, "PE"),
    ],
)
def test_initial_admission_maps_without_recalculation(direction, expected_state, expected_side):
    result = build_canonical_decision(
        replay_event=event(direction=direction),
        readiness=readiness(),
        evidence=evidence(direction=direction),
    )
    assert result.admission_outcome is AdmissionOutcome.ALLOWED
    assert result.entry_type is EntryType.INITIAL
    assert result.current_state is expected_state
    assert result.option_side.value == expected_side
    assert result.evaluation_timeframe == "1m"


@pytest.mark.parametrize(
    "direction,midpoint_aligned,expected_state,expected_strength",
    [
        ("BULLISH", True, RedBarV2State.CONFIRMED_BULLISH, TrendStrength.CONFIRMED),
        ("BEARISH", True, RedBarV2State.CONFIRMED_BEARISH, TrendStrength.CONFIRMED),
        ("BULLISH", False, RedBarV2State.PROVISIONAL_BULLISH, TrendStrength.PROVISIONAL),
        ("BEARISH", False, RedBarV2State.PROVISIONAL_BEARISH, TrendStrength.PROVISIONAL),
    ],
)
def test_reversal_admission_preserves_confirmed_and_provisional_semantics(
    direction,
    midpoint_aligned,
    expected_state,
    expected_strength,
):
    strength = "CONFIRMED" if midpoint_aligned else "PROVISIONAL"
    result = build_canonical_decision(
        replay_event=event(direction=direction, entry_type="REVERSAL", strength=strength),
        readiness=readiness(),
        evidence=evidence(
            direction=direction,
            entry_type="REVERSAL",
            midpoint_aligned=midpoint_aligned,
        ),
    )
    assert result.current_state is expected_state
    assert result.trend_strength is expected_strength
    assert result.evaluation_timeframe == "5m"


def test_rejected_legacy_candidate_maps_without_bundle_requirements():
    result = build_canonical_decision(
        replay_event=event(allowed=False),
        readiness=readiness(),
        evidence=None,
    )
    assert result.admission_outcome is AdmissionOutcome.REJECTED
    assert result.current_state is RedBarV2State.SIGNAL_WAITING


def test_allowed_event_requires_complete_event_time_evidence():
    with pytest.raises(LegacyMappingError, match="complete event-time evidence"):
        build_canonical_decision(
            replay_event=event(),
            readiness=readiness(),
            evidence=None,
        )


def test_adapter_rejects_direction_evidence_disagreement():
    with pytest.raises(Exception):
        build_canonical_decision(
            replay_event=event(direction="BULLISH"),
            readiness=readiness(),
            evidence=evidence(direction="BEARISH"),
        )
