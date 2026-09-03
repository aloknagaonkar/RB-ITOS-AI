from dataclasses import FrozenInstanceError, replace
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
    UnsupportedSchemaVersionError,
    build_red_bar_v2_bundle_id,
    build_red_bar_v2_idempotency_key,
    build_red_bar_v2_signal_id,
    red_bar_v2_bundle_from_dict,
    red_bar_v2_bundle_to_dict,
)

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
EVALUATED_AT = datetime(2026, 8, 24, 10, 5, tzinfo=IST)


def reference() -> RedBarV2Reference:
    return RedBarV2Reference(
        reference_id="RBV2-REF-20260824-0915",
        trading_date=TRADING_DATE,
        timestamp=datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        high=24820.0,
        low=24780.0,
        midpoint=24800.0,
        source="INDEX_1M",
    )


def timestamps(status: ContextStatus = ContextStatus.FRESH) -> MarketTimestampEvidence:
    return MarketTimestampEvidence(
        latest_index_1m=EVALUATED_AT,
        latest_index_5m=EVALUATED_AT,
        latest_futures_1m=EVALUATED_AT,
        latest_futures_5m=EVALUATED_AT,
        evaluated_at=EVALUATED_AT,
        context_status=status,
        maximum_age_seconds=120,
        reason="ALIGNED",
    )


def decision(
    *,
    direction: Direction = Direction.BULLISH,
    option_side: OptionSide = OptionSide.CE,
    outcome: AdmissionOutcome = AdmissionOutcome.ALLOWED,
) -> RedBarV2Decision:
    bullish = direction is Direction.BULLISH
    return RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m",
        entry_type=EntryType.INITIAL if outcome is AdmissionOutcome.ALLOWED else None,
        previous_state=RedBarV2State.REFERENCE_READY,
        current_state=(
            RedBarV2State.CONFIRMED_BULLISH
            if bullish
            else RedBarV2State.CONFIRMED_BEARISH
        ) if outcome is AdmissionOutcome.ALLOWED else RedBarV2State.SIGNAL_WAITING,
        direction=direction if outcome is AdmissionOutcome.ALLOWED else None,
        option_side=option_side if outcome is AdmissionOutcome.ALLOWED else None,
        trend_strength=TrendStrength.CONFIRMED if outcome is AdmissionOutcome.ALLOWED else None,
        reference=reference() if outcome is AdmissionOutcome.ALLOWED else None,
        rsi=RsiEvidence(62.0 if bullish else 38.0, 60.0, 40.0, bullish, not bullish)
        if outcome is AdmissionOutcome.ALLOWED
        else None,
        futures_vwap=FuturesVwapEvidence(
            "NSE_FO|NIFTY-FUT",
            24815.0 if bullish else 24785.0,
            24800.0,
            150000.0,
            bullish,
            not bullish,
            True,
        ) if outcome is AdmissionOutcome.ALLOWED else None,
        midpoint=MidpointEvidence(
            # This builder is CONFIRMED throughout, so the close has to be past the
            # reference candle's own extreme (24820.0 high / 24780.0 low), not just
            # past the 24800.0 midpoint every admitted entry clears.
            24825.0 if bullish else 24775.0,
            24800.0,
            bullish,
            not bullish,
        ) if outcome is AdmissionOutcome.ALLOWED else None,
        context_status=ContextStatus.FRESH,
        admission_outcome=outcome,
        admission_code="RBV2_ALLOWED" if outcome is AdmissionOutcome.ALLOWED else "WAITING",
        admission_reason="All evidence aligned" if outcome is AdmissionOutcome.ALLOWED else "Waiting",
    )


def bundle() -> RedBarV2SignalBundle:
    resolved = decision()
    signal_id = build_red_bar_v2_signal_id(
        strategy_version=resolved.strategy_version,
        instrument_key=resolved.futures_vwap.instrument_key,
        trading_date=TRADING_DATE,
        reference_id=resolved.reference.reference_id,
        evaluation_timestamp=resolved.evaluation_timestamp,
        entry_type=resolved.entry_type,
        direction=resolved.direction,
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
        decision=resolved,
        idempotency_key=build_red_bar_v2_idempotency_key(
            signal_id=signal_id,
            option_side=OptionSide.CE,
        ),
        lifecycle_status=BundleLifecycleStatus.AVAILABLE,
        created_at=datetime(2026, 8, 24, 10, 5, 1, tzinfo=IST),
    )


def working_reference() -> RedBarV2Reference:
    """The deputy: an opposite-colour candle sitting entirely above the red bar.

    Its whole range (24840-24900) is clear of the red bar's high of 24820, which
    is what lets the tests below tell the two levels apart -- a close can be past
    one and short of the other.
    """
    return RedBarV2Reference(
        reference_id="RBV2-REF-20260824-1055",
        trading_date=TRADING_DATE,
        timestamp=datetime(2026, 8, 24, 10, 55, tzinfo=IST),
        high=24900.0,
        low=24840.0,
        midpoint=24870.0,
        source="WORKING_OPPOSITE_CANDLE",
    )


def working_decision(*, index_close: float = 24910.0) -> RedBarV2Decision:
    """An admitted working-reference entry, with no futures VWAP evidence at all.

    `index_close` is the one moving part: past the deputy's high it grades
    CONFIRMED, between its midpoint and its high PROVISIONAL.
    """
    deputy = working_reference()
    cleared = index_close > deputy.high
    return RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m",
        entry_type=EntryType.WORKING,
        previous_state=RedBarV2State.SIGNAL_WAITING,
        current_state=(
            RedBarV2State.CONFIRMED_BULLISH
            if cleared
            else RedBarV2State.PROVISIONAL_BULLISH
        ),
        direction=Direction.BULLISH,
        option_side=OptionSide.CE,
        trend_strength=(
            TrendStrength.CONFIRMED if cleared else TrendStrength.PROVISIONAL
        ),
        reference=deputy,
        rsi=None,
        futures_vwap=None,
        midpoint=MidpointEvidence(index_close, deputy.midpoint, True, False),
        context_status=ContextStatus.FRESH,
        admission_outcome=AdmissionOutcome.ALLOWED,
        admission_code="RBV2_WORKING_REFERENCE_CONFIRMED_FLAT",
        admission_reason="Working reference breakout confirmed on structure alone",
    )


def working_bundle() -> RedBarV2SignalBundle:
    """A schema-1.1 bundle for a working entry.

    Schema 1.1 carries the underlying `instrument_key` itself, which is what makes
    a bundle with no futures VWAP evidence identifiable at all -- on 1.0 the VWAP
    block is the only thing naming an instrument.
    """
    resolved = working_decision()
    instrument_key = "NSE_INDEX|Nifty 50"
    signal_id = build_red_bar_v2_signal_id(
        strategy_version=resolved.strategy_version,
        instrument_key=instrument_key,
        trading_date=TRADING_DATE,
        reference_id=resolved.reference.reference_id,
        evaluation_timestamp=resolved.evaluation_timestamp,
        entry_type=resolved.entry_type,
        direction=resolved.direction,
    )
    return RedBarV2SignalBundle(
        schema_version="1.1",
        bundle_id=build_red_bar_v2_bundle_id(signal_id=signal_id, schema_version="1.1"),
        signal_id=signal_id,
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        evaluation_timestamp=EVALUATED_AT,
        evaluation_timeframe="1m",
        entry_type=EntryType.WORKING,
        direction=Direction.BULLISH,
        option_side=OptionSide.CE,
        decision=resolved,
        idempotency_key=build_red_bar_v2_idempotency_key(
            signal_id=signal_id,
            option_side=OptionSide.CE,
        ),
        lifecycle_status=BundleLifecycleStatus.AVAILABLE,
        created_at=datetime(2026, 8, 24, 10, 5, 1, tzinfo=IST),
        instrument_key=instrument_key,
    )


def test_contracts_are_frozen_and_nested_evidence_is_immutable():
    value = bundle()
    with pytest.raises(FrozenInstanceError):
        value.bundle_id = "changed"
    with pytest.raises(FrozenInstanceError):
        value.decision.rsi.value = 10.0
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize(
    "changes",
    [
        {"high": 24780.0},
        {"midpoint": 24900.0},
        {"high": float("nan")},
        {"low": float("inf")},
        {"timestamp": datetime(2026, 8, 24, 9, 15)},
        {"timestamp": datetime(2026, 8, 25, 9, 15, tzinfo=IST)},
        {"reference_id": ""},
        {"source": ""},
    ],
)
def test_reference_rejects_invalid_contracts(changes):
    values = {
        "reference_id": "REF",
        "trading_date": TRADING_DATE,
        "timestamp": datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        "high": 24820.0,
        "low": 24780.0,
        "midpoint": 24800.0,
        "source": "INDEX_1M",
    }
    values.update(changes)
    with pytest.raises(DomainValidationError):
        RedBarV2Reference(**values)


def test_reference_ready_requires_all_section_one_evidence():
    valid = RedBarV2InputReadiness(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        outcome=RedBarV2Section1Outcome.REFERENCE_READY,
        reference=reference(),
        timestamps=timestamps(),
        futures_instrument_key="NSE_FO|NIFTY-FUT",
        futures_expiry=date(2026, 8, 27),
        futures_volume_available=True,
        futures_vwap_available=True,
        source_name="CURRENT_SESSION",
        source_version="1",
        reason_code="READY",
        reason="Reference and futures ready",
    )
    assert valid.outcome is RedBarV2Section1Outcome.REFERENCE_READY
    with pytest.raises(DomainValidationError):
        replace(valid, reference=None)
    with pytest.raises(DomainValidationError):
        replace(valid, timestamps=timestamps(ContextStatus.STALE))
    with pytest.raises(DomainValidationError):
        replace(valid, futures_vwap_available=False)


def test_waiting_readiness_is_valid_without_reference():
    value = RedBarV2InputReadiness(
        "RED_BAR_V2", "2.0.0", TRADING_DATE,
        RedBarV2Section1Outcome.REFERENCE_WAITING,
        None, timestamps(ContextStatus.UNAVAILABLE), None, None, False, False,
        "CURRENT_SESSION", "1", "WAITING", "Waiting for reference",
    )
    assert value.reference is None


def test_valid_bullish_and_bearish_decisions():
    assert decision().option_side is OptionSide.CE
    assert decision(direction=Direction.BEARISH, option_side=OptionSide.PE).option_side is OptionSide.PE


def test_direction_option_side_and_allowed_evidence_invariants():
    with pytest.raises(DomainValidationError):
        decision(direction=Direction.BULLISH, option_side=OptionSide.PE)
    with pytest.raises(DomainValidationError):
        decision(direction=Direction.BEARISH, option_side=OptionSide.CE)
    # RSI is informational under the futures gates, so an ALLOWED decision
    # stays valid without an RSI evidence block. Wilder RSI(14) is NaN for the
    # first 15 completed candles, and requiring the block here made every
    # warm-up admission unrepresentable.
    assert replace(decision(), rsi=None).rsi is None
    # The gating evidence blocks are still mandatory.
    with pytest.raises(DomainValidationError):
        replace(decision(), futures_vwap=None)
    with pytest.raises(DomainValidationError):
        replace(decision(), midpoint=None)
    with pytest.raises(DomainValidationError):
        replace(decision(), context_status=ContextStatus.STALE)
    with pytest.raises(DomainValidationError):
        replace(decision(), direction=None)
    with pytest.raises(DomainValidationError):
        replace(decision(), evaluation_timeframe="15m")
    assert decision(outcome=AdmissionOutcome.WAITING).direction is None


def test_identity_is_deterministic_sensitive_and_timezone_normalized():
    kwargs = dict(
        strategy_version="2.0.0",
        instrument_key="NSE_FO|NIFTY-FUT",
        trading_date=TRADING_DATE,
        reference_id="REF",
        evaluation_timestamp=EVALUATED_AT,
        entry_type=EntryType.INITIAL,
        direction=Direction.BULLISH,
    )
    first = build_red_bar_v2_signal_id(**kwargs)
    assert first == build_red_bar_v2_signal_id(**kwargs)
    utc_kwargs = {**kwargs, "evaluation_timestamp": EVALUATED_AT.astimezone(timezone.utc)}
    assert first == build_red_bar_v2_signal_id(**utc_kwargs)
    assert first != build_red_bar_v2_signal_id(**{**kwargs, "evaluation_timestamp": EVALUATED_AT + timedelta(minutes=1)})
    assert first != build_red_bar_v2_signal_id(**{**kwargs, "entry_type": EntryType.REVERSAL})
    assert first != build_red_bar_v2_signal_id(**{**kwargs, "direction": Direction.BEARISH})


def test_bundle_validates_nested_contract_and_strategy_identity():
    value = bundle()
    assert value.lifecycle_status is BundleLifecycleStatus.AVAILABLE
    with pytest.raises(DomainValidationError):
        replace(value, strategy_id="OTHER")
    with pytest.raises(DomainValidationError):
        replace(value, direction=Direction.BEARISH)
    with pytest.raises(DomainValidationError):
        replace(value, decision=decision(outcome=AdmissionOutcome.WAITING))
    with pytest.raises(DomainValidationError):
        replace(value, created_at=datetime(2026, 8, 24, 10, 5))


def test_bundle_round_trip_and_stable_encoding():
    value = bundle()
    payload = red_bar_v2_bundle_to_dict(value)
    assert payload["direction"] == "BULLISH"
    assert payload["evaluation_timestamp"].endswith("+05:30")
    assert red_bar_v2_bundle_from_dict(payload) == value


def test_deserialization_rejects_missing_invalid_and_unsupported_data():
    payload = red_bar_v2_bundle_to_dict(bundle())
    missing = dict(payload)
    missing.pop("signal_id")
    with pytest.raises(DomainValidationError):
        red_bar_v2_bundle_from_dict(missing)
    invalid_enum = dict(payload)
    invalid_enum["option_side"] = "CALL"
    with pytest.raises(DomainValidationError):
        red_bar_v2_bundle_from_dict(invalid_enum)
    unsupported = dict(payload)
    unsupported["schema_version"] = "99.0"
    with pytest.raises(UnsupportedSchemaVersionError):
        red_bar_v2_bundle_from_dict(unsupported)
    invalid_numeric = dict(payload)
    invalid_numeric["decision"] = dict(payload["decision"])
    invalid_numeric["decision"]["rsi"] = dict(payload["decision"]["rsi"])
    invalid_numeric["decision"]["rsi"]["value"] = float("nan")
    with pytest.raises(DomainValidationError):
        red_bar_v2_bundle_from_dict(invalid_numeric)


def test_deserialization_rejects_identity_mismatch():
    payload = red_bar_v2_bundle_to_dict(bundle())
    payload["signal_id"] = "RBV2-SIGNAL-WRONG"
    with pytest.raises(BundleIdentityError):
        red_bar_v2_bundle_from_dict(payload)


def test_a_working_entry_is_allowed_with_no_futures_vwap_evidence_at_all():
    """The deputy path consults no VWAP, so requiring one would forbid every entry.

    The exemption is granted to WORKING specifically and not to the two red bar
    paths, which is what the two rejections pin down. Each variant below differs
    from an allowed decision in exactly one way, so the error can only be the
    missing VWAP -- the reversal gets 5m at the same time, or it would fail on the
    timeframe instead and prove nothing about VWAP.
    """
    assert working_decision().futures_vwap is None
    assert working_decision().admission_outcome is AdmissionOutcome.ALLOWED

    with pytest.raises(DomainValidationError, match="futures_vwap"):
        replace(working_decision(), entry_type=EntryType.INITIAL)
    with pytest.raises(DomainValidationError, match="futures_vwap"):
        replace(
            working_decision(),
            entry_type=EntryType.REVERSAL,
            evaluation_timeframe="5m",
        )


def test_only_a_reversal_is_judged_on_five_minutes():
    """A working entry acts on a 1-minute close, like the day's initial entry.

    Both halves are the same decision with one field moved, and the messages name
    the timeframe each path requires, so this cannot pass by raising for some other
    reason.
    """
    with pytest.raises(DomainValidationError, match="requires 1m"):
        replace(working_decision(), evaluation_timeframe="5m")
    with pytest.raises(DomainValidationError, match="requires 5m"):
        replace(decision(), entry_type=EntryType.REVERSAL)


def test_the_grade_is_measured_against_whichever_reference_governed():
    """`reference` holds the governing level, so the grade follows the deputy.

    24880.0 is above the red bar's own high of 24820.0 and below the deputy's
    24900.0. If the invariant re-derived the grade from the red bar it would demand
    CONFIRMED here; against the deputy that actually governed, PROVISIONAL is the
    only valid answer, and claiming CONFIRMED is rejected.
    """
    confirmed = working_decision()
    assert confirmed.reference.source == "WORKING_OPPOSITE_CANDLE"
    assert confirmed.trend_strength is TrendStrength.CONFIRMED

    provisional = working_decision(index_close=24880.0)
    assert provisional.trend_strength is TrendStrength.PROVISIONAL
    assert provisional.midpoint.index_close > reference().high
    with pytest.raises(DomainValidationError, match="reference-candle grade"):
        replace(
            provisional,
            current_state=RedBarV2State.CONFIRMED_BULLISH,
            trend_strength=TrendStrength.CONFIRMED,
        )


def test_a_working_bundle_round_trips_with_its_deputy_intact():
    """The deputy has to survive serialization or the audit trail loses the level.

    Nothing else records which reference a working entry was judged against, so
    `source` coming back as anything else would leave a decision that cannot be
    re-checked.
    """
    value = working_bundle()
    payload = red_bar_v2_bundle_to_dict(value)
    assert payload["entry_type"] == "WORKING"
    assert payload["decision"]["futures_vwap"] is None
    assert payload["decision"]["reference"]["source"] == "WORKING_OPPOSITE_CANDLE"
    restored = red_bar_v2_bundle_from_dict(payload)
    assert restored == value
    assert restored.decision.reference.source == "WORKING_OPPOSITE_CANDLE"


def test_a_bundle_with_no_vwap_evidence_must_name_its_own_instrument():
    """On schema 1.0 the VWAP block is the only thing that names an instrument.

    A working entry has no VWAP block, so without `instrument_key` there is nothing
    to build the signal identity from -- and an unidentifiable bundle is worse than
    a rejected one.
    """
    with pytest.raises(DomainValidationError, match="instrument_key"):
        replace(working_bundle(), schema_version="1.0", instrument_key=None)
