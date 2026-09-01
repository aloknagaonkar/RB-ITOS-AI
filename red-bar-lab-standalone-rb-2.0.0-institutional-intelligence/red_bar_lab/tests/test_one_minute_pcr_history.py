from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.services.market_trend_research.combined_pcr import (
    CombinedMarketPcr,
    CombinedPcrComponent,
)
from red_bar_lab.services.market_trend_research.five_minute_history import (
    OneMinutePcrObservation,
)
from red_bar_lab.services.market_trend_research.one_minute_history import (
    aligned_one_minute_futures_vwap,
    build_one_minute_pcr_observation,
    completed_one_minute_close,
    completed_one_minute_rsi,
)
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)


IST = ZoneInfo("Asia/Kolkata")


def _combined() -> CombinedMarketPcr:
    return CombinedMarketPcr(
        score=42.0,
        direction="BEARISH",
        confidence=16.0,
        coverage=0.70,
        agreement="2 of 3",
        components=(CombinedPcrComponent(
            "NIFTY TOP 10", 0.30, 0.74, 0.0, "NEUTRAL", None, True,
            "10/10 stocks",
        ),),
        reason_code="COMBINED_PCR_READY",
        index_pcr=0.66,
    )


def _projection(source: datetime) -> dict[str, object]:
    return {
        "underlying": "NIFTY 50",
        "source_timestamp": source.isoformat(),
        "quality": {"state": "READY"},
        "current_panel": {
            "spot": 24219.05,
            "aggregate": {
                "pcr": 0.82,
                "total_ce_oi": 1000.0,
                "total_pe_oi": 820.0,
                "direction_evidence": {"direction": "BEARISH"},
            },
            "rows": [{
                "position": "TOTAL",
                "ce_previous_day_change": 100.0,
                "ce_previous_day_change_pct": 11.11,
                "pe_previous_day_change": 50.0,
                "pe_previous_day_change_pct": 6.49,
            }],
        },
        "morning_panel": {"aggregate": {"pcr": 0.91}},
    }


def test_completed_one_minute_boundary_floors_seconds_to_minute() -> None:
    assert completed_one_minute_close(
        datetime(2026, 8, 25, 9, 14, 59, tzinfo=IST)
    ) is None
    assert completed_one_minute_close(
        datetime(2026, 8, 25, 9, 15, 0, tzinfo=IST)
    ) == datetime(2026, 8, 25, 9, 15, tzinfo=IST)
    assert completed_one_minute_close(
        datetime(2026, 8, 25, 9, 15, 59, 999999, tzinfo=IST)
    ) == datetime(2026, 8, 25, 9, 15, tzinfo=IST)
    assert completed_one_minute_close(
        datetime(2026, 8, 25, 9, 16, 17, tzinfo=IST)
    ) == datetime(2026, 8, 25, 9, 16, tzinfo=IST)


def test_completed_one_minute_boundary_returns_none_outside_session() -> None:
    assert completed_one_minute_close(
        datetime(2026, 8, 25, 15, 31, 0, tzinfo=IST)
    ) is None
    assert completed_one_minute_close(
        datetime(2026, 8, 29, 9, 16, 0, tzinfo=IST)
    ) is None


def test_evidence_older_than_candle_close_is_not_attached() -> None:
    observation = build_one_minute_pcr_observation(
        projection=_projection(datetime(2026, 8, 25, 9, 14, 59, tzinfo=IST)),
        combined=_combined(),
        evaluated_at=datetime(2026, 8, 25, 9, 15, 2, tzinfo=IST),
    )
    assert observation is None


def test_builder_returns_one_minute_observation() -> None:
    observation = build_one_minute_pcr_observation(
        projection=_projection(datetime(2026, 8, 25, 9, 15, 1, tzinfo=IST)),
        combined=_combined(),
        evaluated_at=datetime(2026, 8, 25, 9, 15, 2, tzinfo=IST),
        rsi=54.25,
        vwap=24211.75,
    )
    assert isinstance(observation, OneMinutePcrObservation)
    assert observation.candle_close_timestamp == datetime(
        2026, 8, 25, 9, 15, tzinfo=IST
    )
    assert observation.research_direction == "BEARISH"
    assert observation.nifty_spot == 24219.05


def test_repository_keeps_one_immutable_row_per_candle(tmp_path) -> None:
    observation = build_one_minute_pcr_observation(
        projection=_projection(datetime(2026, 8, 25, 9, 15, 1, tzinfo=IST)),
        combined=_combined(),
        evaluated_at=datetime(2026, 8, 25, 9, 15, 2, tzinfo=IST),
        rsi=54.25,
        vwap=24211.75,
    )
    assert observation is not None
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    assert repository.persist_one_minute_pcr_observation(observation) is True
    assert repository.persist_one_minute_pcr_observation(observation) is False
    rows = repository.one_minute_pcr_history(
        underlying="NIFTY 50",
        trading_date=date(2026, 8, 25),
    )
    assert len(rows) == 1
    assert rows[0]["overall_pcr"] == 0.82
    assert rows[0]["combined_index_pcr"] == 0.66
    assert rows[0]["top_ten_pcr"] == 0.74
    assert rows[0]["research_direction"] == "BEARISH"
    assert rows[0]["ce_day_oi_change_pct"] == 11.11
    assert rows[0]["pe_day_oi_change_pct"] == 6.49
    assert rows[0]["nifty_spot"] == 24219.05
    assert rows[0]["rsi"] == 54.25
    assert rows[0]["vwap"] == 24211.75
    assert rows[0]["candle_close_timestamp"].startswith("2026-08-25T09:15:00")
    assert repository.one_minute_pcr_trading_days("NIFTY 50") == ["2026-08-25"]


def test_repository_history_respects_limit_and_trading_day(tmp_path) -> None:
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    base_close = datetime(2026, 8, 25, 9, 15, tzinfo=IST)
    for minute in range(5):
        close = base_close.replace(minute=15 + minute)
        observation = OneMinutePcrObservation(
            underlying="NIFTY 50",
            candle_close_timestamp=close,
            source_timestamp=close.replace(microsecond=500_000),
            overall_pcr=round(0.80 + 0.01 * minute, 2),
            overall_direction="BEARISH",
            total_ce_oi=1000.0,
            total_pe_oi=820.0 + 5 * minute,
            ce_day_oi_change=100.0,
            pe_day_oi_change=50.0,
            morning_pcr=0.91,
            combined_score=42.0,
            combined_direction="BEARISH",
            combined_coverage=0.7,
            quality_state="READY",
        )
        assert repository.persist_one_minute_pcr_observation(observation) is True

    rows = repository.one_minute_pcr_history(
        underlying="NIFTY 50",
        trading_date=date(2026, 8, 25),
        limit=2,
    )
    assert [row["overall_pcr"] for row in rows] == [0.84, 0.83]


def test_rsi_uses_only_candles_completed_by_boundary() -> None:
    timestamps = pd.date_range("2026-08-25 09:15", periods=17, freq="1min", tz=IST)
    candles = pd.DataFrame({
        "timestamp": timestamps,
        "close": [100.0 + value for value in range(17)],
    })

    value = completed_one_minute_rsi(
        candles,
        candle_close=datetime(2026, 8, 25, 9, 30, tzinfo=IST),
    )

    assert value == 100.0


def test_rsi_returns_none_until_enough_candles_are_complete() -> None:
    timestamps = pd.date_range("2026-08-25 09:15", periods=10, freq="1min", tz=IST)
    candles = pd.DataFrame({
        "timestamp": timestamps,
        "close": [100.0 + value for value in range(10)],
    })

    assert completed_one_minute_rsi(
        candles,
        candle_close=datetime(2026, 8, 25, 9, 22, tzinfo=IST),
    ) is None


def test_one_minute_futures_vwap_must_be_aligned_to_boundary() -> None:
    close = datetime(2026, 8, 25, 9, 30, tzinfo=IST)
    rows = [{
        "futures_vwap": 24210.5,
        "futures_vwap_timestamp": close.isoformat(),
    }]

    assert aligned_one_minute_futures_vwap(rows, candle_close=close) == 24210.5


def test_one_minute_futures_vwap_rejects_evidence_beyond_one_minute() -> None:
    close = datetime(2026, 8, 25, 9, 30, tzinfo=IST)
    rows = [{
        "futures_vwap": 24210.5,
        "futures_vwap_timestamp": (close.replace(second=0) ).isoformat(),
    }]

    # Move evidence 90s before the close; 1m window only accepts <=60s.
    rows[0]["futures_vwap_timestamp"] = (
        close - pd.Timedelta(seconds=90)
    ).isoformat()

    assert aligned_one_minute_futures_vwap(rows, candle_close=close) is None
