from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    BundleIdentityError,
    BundleLifecycleStatus,
    ContextStatus,
    Direction,
    DomainValidationError,
    EntryType,
    FuturesVwapEvidence,
    MarketTimestampEvidence,
    MidpointEvidence,
    OptionSide,
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2Reference,
    RedBarV2Section1Outcome,
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
    direction: Direction = Direction.BULLISH,
    entry_type: EntryType = EntryType.INITIAL,
    timeframe: str | None = None,
) -> RedBarV2Decision:
    bullish = direction is Direction.BULLISH
    return RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe=timeframe or ("1m" if entry_type is EntryType.INITIAL else "5m"),
        entry_type=entry_type,
        previous_state=RedBarV2State.REFERENCE_READY,
        current_state=(
            RedBarV2State.CONFIRMED_BULLISH
            if bullish
            else RedBarV2State.CONFIRMED_BEARISH
        ),
        direction=direction,
        option_side=OptionSide.CE if bullish else OptionSide.PE,
        trend_strength=TrendStrength.CONFIRMED,
        reference=_reference(),
        rsi=RsiEvidence(62.0 if bullish else 38.0, 60.0, 40.0, bullish, not bullish),
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
            24810.0 if bullish else 24790.0,
            24800.0,
            bullish,
            not bullish,
        ),
        context_status=ContextStatus.FRESH,
        admission_outcome=AdmissionOutcome.ALLOWED,
        admission_code="RBV2_ALLOWED",
        admission_reason="All evidence aligned",
    )


def _bundle() -> RedBarV2SignalBundle:
    decision = _decision()
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
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m",
        entry_type=EntryType.INITIAL,
        direction=Direction.BULLISH,
        option_side=OptionSide.CE,
        decision=decision,
        idempotency_key=build_red_bar_v2_idempotency_key(
            signal_id=signal_id,
            option_side=OptionSide.CE,
        ),
        lifecycle_status=BundleLifecycleStatus.AVAILABLE,
        created_at=datetime(2026, 8, 24, 10, 5, 1, tzinfo=IST),
    )


def test_allowed_bullish_accepts_informational_bearish_rsi():
    # RSI is informational-only: a bearish RSI reading must NOT block an
    # ALLOWED bullish decision. The operational gates are futures VWAP and
    # reference midpoint alignment.
    value = replace(_decision(), rsi=RsiEvidence(38.0, 60.0, 40.0, False, True))
    assert value.rsi.bearish_aligned is True
    assert value.direction is Direction.BULLISH


def test_allowed_bullish_rejects_bearish_futures_vwap_alignment():
    bullish = _decision()
    with pytest.raises(DomainValidationError, match="must align with direction"):
        replace(
            bullish,
            futures_vwap=replace(
                bullish.futures_vwap,
                comparison_price=24785.0,
                bullish_aligned=False,
                bearish_aligned=True,
            ),
        )


def test_allowed_bearish_rejects_bullish_futures_alignment():
    bearish = _decision(direction=Direction.BEARISH)
    with pytest.raises(
        DomainValidationError,
        match="futures VWAP alignment flags must match numeric evidence",
    ):
        replace(
            bearish,
            futures_vwap=replace(
                bearish.futures_vwap,
                bullish_aligned=True,
                bearish_aligned=False,
            ),
        )


def test_allowed_rejects_stale_futures_evidence():
    value = _decision()
    with pytest.raises(DomainValidationError, match="fresh futures VWAP"):
        replace(value, futures_vwap=replace(value.futures_vwap, fresh=False))


def test_allowed_rejects_midpoint_different_from_reference():
    value = _decision()
    with pytest.raises(DomainValidationError, match="match reference midpoint"):
        replace(value, midpoint=replace(value.midpoint, midpoint=24800.01))


@pytest.mark.parametrize("field", ["signal_id", "bundle_id", "idempotency_key"])
def test_direct_bundle_rejects_incorrect_canonical_identity(field):
    with pytest.raises(BundleIdentityError):
        replace(_bundle(), **{field: "WRONG"})


def test_reversal_requires_completed_five_minute_timeframe():
    with pytest.raises(DomainValidationError, match="REVERSAL entry requires 5m"):
        _decision(entry_type=EntryType.REVERSAL, timeframe="1m")
    assert _decision(entry_type=EntryType.REVERSAL, timeframe="5m").evaluation_timeframe == "5m"


def test_deserialization_rejects_numeric_strategy_id():
    payload = red_bar_v2_bundle_to_dict(_bundle())
    payload["strategy_id"] = 123
    with pytest.raises(DomainValidationError, match="strategy_id must be a non-empty string"):
        red_bar_v2_bundle_from_dict(payload)


@pytest.mark.parametrize("bad_value", [1, 0, "yes"])
def test_deserialization_rejects_non_boolean_evidence(bad_value):
    payload = red_bar_v2_bundle_to_dict(_bundle())
    decision = dict(payload["decision"])
    rsi = dict(decision["rsi"])
    rsi["bullish_aligned"] = bad_value
    decision["rsi"] = rsi
    payload["decision"] = decision
    with pytest.raises(DomainValidationError, match="bullish_aligned must be a bool"):
        red_bar_v2_bundle_from_dict(payload)


def test_models_reject_non_v2_strategy_identity():
    with pytest.raises(DomainValidationError, match="strategy_id must be RED_BAR_V2"):
        replace(_decision(), strategy_id="OTHER")

    timestamps = MarketTimestampEvidence(
        latest_index_1m=EVALUATED_AT,
        latest_index_5m=EVALUATED_AT,
        latest_futures_1m=EVALUATED_AT,
        latest_futures_5m=EVALUATED_AT,
        evaluated_at=EVALUATED_AT,
        context_status=ContextStatus.FRESH,
        maximum_age_seconds=120,
        reason="ALIGNED",
    )
    with pytest.raises(DomainValidationError, match="strategy_id must be RED_BAR_V2"):
        RedBarV2InputReadiness(
            strategy_id="OTHER",
            strategy_version="2.0.0",
            trading_date=TRADING_DATE,
            outcome=RedBarV2Section1Outcome.REFERENCE_READY,
            reference=_reference(),
            timestamps=timestamps,
            futures_instrument_key="NSE_FO|NIFTY-FUT",
            futures_expiry=date(2026, 8, 27),
            futures_volume_available=True,
            futures_vwap_available=True,
            source_name="CURRENT_SESSION",
            source_version="1",
            reason_code="READY",
            reason="Ready",
        )


def test_models_reject_non_boolean_flags_directly():
    with pytest.raises(DomainValidationError, match="bullish_aligned must be a bool"):
        RsiEvidence(62.0, 60.0, 40.0, 1, False)
    with pytest.raises(DomainValidationError, match="fresh must be a bool"):
        FuturesVwapEvidence("FUT", 100.0, 99.0, 10.0, True, False, "yes")
