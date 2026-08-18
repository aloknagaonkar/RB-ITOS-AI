from __future__ import annotations

from dataclasses import replace

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    build_candidate_identity,
    build_reversal_event_id,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import (
    TradeLifecycleState,
    observe_trade_state,
)
from red_bar_lab.intelligence.market_context import MarketIndicatorSnapshot
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2EventType,
    RedBarV2Reference,
    RedBarV2State,
    evaluate_initial_direction,
    evaluate_midpoint_upgrade,
    evaluate_reversal_direction,
)


IST = "Asia/Kolkata"


def _reference(midpoint: float = 100.0) -> RedBarV2Reference:
    return RedBarV2Reference(
        instrument_key="NIFTY",
        trading_date="2026-08-21",
        reference_timestamp=pd.Timestamp(
            "2026-08-21 09:25", tz=IST
        ).to_pydatetime(),
        reference_open=104.0,
        reference_high=106.0,
        reference_low=94.0,
        reference_close=96.0,
        midpoint=midpoint,
    )


def _context(
    *,
    timeframe: str,
    timestamp: str,
    close: float,
    rsi: float,
    vwap: float,
    quality: str = "VALID",
    fresh: bool = True,
) -> MarketIndicatorSnapshot:
    stamp = pd.Timestamp(timestamp, tz=IST).to_pydatetime()
    return MarketIndicatorSnapshot(
        instrument_key="NIFTY",
        trading_date="2026-08-21",
        timeframe=timeframe,
        candle_timestamp=stamp,
        candle_open=close - 0.5,
        candle_high=close + 0.5,
        candle_low=close - 1.0,
        candle_close=close,
        candle_volume=1000.0,
        rsi_period=14,
        rsi_value=rsi,
        vwap_value=vwap,
        price_vs_vwap=(
            "ABOVE" if close > vwap else "BELOW" if close < vwap else "AT"
        ),
        bullish_context=quality == "VALID" and fresh and rsi > 55 and close > vwap,
        bearish_context=quality == "VALID" and fresh and rsi < 45 and close < vwap,
        source="PHASE_6_TEST",
        data_quality=quality,
        fresh=fresh,
    )


def _flat_state():
    return observe_trade_state([])


def _active_pe_state():
    return observe_trade_state(
        [
            {
                "trade_id": "PE-1",
                "signal_id": "SIG-PE-1",
                "instrument_key": "NIFTY",
                "option_side": "PE",
                "status": "ACTIVE",
                "entry_timestamp": "2026-08-21T10:00:00+05:30",
            }
        ]
    )


def _closed_pe_state():
    return observe_trade_state(
        [
            {
                "trade_id": "PE-1",
                "signal_id": "SIG-PE-1",
                "instrument_key": "NIFTY",
                "option_side": "PE",
                "status": "CLOSED",
                "entry_timestamp": "2026-08-21T10:00:00+05:30",
                "exit_timestamp": "2026-08-21T10:25:00+05:30",
                "updated_at": "2026-08-21T10:25:00+05:30",
            }
        ]
    )


def test_initial_bearish_alignment_is_admitted_when_flat():
    direction = evaluate_initial_direction(
        _reference(),
        _context(
            timeframe="1M",
            timestamp="2026-08-21 10:00",
            close=95.0,
            rsi=38.0,
            vwap=97.0,
        ),
    )

    admission = evaluate_candidate_admission(direction, _flat_state())

    assert admission.candidate_allowed is True
    assert admission.admission_code == AdmissionCode.INITIAL_BEARISH_ALIGNMENT
    assert admission.option_side == "PE"
    assert admission.trend_strength == "CONFIRMED"


def test_initial_bullish_alignment_is_admitted_when_previous_trade_closed():
    direction = evaluate_initial_direction(
        _reference(),
        _context(
            timeframe="1M",
            timestamp="2026-08-21 10:30",
            close=105.0,
            rsi=62.0,
            vwap=102.0,
        ),
    )

    admission = evaluate_candidate_admission(direction, _closed_pe_state())

    assert admission.candidate_allowed is True
    assert admission.admission_code == AdmissionCode.INITIAL_BULLISH_ALIGNMENT
    assert admission.previous_trade_status == TradeLifecycleState.CLOSED.value


def test_reversal_before_exit_is_detected_but_blocked_by_active_trade():
    reversal = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(
            timeframe="5M",
            timestamp="2026-08-21 10:20",
            close=105.0,
            rsi=61.0,
            vwap=102.0,
        ),
        previous_direction="BEARISH",
    )

    admission = evaluate_candidate_admission(reversal, _active_pe_state())

    assert reversal.event_type == RedBarV2EventType.BULLISH_REVERSAL_DETECTED
    assert reversal.state == RedBarV2State.PROVISIONAL_BULLISH
    assert admission.candidate_allowed is False
    assert admission.admission_code == AdmissionCode.ACTIVE_TRADE_BLOCK
    assert admission.reversal_event_id is not None


def test_same_reversal_is_admitted_after_old_trade_closes():
    reversal = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(
            timeframe="5M",
            timestamp="2026-08-21 10:20",
            close=105.0,
            rsi=61.0,
            vwap=102.0,
        ),
        previous_direction="BEARISH",
    )

    blocked = evaluate_candidate_admission(reversal, _active_pe_state())
    allowed = evaluate_candidate_admission(reversal, _closed_pe_state())

    assert blocked.decision_id == allowed.decision_id
    assert blocked.reversal_event_id == allowed.reversal_event_id
    assert allowed.candidate_allowed is True
    assert allowed.admission_code == AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT
    assert allowed.option_side == "CE"
    assert allowed.trend_strength == "PROVISIONAL"


def test_exit_before_reversal_allows_reversal_immediately():
    reversal = evaluate_reversal_direction(
        _reference(midpoint=100.0),
        _context(
            timeframe="5M",
            timestamp="2026-08-21 10:30",
            close=105.0,
            rsi=63.0,
            vwap=102.0,
        ),
        previous_direction="BEARISH",
    )

    admission = evaluate_candidate_admission(reversal, _closed_pe_state())

    assert reversal.state == RedBarV2State.CONFIRMED_BULLISH
    assert admission.candidate_allowed is True
    assert admission.admission_code == AdmissionCode.REVERSAL_CONTEXT_ALIGNED_FLAT
    assert admission.trend_strength == "CONFIRMED"


def test_pending_exit_blocks_reversal_until_terminal_close():
    pending_state = observe_trade_state(
        [
            {
                "trade_id": "PE-1",
                "instrument_key": "NIFTY",
                "option_side": "PE",
                "status": "EXIT_PENDING",
                "entry_timestamp": "2026-08-21T10:00:00+05:30",
            }
        ]
    )
    reversal = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(
            timeframe="5M",
            timestamp="2026-08-21 10:20",
            close=105.0,
            rsi=61.0,
            vwap=102.0,
        ),
        previous_direction="BEARISH",
    )

    admission = evaluate_candidate_admission(reversal, pending_state)

    assert pending_state.lifecycle_state == TradeLifecycleState.PENDING
    assert admission.candidate_allowed is False
    assert admission.admission_code == AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED


def test_midpoint_upgrade_never_creates_second_candidate():
    upgrade = evaluate_midpoint_upgrade(
        _reference(midpoint=100.0),
        _context(
            timeframe="1M",
            timestamp="2026-08-21 10:26",
            close=102.0,
            rsi=59.0,
            vwap=101.0,
        ),
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
    )

    admission = evaluate_candidate_admission(upgrade, _flat_state())

    assert upgrade.event_type == RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT
    assert upgrade.entry_type == "STATE_UPGRADE"
    assert upgrade.state == RedBarV2State.CONFIRMED_BULLISH
    assert admission.candidate_allowed is False
    assert admission.admission_code == AdmissionCode.DUPLICATE_SIGNAL


def test_duplicate_signal_has_priority_over_active_trade_block():
    direction = evaluate_initial_direction(
        _reference(),
        _context(
            timeframe="1M",
            timestamp="2026-08-21 10:00",
            close=95.0,
            rsi=38.0,
            vwap=97.0,
        ),
    )

    admission = evaluate_candidate_admission(
        direction,
        _active_pe_state(),
        duplicate_signal=True,
    )

    assert admission.candidate_allowed is False
    assert admission.admission_code == AdmissionCode.DUPLICATE_SIGNAL


def test_consumed_reversal_has_priority_over_execution_state():
    reversal = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(
            timeframe="5M",
            timestamp="2026-08-21 10:20",
            close=105.0,
            rsi=61.0,
            vwap=102.0,
        ),
        previous_direction="BEARISH",
    )

    admission = evaluate_candidate_admission(
        reversal,
        _active_pe_state(),
        reversal_already_consumed=True,
    )

    assert admission.candidate_allowed is False
    assert admission.admission_code == AdmissionCode.REVERSAL_ALREADY_CONSUMED


def test_candidate_and_reversal_identities_are_deterministic():
    reversal = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(
            timeframe="5M",
            timestamp="2026-08-21 10:20",
            close=105.0,
            rsi=61.0,
            vwap=102.0,
        ),
        previous_direction="BEARISH",
    )

    assert build_candidate_identity(reversal) == build_candidate_identity(reversal)
    assert build_reversal_event_id(reversal) == build_reversal_event_id(reversal)

    later = replace(
        reversal,
        context_timestamp=pd.Timestamp(
            "2026-08-21 10:25", tz=IST
        ).to_pydatetime(),
    )
    assert build_candidate_identity(reversal) != build_candidate_identity(later)
    assert build_reversal_event_id(reversal) != build_reversal_event_id(later)


def test_stale_context_blocks_before_alignment_checks():
    stale = evaluate_initial_direction(
        _reference(),
        _context(
            timeframe="1M",
            timestamp="2026-08-21 10:00",
            close=105.0,
            rsi=62.0,
            vwap=102.0,
            quality="STALE_CONTEXT",
            fresh=False,
        ),
    )

    admission = evaluate_candidate_admission(stale, _flat_state())

    assert admission.candidate_allowed is False
    assert admission.admission_code == AdmissionCode.CONTEXT_STALE
