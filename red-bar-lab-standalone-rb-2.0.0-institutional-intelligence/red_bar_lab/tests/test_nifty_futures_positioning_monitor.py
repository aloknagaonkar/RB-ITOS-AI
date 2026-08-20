from red_bar_lab.services.nifty_futures_market_data import NiftyFuturesMarketData
from red_bar_lab.services.nifty_futures_positioning_monitor import (
    assess_futures_positioning,
    futures_positioning_log_values,
)


def test_assesses_positioning_from_completed_market_candles():
    market = NiftyFuturesMarketData(
        status="READY",
        reason="ready",
        completed_candles=(
            ["2026-08-20T10:28:00+05:30", 1, 2, 1, 100, 100, 1000],
            ["2026-08-20T10:29:00+05:30", 1, 2, 1, 101, 120, 1010],
            ["2026-08-20T10:30:00+05:30", 1, 2, 1, 102, 180, 1030],
        ),
    )

    result = assess_futures_positioning(market)

    assert result.status == "READY"
    assert result.state == "LONG_BUILDUP"
    assert result.price_change == 1.0
    assert result.oi_change == 20.0
    assert result.relative_volume == 180 / 110
    assert result.baseline_samples == 2


def test_uses_only_configured_volume_baseline_window():
    market = NiftyFuturesMarketData(
        status="READY",
        reason="ready",
        completed_candles=(
            ["2026-08-20T10:27:00+05:30", 1, 2, 1, 99, 10, 990],
            ["2026-08-20T10:28:00+05:30", 1, 2, 1, 100, 100, 1000],
            ["2026-08-20T10:29:00+05:30", 1, 2, 1, 101, 200, 1010],
            ["2026-08-20T10:30:00+05:30", 1, 2, 1, 102, 300, 1030],
        ),
    )

    result = assess_futures_positioning(market, baseline_window=2)

    assert result.baseline_volume == 150.0
    assert result.baseline_samples == 2
    assert result.relative_volume == 2.0


def test_unavailable_market_data_is_insufficient_and_non_throwing():
    result = assess_futures_positioning(
        NiftyFuturesMarketData(status="ERROR", reason="provider failed")
    )

    assert result.status == "INSUFFICIENT_DATA"
    assert result.state == "NEUTRAL"


def test_positioning_log_values_are_stable():
    market = NiftyFuturesMarketData(
        status="READY",
        reason="ready",
        completed_candles=(
            ["2026-08-20T10:29:00+05:30", 1, 2, 1, 100, 100, 1000],
            ["2026-08-20T10:30:00+05:30", 1, 2, 1, 101, 200, 1020],
        ),
    )

    values = futures_positioning_log_values(assess_futures_positioning(market))

    assert values == (
        "READY",
        "Completed-candle futures price, OI and relative volume were assessed.",
        "LONG_BUILDUP",
        "1.00",
        "1.0000",
        "20.0",
        "2.0000",
        "2.0000",
        "100.0",
        "1",
    )
