from datetime import datetime
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.red_bar_v2_historical_replay import (
    RedBarV2ReplayResult,
    ReplayEvent,
)
from red_bar_lab.services.red_bar_v2_lifecycle_validation import ReplayEventEpisode
from red_bar_lab.services.red_bar_v2_multiday_validation import (
    RedBarV2ValidationDay,
    classify_session_regime,
    run_red_bar_v2_multiday_validation,
)


IST = "Asia/Kolkata"


def _candles(start: float, end: float, *, periods: int = 375) -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-18 09:15", periods=periods, freq="1min", tz=IST)
    closes = pd.Series(
        [start + (end - start) * index / (periods - 1) for index in range(periods)]
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": [1000.0] * periods,
        }
    )


def test_regime_classifier_separates_up_down_and_range():
    assert classify_session_regime(_candles(100.0, 101.0)) == "TREND_UP"
    assert classify_session_regime(_candles(101.0, 100.0)) == "TREND_DOWN"
    assert classify_session_regime(_candles(100.0, 100.1)) == "RANGE"


def test_manifest_optional_text_treats_blank_and_nan_as_absent():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "run_red_bar_v2_multiday_validation.py"
    spec = importlib.util.spec_from_file_location("red_bar_v2_multiday_cli", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._optional_text(None) is None
    assert module._optional_text(float("nan")) is None
    assert module._optional_text("   ") is None
    assert module._optional_text(" RANGE ") == "RANGE"
    assert module._parse_exit_timestamps(float("nan")) == ()


def _runner(index_candles, futures_candles, **kwargs):
    trading_date = pd.Timestamp(index_candles["timestamp"].iloc[0]).date().isoformat()
    stamp = pd.Timestamp(index_candles["timestamp"].iloc[30]).to_pydatetime()
    bullish = float(index_candles["close"].iloc[-1]) >= float(index_candles["close"].iloc[0])
    first_direction = "BULLISH" if bullish else "BEARISH"
    second_direction = "BEARISH" if bullish else "BULLISH"
    events = (
        ReplayEvent(
            timestamp=stamp,
            event_type="CANDIDATE_ADMISSION",
            direction=first_direction,
            option_side="CE" if bullish else "PE",
            admission_code="INITIAL_ALIGNMENT",
            candidate_allowed=True,
            trade_id="T1",
            details={},
        ),
        ReplayEvent(
            timestamp=stamp + pd.Timedelta(minutes=20),
            event_type="TRADE_CLOSED",
            direction=first_direction,
            option_side="CE" if bullish else "PE",
            admission_code=None,
            candidate_allowed=None,
            trade_id="T1",
            details={"source": "REPLAY_EXIT_FIXTURE"},
        ),
        ReplayEvent(
            timestamp=stamp + pd.Timedelta(minutes=25),
            event_type="CANDIDATE_ADMISSION",
            direction=second_direction,
            option_side="PE" if bullish else "CE",
            admission_code="REVERSAL_ALIGNMENT",
            candidate_allowed=True,
            trade_id="T2",
            details={},
        ),
    )
    replay = RedBarV2ReplayResult(
        instrument_key=kwargs["instrument_key"],
        trading_date=trading_date,
        reference_timestamp=stamp,
        reference_midpoint=100.0,
        events=events,
        admitted_candidates=2,
        blocked_candidates=3,
        closed_trades=1,
        final_trade_state="ACTIVE",
    )
    health = SimpleNamespace(
        status="READY",
        reason="FULL_SESSION_TIMESTAMP_ALIGNMENT",
        index_rows=375,
        futures_rows=385,
        aligned_rows=375,
        alignment_coverage_pct=100.0,
        completed_5m_aligned_rows=75,
        completed_5m_alignment_coverage_pct=100.0,
    )
    episodes = (
        ReplayEventEpisode(
            first_timestamp=stamp + pd.Timedelta(minutes=5),
            last_timestamp=stamp + pd.Timedelta(minutes=7),
            event_type="CANDIDATE_ADMISSION",
            direction=second_direction,
            option_side="PE" if bullish else "CE",
            admission_code="ACTIVE_TRADE_BLOCK",
            candidate_allowed=False,
            occurrences=3,
        ),
    )
    return SimpleNamespace(
        replay=replay,
        health=health,
        health_path=Path(kwargs["artifacts_root"]) / "health.json",
        event_episodes=episodes,
    )


def test_multiday_validation_persists_json_csv_and_reversal_metrics(tmp_path):
    up = _candles(100.0, 101.0)
    down = _candles(101.0, 100.0)
    days = (
        RedBarV2ValidationDay(
            trading_date="2026-08-18",
            index_candles=up,
            futures_candles=up,
            futures_instrument_key="NSE_FO|UP",
            expected_regime="TREND_UP",
        ),
        RedBarV2ValidationDay(
            trading_date="2026-08-19",
            index_candles=down,
            futures_candles=down,
            futures_instrument_key="NSE_FO|DOWN",
            expected_regime="TREND_DOWN",
        ),
    )

    result = run_red_bar_v2_multiday_validation(
        days,
        instrument_key="NSE_INDEX|Nifty 50",
        artifacts_root=tmp_path,
        replay_runner=_runner,
    )

    assert result.total_days == 2
    assert result.ready_days == 2
    assert result.blocked_days == 0
    assert result.total_admitted_candidates == 4
    assert result.total_closed_trades == 2
    assert result.total_admitted_reversals == 2
    assert result.regimes == ("TREND_DOWN", "TREND_UP")
    assert result.json_path.exists()
    assert result.csv_path.exists()
    assert all(day.regime_matches_expectation is True for day in result.days)
    assert all(day.active_trade_block_episodes == 1 for day in result.days)
    assert all(day.active_trade_block_occurrences == 3 for day in result.days)
