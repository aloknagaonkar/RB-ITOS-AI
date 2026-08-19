from datetime import date

import pytest

from red_bar_lab.services.nifty_futures_resolver import (
    NiftyFuturesResolutionError,
    resolve_nifty_monthly_future,
)


def test_resolver_exactly_matches_nifty_and_selects_nearest_non_expired():
    rows = [
        {
            "instrument_key": "NSE_FO|BANK",
            "trading_symbol": "BANKNIFTY FUT 25 AUG 26",
            "underlying_symbol": "BANKNIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": 1787682599000,
        },
        {
            "instrument_key": "NSE_FO|68407",
            "trading_symbol": "NIFTY FUT 29 SEP 26",
            "underlying_symbol": "NIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": "2026-09-29",
        },
        {
            "instrument_key": "NSE_FO|58072",
            "trading_symbol": "NIFTY FUT 25 AUG 26",
            "underlying_symbol": "NIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": 1787682599000,
        },
    ]

    contract = resolve_nifty_monthly_future(
        rows,
        as_of_date=date(2026, 8, 18),
    )

    assert contract.instrument_key == "NSE_FO|58072"
    assert contract.trading_symbol == "NIFTY FUT 25 AUG 26"
    assert contract.expiry == date(2026, 8, 25)


def test_resolver_rejects_expired_only_contracts():
    rows = [
        {
            "instrument_key": "NSE_FO|OLD",
            "trading_symbol": "NIFTY FUT 28 JUL 26",
            "underlying_symbol": "NIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": "2026-07-28",
        }
    ]

    with pytest.raises(NiftyFuturesResolutionError, match="CONTRACT_NOT_FOUND"):
        resolve_nifty_monthly_future(rows, as_of_date=date(2026, 8, 18))
