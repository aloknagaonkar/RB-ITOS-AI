from datetime import datetime, timedelta

from red_bar_lab.execution.option_quote_readiness import (
    QUOTE_CROSSED_MARKET,
    QUOTE_INVALID_TIMESTAMP,
    QUOTE_MISSING_BID_ASK,
    QUOTE_MISSING_TIMESTAMP,
    QUOTE_READY,
    QUOTE_STALE,
    QUOTE_WIDE_SPREAD,
    QUOTE_ZERO_LTP,
    assess_option_quote_readiness,
)


OBSERVED = datetime.fromisoformat("2026-08-20T14:30:00+05:30")


def _quote(**overrides):
    quote = {
        "last_price": 100.0,
        "exchange_timestamp": OBSERVED.isoformat(),
        "depth": {
            "buy": [{"price": 99.5}],
            "sell": [{"price": 100.5}],
        },
    }
    quote.update(overrides)
    return quote


def test_ready_quote_reports_age_and_spread():
    result = assess_option_quote_readiness(_quote(), observed_at=OBSERVED)

    assert result.status == QUOTE_READY
    assert result.ready is True
    assert result.quote_age_seconds == 0.0
    assert result.last_price == 100.0
    assert result.best_bid == 99.5
    assert result.best_ask == 100.5
    assert round(result.spread_pct, 3) == 1.0


def test_missing_timestamp_is_explicit():
    quote = _quote()
    quote.pop("exchange_timestamp")

    result = assess_option_quote_readiness(quote, observed_at=OBSERVED)

    assert result.status == QUOTE_MISSING_TIMESTAMP
    assert result.quote_timestamp is None
    assert result.quote_age_seconds is None


def test_invalid_timestamp_is_explicit():
    result = assess_option_quote_readiness(
        _quote(exchange_timestamp="not-a-timestamp"),
        observed_at=OBSERVED,
    )

    assert result.status == QUOTE_INVALID_TIMESTAMP


def test_future_timestamp_beyond_tolerance_is_invalid():
    result = assess_option_quote_readiness(
        _quote(exchange_timestamp=(OBSERVED + timedelta(seconds=6)).isoformat()),
        observed_at=OBSERVED,
    )

    assert result.status == QUOTE_INVALID_TIMESTAMP
    assert result.quote_age_seconds == -6.0


def test_stale_quote_precedes_price_quality_checks():
    result = assess_option_quote_readiness(
        _quote(
            exchange_timestamp=(OBSERVED - timedelta(seconds=61)).isoformat(),
            last_price=0,
        ),
        observed_at=OBSERVED,
        stale_after_seconds=60,
    )

    assert result.status == QUOTE_STALE
    assert result.quote_age_seconds == 61.0


def test_zero_ltp_is_rejected():
    result = assess_option_quote_readiness(
        _quote(last_price=0),
        observed_at=OBSERVED,
    )

    assert result.status == QUOTE_ZERO_LTP


def test_missing_bid_or_ask_is_rejected():
    result = assess_option_quote_readiness(
        _quote(depth={"buy": [{"price": 99.5}], "sell": []}),
        observed_at=OBSERVED,
    )

    assert result.status == QUOTE_MISSING_BID_ASK


def test_crossed_market_is_rejected():
    result = assess_option_quote_readiness(
        _quote(
            depth={
                "buy": [{"price": 101.0}],
                "sell": [{"price": 100.0}],
            }
        ),
        observed_at=OBSERVED,
    )

    assert result.status == QUOTE_CROSSED_MARKET


def test_wide_spread_is_rejected():
    result = assess_option_quote_readiness(
        _quote(
            depth={
                "buy": [{"price": 98.0}],
                "sell": [{"price": 102.0}],
            }
        ),
        observed_at=OBSERVED,
        max_spread_pct=2.0,
    )

    assert result.status == QUOTE_WIDE_SPREAD
    assert result.spread_pct == 4.0


def test_epoch_milliseconds_timestamp_is_supported():
    epoch_ms = int(OBSERVED.timestamp() * 1000)

    result = assess_option_quote_readiness(
        _quote(exchange_timestamp=epoch_ms),
        observed_at=OBSERVED,
    )

    assert result.status == QUOTE_READY
    assert result.quote_age_seconds == 0.0
