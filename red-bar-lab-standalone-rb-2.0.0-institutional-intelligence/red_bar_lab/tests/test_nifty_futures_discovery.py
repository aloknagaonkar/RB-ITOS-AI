from datetime import date

import pytest

from red_bar_lab.services.nifty_futures_discovery import (
    discover_active_nifty_future,
)
from red_bar_lab.services.nifty_futures_resolver import (
    NiftyFuturesResolutionError,
)


class _Provider:
    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls = []

    def search_instruments(self, **kwargs):
        self.calls.append(kwargs)
        expiry = kwargs["expiry"]
        if expiry in self.errors:
            raise self.errors[expiry]
        return self.responses.get(expiry, [])


def _row(key, symbol, expiry):
    return {
        "instrument_key": key,
        "trading_symbol": symbol,
        "underlying_symbol": "NIFTY",
        "segment": "NSE_FO",
        "instrument_type": "FUT",
        "expiry": expiry,
    }


def test_discovers_nearest_contract_across_current_and_next_month():
    provider = _Provider(
        responses={
            "current_month": [
                _row("NSE_FO|AUG", "NIFTY FUT 27 AUG 26", "2026-08-27")
            ],
            "next_month": [
                _row("NSE_FO|SEP", "NIFTY FUT 24 SEP 26", "2026-09-24")
            ],
        }
    )

    result = discover_active_nifty_future(
        provider,
        as_of_date=date(2026, 8, 20),
    )

    assert result.contract.instrument_key == "NSE_FO|AUG"
    assert result.requested_expiries == ("current_month", "next_month")
    assert result.records_seen == 2
    assert [call["expiry"] for call in provider.calls] == [
        "current_month",
        "next_month",
    ]
    assert all(call["query"] == "NIFTY" for call in provider.calls)
    assert all(call["exchanges"] == "NSE" for call in provider.calls)
    assert all(call["segments"] == "FO" for call in provider.calls)
    assert all(call["instrument_types"] == "FUT" for call in provider.calls)
    assert all(call["records"] == 30 for call in provider.calls)


def test_rollover_uses_next_month_when_current_month_is_expired():
    provider = _Provider(
        responses={
            "current_month": [
                _row("NSE_FO|OLD", "NIFTY FUT 20 AUG 26", "2026-08-20")
            ],
            "next_month": [
                _row("NSE_FO|NEW", "NIFTY FUT 24 SEP 26", "2026-09-24")
            ],
        }
    )

    result = discover_active_nifty_future(
        provider,
        as_of_date=date(2026, 8, 21),
    )

    assert result.contract.instrument_key == "NSE_FO|NEW"


def test_one_search_failure_does_not_hide_valid_other_month():
    provider = _Provider(
        responses={
            "next_month": [
                _row("NSE_FO|SEP", "NIFTY FUT 24 SEP 26", "2026-09-24")
            ]
        },
        errors={"current_month": RuntimeError("temporary search failure")},
    )

    result = discover_active_nifty_future(
        provider,
        as_of_date=date(2026, 8, 20),
    )

    assert result.contract.instrument_key == "NSE_FO|SEP"
    assert result.records_seen == 1


def test_failure_contains_discovery_context_when_no_contract_resolves():
    provider = _Provider(
        errors={
            "current_month": RuntimeError("current unavailable"),
            "next_month": RuntimeError("next unavailable"),
        }
    )

    with pytest.raises(NiftyFuturesResolutionError) as exc_info:
        discover_active_nifty_future(
            provider,
            as_of_date=date(2026, 8, 20),
        )

    message = str(exc_info.value)
    assert "NIFTY_FUTURES_CONTRACT_NOT_FOUND" in message
    assert "current_month:RuntimeError:current unavailable" in message
    assert "next_month:RuntimeError:next unavailable" in message
    assert "records_seen=0" in message


def test_non_nifty_results_are_still_rejected_by_strict_resolver():
    provider = _Provider(
        responses={
            "current_month": [
                {
                    "instrument_key": "NSE_FO|BANK",
                    "trading_symbol": "BANKNIFTY FUT 27 AUG 26",
                    "underlying_symbol": "BANKNIFTY",
                    "segment": "NSE_FO",
                    "instrument_type": "FUT",
                    "expiry": "2026-08-27",
                }
            ]
        }
    )

    with pytest.raises(NiftyFuturesResolutionError):
        discover_active_nifty_future(
            provider,
            as_of_date=date(2026, 8, 20),
        )
