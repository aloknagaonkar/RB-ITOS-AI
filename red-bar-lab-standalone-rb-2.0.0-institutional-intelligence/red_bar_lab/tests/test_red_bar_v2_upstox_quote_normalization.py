from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataDiagnosticError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    MarketDataReadinessStage,
)
from red_bar_lab.services.red_bar_v2_canonical.upstox_paper_market_data import (
    UpstoxPaperCanaryMarketData,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
KEY = "NSE_FO|51834"


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return _Response(self.payload)


class _Client:
    BASE_URL_V2 = "https://example.invalid/v2"
    timeout = 1

    def __init__(self, payload):
        self.session = _Session(payload)

    def _headers(self):
        return {"Authorization": "Bearer hidden"}

    def _raise_for_api_error(self, response):
        return None


def _provider(payload, *, maximum_age_seconds: float = 120.0):
    provider = UpstoxPaperCanaryMarketData(
        _Client(payload),
        underlying_keys={"NIFTY 50": "NSE_INDEX|Nifty 50"},
        maximum_quote_age_seconds=maximum_age_seconds,
    )
    provider._expected_tokens[KEY] = KEY
    return provider


def _row(**overrides):
    row = {
        "instrument_token": KEY,
        "last_price": 100.0,
        "bid_price": 99.0,
        "ask_price": 101.0,
        "timestamp": NOW.isoformat(),
    }
    row.update(overrides)
    return row


def _quotes(provider):
    return provider.quotes(instrument_keys=(KEY,), evaluated_at=NOW)


def _assert_diagnostic(error, reason, stage):
    assert error.diagnostic.reason_code == reason
    assert error.stage is stage
    assert error.diagnostic.source_component == "upstox_full_quotes"


def test_quote_timestamp_accepts_integer_epoch_milliseconds():
    value = int(NOW.timestamp() * 1000)
    assert UpstoxPaperCanaryMarketData._quote_timestamp(value) == NOW


def test_quote_timestamp_accepts_digit_string_epoch_milliseconds():
    value = str(int(NOW.timestamp() * 1000))
    assert UpstoxPaperCanaryMarketData._quote_timestamp(value) == NOW


def test_quote_timestamp_accepts_timezone_aware_iso_string():
    value = "2026-08-24T09:30:00+05:30"
    parsed = UpstoxPaperCanaryMarketData._quote_timestamp(value)
    assert parsed.astimezone(timezone.utc) == NOW


def test_quote_timestamp_accepts_timezone_aware_datetime():
    assert UpstoxPaperCanaryMarketData._quote_timestamp(NOW) is NOW


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-24T04:00:00",
        str(int(NOW.timestamp())),
        str(int(NOW.timestamp() * 1_000_000)),
        str(int(NOW.timestamp() * 1_000_000_000)),
        True,
        "",
        "not-a-timestamp",
        9_999_999_999_999,
    ],
)
def test_quote_timestamp_rejects_unsafe_or_ambiguous_values(value):
    with pytest.raises(ValueError):
        UpstoxPaperCanaryMarketData._quote_timestamp(value)


def test_epoch_millisecond_option_quote_normalizes_successfully():
    row = _row(timestamp=int(NOW.timestamp() * 1000))
    quotes = _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    assert len(quotes) == 1
    assert quotes[0].quote_timestamp == NOW


def test_digit_epoch_millisecond_option_quote_normalizes_successfully():
    row = _row(timestamp=str(int(NOW.timestamp() * 1000)))
    quotes = _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    assert quotes[0].quote_timestamp == NOW


def test_invalid_timestamp_is_precisely_classified():
    row = _row(timestamp=str(int(NOW.timestamp())))
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_TIMESTAMP_INVALID",
        MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION,
    )
    assert captured.value.diagnostic.rejected_field == "quote_timestamp"


def test_stale_timestamp_is_precisely_classified():
    row = _row(timestamp=(NOW - timedelta(seconds=121)).isoformat())
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(
            _provider(
                {"data": {"NSE_FO:NIFTY-SYMBOL": row}},
                maximum_age_seconds=120,
            )
        )
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_STALE",
        MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION,
    )


def test_invalid_depth_is_precisely_classified():
    row = _row(market_depth=["raw-depth"])
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_DEPTH_MALFORMED",
        MarketDataReadinessStage.QUOTE_QUALITY_VALIDATION,
    )
    assert captured.value.diagnostic.rejected_type == "list"


def test_invalid_top_of_book_shape_is_precisely_classified():
    row = _row(market_depth={"buy": ["raw-bid"], "sell": []})
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_DEPTH_MALFORMED",
        MarketDataReadinessStage.QUOTE_QUALITY_VALIDATION,
    )


def test_invalid_price_is_precisely_classified():
    row = _row(last_price="not-a-price")
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_PRICE_INVALID",
        MarketDataReadinessStage.QUOTE_QUALITY_VALIDATION,
    )


def test_missing_token_after_outer_key_fallback_is_precisely_classified():
    row = _row()
    row.pop("instrument_token")
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider({"data": {"NSE_FO:51834": row}}))
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_TOKEN_MISSING",
        MarketDataReadinessStage.OPTION_QUOTE_CORRELATION,
    )


@pytest.mark.parametrize("payload", [[], {"data": []}, {"status": "success"}])
def test_malformed_top_level_response_remains_response_malformed(payload):
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider(payload))
    _assert_diagnostic(
        captured.value,
        "OPTION_QUOTE_RESPONSE_MALFORMED",
        MarketDataReadinessStage.OPTION_QUOTE_COLLECTION,
    )


def test_normalization_diagnostic_excludes_raw_payload_and_credentials():
    secret = "Bearer-super-secret-token"
    row = _row(timestamp=secret, raw_payload={"account": "private-account"})
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _quotes(_provider({"data": {"NSE_FO:NIFTY-SYMBOL": row}}))
    rendered = str(captured.value)
    assert secret not in rendered
    assert "private-account" not in rendered
    assert "Authorization" not in rendered
