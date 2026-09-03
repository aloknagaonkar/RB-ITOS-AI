"""Regressions for the RSI warm-up blackout and the RedBar+VWAP audit row.

Wilder RSI(14) is NaN until 15 completed candles exist. The futures context
used to discard the whole snapshot in that window, so the 1-minute initial path
was blind until 09:30 IST and the 5-minute reversal path until 10:30 -- 75
minutes of every session in which no decision was evaluated at all. RSI is
informational under the futures gates, so absence of an RSI reading must not
suppress evaluation, and the gating RedBar+VWAP evidence must reach the audit
trail under its own name.
"""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    ContextStatus,
    Direction,
    EntryType,
    FuturesVwapEvidence,
    MidpointEvidence,
    OptionSide,
    RedBarV2Decision,
    TrendStrength,
)
from red_bar_lab.domain.red_bar_v2 import RedBarV2Reference as DomainReference
from red_bar_lab.domain.red_bar_v2 import RedBarV2State as DomainState
from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import (
    TradeLifecycleState,
    TradeStateSnapshot,
)
from red_bar_lab.intelligence.market_context import rsi_alignment_state
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2FuturesSnapshot,
    build_red_bar_v2_futures_snapshot,
)
from red_bar_lab.services.red_bar_v2_canonical import (
    LegacyV2DecisionEvidence,
    build_legacy_v2_decision_evidence,
    evidence_from_event_details,
    evidence_to_event_details,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2Reference,
    RedBarV2State,
    evaluate_reversal_direction,
)
from red_bar_lab.strategy.red_bar_v2_futures import (
    evaluate_initial_direction_futures,
    evaluate_reversal_direction_futures,
)

IST = "Asia/Kolkata"
TRADING_DATE = "2026-08-18"


def _ist(hour: int, minute: int) -> datetime:
    return pd.Timestamp(
        f"{TRADING_DATE} {hour:02d}:{minute:02d}", tz=IST
    ).to_pydatetime()


def _frame(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range(
        f"{TRADING_DATE} 09:15", periods=len(closes), freq="1min", tz=IST
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": volumes,
        }
    )


def _reference(midpoint: float = 100.0) -> RedBarV2Reference:
    return RedBarV2Reference(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date=TRADING_DATE,
        reference_timestamp=_ist(9, 25),
        reference_open=midpoint + 2.0,
        reference_high=midpoint + 5.0,
        reference_low=midpoint - 5.0,
        reference_close=midpoint - 2.0,
        midpoint=midpoint,
    )


def _snapshot(
    *,
    timeframe: str = "1M",
    close: float = 110.0,
    futures_price: float = 210.0,
    vwap: float = 205.0,
    rsi: float | None = None,
    candle_timestamp: datetime | None = None,
) -> RedBarV2FuturesSnapshot:
    stamp = candle_timestamp or _ist(10, 0)
    return RedBarV2FuturesSnapshot(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date=TRADING_DATE,
        timeframe=timeframe,
        candle_timestamp=stamp,
        candle_open=close - 1.0,
        candle_high=close + 1.0,
        candle_low=close - 2.0,
        candle_close=close,
        candle_volume=0.0,
        rsi_period=14,
        rsi_value=rsi,
        vwap_value=vwap,
        price_vs_vwap="ABOVE" if futures_price > vwap else "BELOW",
        rsi_state=rsi_alignment_state(rsi),
        source="RED_BAR_V2_INDEX_RSI_FUTURES_VWAP_V1",
        data_quality="VALID",
        fresh=True,
        vwap_comparison_price=futures_price,
        vwap_source_instrument_key="NSE_FO|58072",
        vwap_source_timestamp=stamp,
        vwap_source_volume=150000.0,
    )


def _flat_trade_state() -> TradeStateSnapshot:
    return TradeStateSnapshot(
        lifecycle_state=TradeLifecycleState.FLAT,
        active_trade=None,
        latest_executed_trade=None,
        previous_trade_closed=True,
        has_pending_trade=False,
        active_trade_count=0,
        pending_trade_count=0,
        conflict_reason=None,
    )


def test_one_minute_snapshot_survives_the_rsi_warm_up():
    """Before 09:30 IST there is no RSI(14), but VWAP evidence is complete."""
    index = _frame([100.0 + i for i in range(20)], [0.0] * 20)
    futures = _frame([200.0 + i for i in range(20)], [1000.0] * 20)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp(f"{TRADING_DATE} 09:26", tz=IST),
        expected_timestamp=pd.Timestamp(f"{TRADING_DATE} 09:25", tz=IST),
    )

    assert snapshot is not None, "the warm-up must not suppress the snapshot"
    assert snapshot.rsi_value is None
    assert snapshot.data_quality == "VALID"
    assert snapshot.vwap_value is not None
    assert snapshot.rsi_state is None, "no reading means no classification"
    assert health.status == "READY"
    assert health.reason == "RSI_WARMING_UP"


def test_five_minute_snapshot_survives_the_rsi_warm_up():
    """The 5-minute reversal path used to stay blind until 10:30 IST."""
    index = _frame([100.0 + i for i in range(60)], [0.0] * 60)
    futures = _frame([200.0 + i for i in range(60)], [1000.0] * 60)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="5M",
        evaluation_time=pd.Timestamp(f"{TRADING_DATE} 09:50", tz=IST),
    )

    assert snapshot is not None
    assert snapshot.rsi_value is None
    assert snapshot.timeframe == "5M"
    assert health.status == "READY"
    assert health.reason == "RSI_WARMING_UP"


def test_full_rsi_history_still_reports_full_alignment():
    """The warm-up branch must not mask a genuine timestamp problem."""
    index = _frame([100.0 + i for i in range(30)], [0.0] * 30)
    futures = _frame([200.0 + i for i in range(30)], [1000.0] * 30)

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|58072",
        timeframe="1M",
        evaluation_time=pd.Timestamp(f"{TRADING_DATE} 09:45", tz=IST),
        expected_timestamp=pd.Timestamp(f"{TRADING_DATE} 09:44", tz=IST),
    )

    assert snapshot is not None
    assert snapshot.rsi_value is not None
    assert health.reason == "FULL_TIMESTAMP_ALIGNMENT"


def test_initial_entry_is_admitted_while_rsi_is_still_warming_up():
    decision = evaluate_initial_direction_futures(_reference(), _snapshot())

    assert decision.direction == "BULLISH"
    assert decision.entry_type == "INITIAL"
    assert decision.rsi_value is None
    assert decision.rsi_aligned is False, "no reading means no alignment claim"
    assert decision.redbar_vwap_aligned is True

    admission = evaluate_candidate_admission(decision, _flat_trade_state())

    assert admission.candidate_allowed is True
    assert admission.admission_code == AdmissionCode.INITIAL_BULLISH_ALIGNMENT
    assert admission.conditions["rsi_aligned"] is False


def test_reversal_is_detected_while_rsi_is_still_warming_up():
    decision = evaluate_reversal_direction_futures(
        _reference(),
        _snapshot(timeframe="5M"),
        previous_direction="BEARISH",
    )

    assert decision.direction == "BULLISH"
    assert decision.entry_type == "REVERSAL"
    assert decision.rsi_value is None
    assert decision.rsi_aligned is False
    assert decision.redbar_vwap_aligned is True


def test_admission_conditions_expose_the_redbar_vwap_gate():
    """The UI advertises this gate first; it must exist as an audit row."""
    admission = evaluate_candidate_admission(
        evaluate_initial_direction_futures(_reference(), _snapshot()),
        _flat_trade_state(),
    )

    assert "redbar_vwap_aligned" in admission.conditions
    assert admission.conditions["redbar_vwap_aligned"] is True


def test_invalid_context_reports_the_redbar_vwap_gate_as_failed():
    """Every gate flag defaults to True, so absence would read as a pass."""
    futures_decision = evaluate_initial_direction_futures(_reference(), None)
    assert futures_decision.redbar_vwap_aligned is False
    assert futures_decision.vwap_aligned is False
    assert futures_decision.midpoint_aligned is False

    admission = evaluate_candidate_admission(futures_decision, _flat_trade_state())
    assert admission.candidate_allowed is False
    assert admission.conditions["redbar_vwap_aligned"] is False

    legacy_decision = evaluate_reversal_direction(
        _reference(), None, previous_direction="BULLISH"
    )
    assert legacy_decision.redbar_vwap_aligned is False
    assert legacy_decision.state is RedBarV2State.NEUTRAL


@pytest.mark.parametrize(
    "evaluate",
    [evaluate_reversal_direction_futures, evaluate_reversal_direction],
)
def test_previous_direction_is_validated_before_the_context_early_return(evaluate):
    """A typo'd direction must not hide until the data happens to be good."""
    with pytest.raises(ValueError):
        evaluate(_reference(), None, previous_direction="SIDEWAYS")


def _warm_up_evidence() -> LegacyV2DecisionEvidence:
    reference = _reference()
    snapshot = _snapshot()
    return build_legacy_v2_decision_evidence(
        underlying_instrument_key="NSE_INDEX|Nifty 50",
        futures_instrument_key="NSE_FO|58072",
        direction_decision=evaluate_initial_direction_futures(reference, snapshot),
        reference=reference,
        index_context=snapshot,
        futures_context=snapshot,
    )


def test_canonical_evidence_builds_without_an_rsi_reading():
    evidence = _warm_up_evidence()

    assert evidence.rsi_value is None
    assert evidence.futures_vwap == 205.0
    assert evidence.index_close == 110.0


def test_canonical_evidence_round_trips_a_null_rsi_through_event_details():
    details = evidence_to_event_details(_warm_up_evidence())
    assert details["rsi_value"] is None

    restored = evidence_from_event_details(details)
    assert restored.rsi_value is None
    assert restored.futures_vwap == 205.0


def test_null_rsi_evidence_yields_no_rsi_block_but_a_valid_decision():
    """`RsiEvidence` promises a finite value, so absence means no block."""
    evidence = _warm_up_evidence()
    decision = RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        evaluation_timestamp=datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc),
        evaluation_timeframe="1m",
        entry_type=EntryType.INITIAL,
        previous_state=DomainState.REFERENCE_READY,
        current_state=DomainState.CONFIRMED_BULLISH,
        direction=Direction.BULLISH,
        option_side=OptionSide.CE,
        trend_strength=TrendStrength.CONFIRMED,
        reference=DomainReference(
            reference_id=evidence.reference_id,
            trading_date=date(2026, 8, 18),
            timestamp=datetime(2026, 8, 18, 9, 25, tzinfo=timezone.utc),
            high=evidence.reference_high,
            low=evidence.reference_low,
            midpoint=evidence.reference_midpoint,
            source=evidence.reference_source,
        ),
        rsi=None,
        futures_vwap=FuturesVwapEvidence(
            instrument_key=evidence.futures_instrument_key,
            comparison_price=evidence.futures_comparison_price,
            vwap=evidence.futures_vwap,
            volume=evidence.futures_volume,
            bullish_aligned=True,
            bearish_aligned=False,
            fresh=True,
        ),
        midpoint=MidpointEvidence(
            index_close=evidence.index_close,
            midpoint=evidence.reference_midpoint,
            bullish_aligned=True,
            bearish_aligned=False,
        ),
        context_status=ContextStatus.FRESH,
        admission_outcome=AdmissionOutcome.ALLOWED,
        admission_code="INITIAL_BULLISH_ALIGNMENT",
        admission_reason="RedBar reference and futures VWAP are aligned.",
    )

    assert decision.rsi is None
    assert decision.admission_outcome is AdmissionOutcome.ALLOWED
