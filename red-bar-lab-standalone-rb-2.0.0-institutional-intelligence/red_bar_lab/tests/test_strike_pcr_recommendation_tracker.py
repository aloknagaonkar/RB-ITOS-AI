from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)
from red_bar_lab.services.market_trend_research.strike_pcr_tracker import (
    build_strike_pcr_recommendations,
)


IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 8, 25, 10, 0, tzinfo=IST)


def _projection(*, pe_oi: float, source: datetime) -> dict[str, object]:
    return {
        "underlying": "NIFTY 50",
        "source_timestamp": source.isoformat(),
        "current_panel": {
            "expiry": "2026-08-25",
            "aggregate": {"pcr": 0.90},
            "rows": [{
                "strike": 24200.0,
                "position": "ATM",
                "ce_current_oi": 100.0,
                "pe_current_oi": pe_oi,
            }],
        },
    }


def _quotes(*, bid: float, ask: float) -> list[dict[str, object]]:
    return [{
        "strike": 24200.0,
        "option_type": "PE",
        "expiry": "2026-08-25",
        "tradingsymbol": "NIFTY 24200 PE",
        "bid": bid,
        "ask": ask,
        "current_price": (bid + ask) / 2.0,
    }]


def test_builder_maps_each_strike_pcr_without_overall_gate() -> None:
    observations = build_strike_pcr_recommendations(
        projection=_projection(pe_oi=60.0, source=START),
        option_rows=_quotes(bid=99.0, ask=100.0),
    )
    assert len(observations) == 1
    item = observations[0]
    assert item.strike_pcr == 0.6
    assert item.strike_signal == "BEARISH"
    assert item.overall_pcr == 0.9
    assert item.overall_signal == "NEUTRAL"
    assert item.recommendation == "BUY_PE"


def test_entry_ask_is_frozen_and_peak_tracks_highest_bid(tmp_path) -> None:
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    first = build_strike_pcr_recommendations(
        projection=_projection(pe_oi=60.0, source=START),
        option_rows=_quotes(bid=99.0, ask=100.0),
    )
    repository.apply_strike_pcr_recommendations(first)
    second = build_strike_pcr_recommendations(
        projection=_projection(pe_oi=65.0, source=START + timedelta(seconds=5)),
        option_rows=_quotes(bid=112.0, ask=113.0),
    )
    repository.apply_strike_pcr_recommendations(second)
    lower = build_strike_pcr_recommendations(
        projection=_projection(pe_oi=65.0, source=START + timedelta(seconds=10)),
        option_rows=_quotes(bid=106.0, ask=107.0),
    )
    repository.apply_strike_pcr_recommendations(lower)
    rows = repository.strike_pcr_recommendations(
        underlying="NIFTY 50",
        trading_date=date(2026, 8, 25),
    )
    assert len(rows) == 1
    assert rows[0]["entry_price"] == 100.0
    assert rows[0]["current_price"] == 106.0
    assert rows[0]["peak_price"] == 112.0
    assert rows[0]["status"] == "ACTIVE"


def test_neutral_strike_closes_active_episode(tmp_path) -> None:
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    repository.apply_strike_pcr_recommendations(build_strike_pcr_recommendations(
        projection=_projection(pe_oi=60.0, source=START),
        option_rows=_quotes(bid=99.0, ask=100.0),
    ))
    repository.apply_strike_pcr_recommendations(build_strike_pcr_recommendations(
        projection=_projection(pe_oi=90.0, source=START + timedelta(seconds=5)),
        option_rows=_quotes(bid=101.0, ask=102.0),
    ))
    rows = repository.strike_pcr_recommendations(
        underlying="NIFTY 50",
        trading_date=date(2026, 8, 25),
    )
    assert rows[0]["status"] == "CLOSED"
    assert rows[0]["entry_price"] == 100.0
