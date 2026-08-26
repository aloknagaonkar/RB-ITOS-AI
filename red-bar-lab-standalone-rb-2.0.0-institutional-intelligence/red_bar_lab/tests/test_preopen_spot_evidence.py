from datetime import datetime, timezone

import pytest

from red_bar_lab.services.market_trend_research.preopen_spot import (
    NsePreOpenSpotProvider,
    PreOpenSpotObservation,
    resolve_preopen_spot,
)
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)


NOW = datetime(2026, 8, 26, 3, 38, tzinfo=timezone.utc)


def _observation(provider: str, spot: float) -> PreOpenSpotObservation:
    return PreOpenSpotObservation(
        underlying="NIFTY 50",
        trading_date=NOW.date(),
        provider=provider,
        spot=spot,
        source_timestamp=NOW,
        captured_at=NOW,
    )


def test_resolver_prefers_nse_and_reports_alignment():
    result = resolve_preopen_spot(
        (_observation("UPSTOX", 24219.05), _observation("NSE", 24220.10)),
        evaluated_at=NOW,
        maximum_age_seconds=30.0,
    )

    assert result.selected is not None
    assert result.selected.provider == "NSE"
    assert result.state == "ALIGNED"
    assert result.difference_points == pytest.approx(1.05)


def test_resolver_uses_upstox_fallback():
    result = resolve_preopen_spot(
        (_observation("UPSTOX", 24219.05),),
        evaluated_at=NOW,
        maximum_age_seconds=30.0,
    )

    assert result.selected is not None
    assert result.selected.provider == "UPSTOX"
    assert result.state == "UPSTOX_FALLBACK"


def test_repository_keeps_latest_observation_per_provider(tmp_path):
    repository = MarketTrendResearchRepository(tmp_path / "research.sqlite3")
    repository.persist_preopen_spot(_observation("NSE", 24220.10))
    repository.persist_preopen_spot(_observation("UPSTOX", 24219.05))

    rows = repository.latest_preopen_spots(
        underlying="NIFTY 50",
        trading_date=NOW.date(),
    )

    assert [(row.provider, row.spot) for row in rows] == [
        ("NSE", 24220.10),
        ("UPSTOX", 24219.05),
    ]


def test_nse_payload_accepts_documented_nifty_data_shape():
    assert NsePreOpenSpotProvider._spot(
        {"nifty_data": {"lastPrice": "24,220.10"}}
    ) == 24220.10
