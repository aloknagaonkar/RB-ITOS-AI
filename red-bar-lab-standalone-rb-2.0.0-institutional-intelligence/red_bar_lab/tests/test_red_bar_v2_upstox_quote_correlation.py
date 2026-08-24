from __future__ import annotations

from datetime import datetime, timezone

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


class _Client:
    BASE_URL_V2 = "https://example.invalid/v2"
    timeout = 1


def _provider() -> UpstoxPaperCanaryMarketData:
    return UpstoxPaperCanaryMarketData(
        _Client(),
        underlying_keys={"NIFTY 50": "NSE_INDEX|Nifty 50"},
        maximum_quote_age_seconds=120,
    )


def _row(token: str, *, key: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_token": token,
        "last_price": 100.0,
        "bid_price": 99.0,
        "ask_price": 101.0,
        "timestamp": NOW.isoformat(),
    }
    if key is not None:
        row["instrument_key"] = key
    return row


def _requested(count: int = 18) -> tuple[str, ...]:
    return tuple(f"NSE_FO|{51000 + index}" for index in range(count))


def _prime_tokens(provider: UpstoxPaperCanaryMarketData, requested: tuple[str, ...]) -> None:
    provider._expected_tokens.update({key: key for key in requested})


def _correlate(provider, payload, requested):
    return provider._correlate_quote_rows(
        payload=payload,
        requested_keys=requested,
    )


def test_outer_trading_symbol_uses_embedded_stable_instrument_token():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    payload = {
        "NSE_FO:NIFTY26AUG24300CE": _row("NSE_FO|51834"),
    }
    correlated = _correlate(provider, payload, requested)
    assert tuple(correlated) == requested


def test_all_eighteen_quotes_correlate_independent_of_response_order():
    provider = _provider()
    requested = _requested()
    _prime_tokens(provider, requested)
    payload = {
        f"NSE_FO:NIFTY-{index}": _row(key)
        for index, key in reversed(tuple(enumerate(requested)))
    }
    correlated = _correlate(provider, payload, requested)
    assert len(correlated) == 18
    assert set(correlated) == set(requested)


def test_duplicate_embedded_token_is_rejected():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    payload = {
        "NSE_FO:SYMBOL-A": _row("NSE_FO|51834"),
        "NSE_FO:SYMBOL-B": _row("NSE_FO|51834"),
    }
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_DUPLICATE"


def test_missing_embedded_identity_uses_valid_outer_key_fallback():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    payload = {
        "NSE_FO:51834": {
            "last_price": 100.0,
            "timestamp": NOW.isoformat(),
        }
    }
    correlated = _correlate(provider, payload, requested)
    assert tuple(correlated) == requested


def test_unrequested_embedded_token_is_not_overridden_by_outer_key():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    payload = {
        "NSE_FO:51834": _row("NSE_FO|99999"),
    }
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_IDENTITY_UNREQUESTED"


def test_ambiguous_token_index_is_rejected():
    provider = _provider()
    requested = ("NSE_FO|51834", "NSE_FO|51835")
    provider._expected_tokens.update({key: "SHARED" for key in requested})
    payload = {"NSE_FO:SYMBOL": _row("SHARED")}
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_IDENTITY_AMBIGUOUS"


def test_non_mapping_response_row_is_rejected_safely():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, {"NSE_FO:SYMBOL": ["secret-payload"]}, requested)
    error = captured.value
    assert error.diagnostic.reason_code == "OPTION_QUOTE_ROW_NOT_MAPPING"
    assert error.diagnostic.rejected_type == "list"
    assert "secret-payload" not in str(error)


def test_missing_required_quote_field_is_rejected():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    payload = {
        "NSE_FO:SYMBOL": {
            "instrument_token": "NSE_FO|51834",
            "timestamp": NOW.isoformat(),
        }
    }
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_REQUIRED_FIELD_MISSING"
    assert captured.value.diagnostic.rejected_field == "quote_price"


def test_partial_seventeen_of_eighteen_is_count_incomplete():
    provider = _provider()
    requested = _requested()
    _prime_tokens(provider, requested)
    payload = {
        f"NSE_FO:SYMBOL-{index}": _row(key)
        for index, key in enumerate(requested[:-1])
    }
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    diagnostic = captured.value.diagnostic
    assert diagnostic.reason_code == "OPTION_QUOTE_COUNT_INCOMPLETE"
    assert diagnostic.received_count == 17
    assert diagnostic.normalized_count == 17
    assert diagnostic.rejected_count == 1


def test_conflicting_canonical_embedded_and_outer_identities_are_rejected():
    provider = _provider()
    requested = ("NSE_FO|51834", "NSE_FO|51835")
    _prime_tokens(provider, requested)
    payload = {
        "NSE_FO:51835": _row("NSE_FO|51834"),
    }
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_IDENTITY_CONFLICT"


def test_diagnostics_never_include_token_like_or_raw_payload_values():
    provider = _provider()
    requested = ("NSE_FO|51834",)
    _prime_tokens(provider, requested)
    secret = "Bearer-super-secret-token"
    payload = {
        "NSE_FO:51834": {
            "instrument_token": secret,
            "raw_payload": {"account": "private-account"},
            "last_price": 100.0,
            "timestamp": NOW.isoformat(),
        }
    }
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        _correlate(provider, payload, requested)
    rendered = str(captured.value)
    assert secret not in rendered
    assert "private-account" not in rendered
    assert captured.value.stage is MarketDataReadinessStage.OPTION_QUOTE_CORRELATION
