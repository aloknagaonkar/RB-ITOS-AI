from datetime import datetime

import pandas as pd

from red_bar_lab.intelligence.market_context import MarketIndicatorSnapshot
from red_bar_lab.services import red_bar_v2_historical_replay as replay
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2Reference,
    RedBarV2State,
)


IST = "Asia/Kolkata"


def _candles(periods: int = 25) -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-21 09:15", periods=periods, freq="1min", tz=IST)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * periods,
            "high": [101.0] * periods,
            "low": [99.0] * periods,
            "close": [100.0] * periods,
            "volume": [1000.0] * periods,
        }
    )


def _reference() -> RedBarV2Reference:
    return RedBarV2Reference(
        instrument_key="NIFTY",
        trading_date="2026-08-21",
        reference_timestamp=pd.Timestamp("2026-08-21 09:20", tz=IST).to_pydatetime(),
        reference_open=102.0,
        reference_high=104.0,
        reference_low=96.0,
        reference_close=98.0,
        midpoint=100.0,
    )


def _snapshot(timeframe: str, timestamp: pd.Timestamp, close: float = 100.0) -> MarketIndicatorSnapshot:
    return MarketIndicatorSnapshot(
        instrument_key="NIFTY",
        trading_date="2026-08-21",
        timeframe=timeframe,
        candle_timestamp=timestamp.to_pydatetime(),
        candle_open=close,
        candle_high=close + 1.0,
        candle_low=close - 1.0,
        candle_close=close,
        candle_volume=1000.0,
        rsi_period=14,
        rsi_value=60.0,
        vwap_value=99.0,
        price_vs_vwap="ABOVE",
        bullish_context=True,
        bearish_context=False,
        source="TEST",
        data_quality="VALID",
        fresh=True,
    )


def _decision(
    *,
    event: RedBarV2EventType,
    state: RedBarV2State,
    direction: str | None,
    side: str | None,
    entry_type: str | None,
    timestamp: str,
    provisional: bool = False,
) -> RedBarV2DirectionDecision:
    stamp = pd.Timestamp(timestamp, tz=IST).to_pydatetime()
    return RedBarV2DirectionDecision(
        event_type=event,
        state=state,
        direction=direction,
        option_side=side,
        entry_type=entry_type,
        trend_strength="PROVISIONAL" if provisional else "CONFIRMED" if direction else None,
        context_timestamp=stamp,
        reference_timestamp=_reference().reference_timestamp,
        close_price=105.0 if direction == "BULLISH" else 95.0 if direction == "BEARISH" else 100.0,
        rsi_value=60.0 if direction == "BULLISH" else 40.0 if direction == "BEARISH" else 50.0,
        vwap_value=102.0 if direction == "BULLISH" else 98.0 if direction == "BEARISH" else 100.0,
        rsi_aligned=direction is not None,
        vwap_aligned=direction is not None,
        midpoint_aligned=not provisional and direction is not None,
        context_fresh=True,
        reason="test",
    )


def _patch_common(monkeypatch):
    monkeypatch.setattr(replay, "build_red_bar_v2_reference", lambda *args, **kwargs: _reference())
    monkeypatch.setattr(
        replay,
        "build_latest_snapshot",
        lambda *args, timeframe, evaluation_time, **kwargs: _snapshot(
            timeframe,
            pd.Timestamp(evaluation_time) - pd.Timedelta(minutes=1 if timeframe == "1M" else 5),
        ),
    )


def test_reversal_before_exit_is_blocked_then_admitted_after_close(monkeypatch):
    _patch_common(monkeypatch)
    initial_calls = {"count": 0}

    def initial(*args, **kwargs):
        initial_calls["count"] += 1
        if initial_calls["count"] > 1:
            return _decision(
                event=RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
                state=RedBarV2State.CONFIRMED_BULLISH,
                direction="BULLISH",
                side="CE",
                entry_type="INITIAL",
                timestamp="2026-08-21 09:30",
            )
        return _decision(
            event=RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BEARISH,
            direction="BEARISH",
            side="PE",
            entry_type="INITIAL",
            timestamp="2026-08-21 09:16",
        )

    monkeypatch.setattr(replay, "evaluate_initial_direction", initial)
    monkeypatch.setattr(
        replay,
        "evaluate_reversal_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
            state=RedBarV2State.PROVISIONAL_BULLISH,
            direction="BULLISH",
            side="CE",
            entry_type="REVERSAL",
            timestamp="2026-08-21 09:30",
            provisional=True,
        ),
    )
    monkeypatch.setattr(
        replay,
        "evaluate_midpoint_upgrade",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
            state=RedBarV2State.PROVISIONAL_BULLISH,
            direction=None,
            side=None,
            entry_type=None,
            timestamp="2026-08-21 09:31",
        ),
    )

    result = replay.replay_red_bar_v2_day(
        _candles(),
        instrument_key="NIFTY",
        exit_timestamps=[pd.Timestamp("2026-08-21 09:31", tz=IST)],
    )

    admissions = [event for event in result.events if event.event_type == "CANDIDATE_ADMISSION"]
    assert admissions[0].candidate_allowed is True
    assert any(event.admission_code == "ACTIVE_TRADE_BLOCK" for event in admissions)
    assert admissions[-1].candidate_allowed is True
    assert admissions[-1].admission_code == "INITIAL_BULLISH_ALIGNMENT"

    for event in admissions:
        assert "admission_reason" in event.details
        assert "conditions" in event.details
        assert "reference_ready" in event.details["conditions"]
        assert "context_fresh" in event.details["conditions"]
        assert "rsi_aligned" in event.details["conditions"]
        assert "vwap_aligned" in event.details["conditions"]
        assert "midpoint_aligned" in event.details["conditions"]

    assert result.admitted_candidates == 2
    assert result.closed_trades == 1


def test_exit_does_not_admit_opposite_candidate_without_fresh_rules(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        replay,
        "evaluate_initial_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BEARISH,
            direction="BEARISH",
            side="PE",
            entry_type="INITIAL",
            timestamp="2026-08-21 09:16",
        ),
    )
    monkeypatch.setattr(
        replay,
        "evaluate_reversal_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
            state=RedBarV2State.CONFIRMED_BULLISH,
            direction="BULLISH",
            side="CE",
            entry_type="REVERSAL",
            timestamp="2026-08-21 09:30",
        ),
    )

    result = replay.replay_red_bar_v2_day(
        _candles(),
        instrument_key="NIFTY",
        exit_timestamps=[pd.Timestamp("2026-08-21 09:29", tz=IST)],
    )

    allowed = [event for event in result.events if event.candidate_allowed]
    assert [event.option_side for event in allowed] == ["PE"]
    assert not any(event.admission_code == "ACTIVE_TRADE_BLOCK" for event in result.events)


def test_provisional_midpoint_upgrade_does_not_create_second_candidate(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        replay,
        "evaluate_initial_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BEARISH,
            direction="BEARISH",
            side="PE",
            entry_type="INITIAL",
            timestamp="2026-08-21 09:16",
        ),
    )
    monkeypatch.setattr(
        replay,
        "evaluate_reversal_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
            state=RedBarV2State.PROVISIONAL_BULLISH,
            direction="BULLISH",
            side="CE",
            entry_type="REVERSAL",
            timestamp="2026-08-21 09:30",
            provisional=True,
        ),
    )
    monkeypatch.setattr(
        replay,
        "evaluate_midpoint_upgrade",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BULLISH,
            direction="BULLISH",
            side="CE",
            entry_type="STATE_UPGRADE",
            timestamp="2026-08-21 09:31",
        ),
    )

    result = replay.replay_red_bar_v2_day(
        _candles(),
        instrument_key="NIFTY",
        exit_timestamps=[pd.Timestamp("2026-08-21 09:29", tz=IST)],
    )

    assert result.admitted_candidates == 1
    upgrades = [event for event in result.events if event.event_type == "STATE_UPGRADE"]
    assert upgrades == []


def test_replay_is_deterministic_and_exports_records(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        replay,
        "evaluate_initial_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BULLISH,
            direction="BULLISH",
            side="CE",
            entry_type="INITIAL",
            timestamp="2026-08-21 09:16",
        ),
    )
    monkeypatch.setattr(
        replay,
        "evaluate_reversal_direction",
        lambda *args, **kwargs: _decision(
            event=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
            state=RedBarV2State.NEUTRAL,
            direction=None,
            side=None,
            entry_type=None,
            timestamp="2026-08-21 09:30",
        ),
    )

    first = replay.replay_red_bar_v2_day(_candles(), instrument_key="NIFTY")
    second = replay.replay_red_bar_v2_day(_candles(), instrument_key="NIFTY")

    assert first.to_records() == second.to_records()
    assert first.reference_timestamp == _reference().reference_timestamp
    assert first.reference_midpoint == 100.0
    assert isinstance(first.to_records()[0]["timestamp"], str)


def test_empty_replay_input_is_rejected():
    try:
        replay.replay_red_bar_v2_day(pd.DataFrame(), instrument_key="NIFTY")
    except ValueError as exc:
        assert "one-minute OHLCV" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty replay input")
