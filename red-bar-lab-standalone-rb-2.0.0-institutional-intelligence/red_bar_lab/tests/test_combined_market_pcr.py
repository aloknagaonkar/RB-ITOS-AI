from datetime import datetime, timedelta, timezone

import pytest

from red_bar_lab.services.market_trend_research.combined_pcr import (
    CombinedMarketPcrCalculator,
    TOP_TEN_WEIGHTS,
)


NOW = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)


def _snapshot(pcr: float, *, age_seconds: float = 0) -> dict[str, object]:
    return {
        "source_timestamp": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "current_panel": {"aggregate": {"pcr": pcr}},
    }


def test_combined_pcr_withholds_direction_when_coverage_is_insufficient() -> None:
    result = CombinedMarketPcrCalculator().calculate(
        {"NIFTY 50": _snapshot(0.6)},
        now=NOW,
    )

    assert result.direction == "UNAVAILABLE"
    assert result.score is None
    assert result.coverage == 0.50
    assert result.reason_code == "COMBINED_PCR_COVERAGE_INSUFFICIENT"


def test_combined_pcr_requires_fresh_nifty_even_with_other_coverage() -> None:
    snapshots = {
        "NIFTY 50": _snapshot(1.6, age_seconds=31),
        "NIFTY BANK": _snapshot(1.6),
        "SENSEX": _snapshot(1.6),
        **{symbol: _snapshot(1.6) for symbol in TOP_TEN_WEIGHTS},
    }

    result = CombinedMarketPcrCalculator().calculate(snapshots, now=NOW)

    assert result.direction == "UNAVAILABLE"
    assert result.score is None


def test_combined_pcr_calculates_weighted_bullish_evidence() -> None:
    snapshots = {
        "NIFTY 50": _snapshot(1.6),
        "NIFTY BANK": _snapshot(1.3),
        "SENSEX": _snapshot(0.9),
        **{symbol: _snapshot(1.6) for symbol in TOP_TEN_WEIGHTS},
    }

    result = CombinedMarketPcrCalculator().calculate(snapshots, now=NOW)

    assert result.direction == "BULLISH"
    assert result.score is not None
    assert result.score > 75
    assert result.coverage == 1.0
    assert result.agreement == "2 of 3 index components agree"
    assert result.index_pcr == pytest.approx(1.3642857143)
    top_ten = next(
        component
        for component in result.components
        if component.name == "NIFTY TOP 10"
    )
    assert top_ten.pcr == pytest.approx(1.6)


def test_top_ten_component_requires_seventy_percent_weight_coverage() -> None:
    symbols = tuple(TOP_TEN_WEIGHTS)
    snapshots = {
        "NIFTY 50": _snapshot(1.0),
        "NIFTY BANK": _snapshot(1.0),
        "SENSEX": _snapshot(1.0),
        **{symbol: _snapshot(1.6) for symbol in symbols[-3:]},
    }

    result = CombinedMarketPcrCalculator().calculate(snapshots, now=NOW)
    top_ten = next(component for component in result.components if component.name == "NIFTY TOP 10")

    assert top_ten.direction == "UNAVAILABLE"
    assert top_ten.pcr is None
    assert top_ten.fresh is False
    assert top_ten.detail.startswith("3/10 stocks")


def test_same_day_closing_indices_produce_combined_result_after_close() -> None:
    close = datetime(2026, 8, 25, 9, 59, 59, tzinfo=timezone.utc)
    after_close = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    snapshots = {
        name: {
            "source_timestamp": close.isoformat(),
            "current_panel": {"aggregate": {"pcr": pcr}},
        }
        for name, pcr in (
            ("NIFTY 50", 0.705),
            ("NIFTY BANK", 0.707),
            ("SENSEX", 0.978),
        )
    }

    result = CombinedMarketPcrCalculator(
        accept_same_day_close=True,
    ).calculate(snapshots, now=after_close)

    assert result.score == 50.0
    assert result.direction == "NEUTRAL"
    assert result.coverage == 1.0
    assert result.index_pcr == pytest.approx(0.7640714286)


def test_previous_day_close_is_not_accepted_as_current() -> None:
    prior_close = datetime(2026, 8, 24, 9, 59, 59, tzinfo=timezone.utc)
    after_close = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    snapshot = {
        "source_timestamp": prior_close.isoformat(),
        "current_panel": {"aggregate": {"pcr": 0.6}},
    }

    result = CombinedMarketPcrCalculator(
        accept_same_day_close=True,
    ).calculate({"NIFTY 50": snapshot}, now=after_close)

    assert result.score is None
    assert result.direction == "UNAVAILABLE"
