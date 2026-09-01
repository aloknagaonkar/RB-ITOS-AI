from datetime import datetime, timezone

import pandas as pd

from red_bar_lab.intelligence.red_bar_v2_futures_context import RedBarV2VwapSourceHealth
from red_bar_lab.services import red_bar_v2_futures_replay_service as service
from red_bar_lab.services.red_bar_v2_historical_replay import ReplayEvent, RedBarV2ReplayResult


IST = "Asia/Kolkata"


class _StubDatabase:
    """Minimal stand-in for RedBarDatabase used by the monitored replay
    service. The service's PCR reader only touches ``.path``; setting
    ``path`` to ``None`` short-circuits the read and returns (None, None)."""

    path = None


def _candles(periods: int) -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-18 09:15", periods=periods, freq="1min", tz=IST)
    return pd.DataFrame(
        {
            "open": [100.0] * periods,
            "high": [101.0] * periods,
            "low": [99.0] * periods,
            "close": [100.0] * periods,
            "volume": [1000.0] * periods,
        },
        index=pd.Index(timestamps, name="timestamp"),
    )


def test_monitored_replay_persists_full_session_and_summarizes_blocks(monkeypatch, tmp_path):
    stamp = datetime(2026, 8, 18, 9, 45, tzinfo=timezone.utc)
    events = tuple(
        ReplayEvent(
            timestamp=stamp + pd.Timedelta(minutes=offset),
            event_type="CANDIDATE_ADMISSION",
            direction="BEARISH",
            option_side="PE",
            admission_code="ACTIVE_TRADE_BLOCK",
            candidate_allowed=False,
            trade_id=None,
            details={},
        )
        for offset in range(3)
    )
    replay = RedBarV2ReplayResult(
        instrument_key="NIFTY",
        trading_date="2026-08-18",
        reference_timestamp=None,
        reference_midpoint=None,
        events=events,
        admitted_candidates=1,
        blocked_candidates=3,
        closed_trades=0,
        final_trade_state="ACTIVE",
    )
    evaluation_health = RedBarV2VwapSourceHealth(
        status="READY",
        reason="FULL_TIMESTAMP_ALIGNMENT",
        price_source_instrument="NIFTY",
        rsi_source_instrument="NIFTY",
        vwap_source_instrument="NIFTY-FUT",
        timeframe="5M",
        index_rows=72,
        futures_rows=72,
        aligned_rows=72,
        alignment_coverage_pct=100.0,
        positive_volume_rows=72,
        index_timestamp=stamp,
        futures_timestamp=stamp,
        last_aligned_timestamp=stamp,
    )
    monkeypatch.setattr(
        service,
        "replay_red_bar_v2_day_with_futures_vwap",
        lambda *args, **kwargs: (replay, evaluation_health),
    )

    result = service.run_monitored_red_bar_v2_futures_replay(
        _candles(375),
        _candles(385),
        database=_StubDatabase(),
        instrument_key="NIFTY",
        vwap_instrument_key="NIFTY-FUT",
        artifacts_root=tmp_path,
    )

    assert result.health.index_rows == 375
    assert result.health.futures_rows == 385
    assert result.health.completed_5m_aligned_rows == 75
    assert result.health_path.exists()
    assert len(result.event_episodes) == 1
    assert result.event_episodes[0].occurrences == 3
