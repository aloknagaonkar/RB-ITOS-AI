from datetime import date

from red_bar_lab.services.nifty_futures_monitoring import (
    NiftyFuturesMonitor,
    futures_monitor_log_values,
)


class _Provider:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.calls = []

    def search_instruments(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return list(self.rows)


def _rows():
    return [
        {
            "instrument_key": "NSE_FO|58072",
            "trading_symbol": "NIFTY FUT 25 AUG 26",
            "underlying_symbol": "NIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": "2026-08-25",
        },
        {
            "instrument_key": "NSE_FO|68407",
            "trading_symbol": "NIFTY FUT 29 SEP 26",
            "underlying_symbol": "NIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": "2026-09-29",
        },
    ]


def test_monitor_resolves_and_caches_contract_for_trading_date():
    provider = _Provider(_rows())
    monitor = NiftyFuturesMonitor(provider)
    trading_date = date(2026, 8, 20)

    first = monitor.resolve(as_of_date=trading_date)
    second = monitor.resolve(as_of_date=trading_date)

    assert first.status == "READY"
    assert first.instrument_key == "NSE_FO|58072"
    assert first.expiry == "2026-08-25"
    assert second is first
    assert len(provider.calls) == 2


def test_monitor_refreshes_on_next_trading_date():
    provider = _Provider(_rows())
    monitor = NiftyFuturesMonitor(provider)

    monitor.resolve(as_of_date=date(2026, 8, 20))
    monitor.resolve(as_of_date=date(2026, 8, 21))

    assert len(provider.calls) == 4


def test_monitor_returns_non_throwing_unavailable_result():
    provider = _Provider([])
    result = NiftyFuturesMonitor(provider).resolve(
        as_of_date=date(2026, 8, 20)
    )

    assert result.status == "UNAVAILABLE"
    assert result.instrument_key is None
    assert "CONTRACT_NOT_FOUND" in str(result.error)


def test_futures_monitor_log_values_are_stable():
    provider = _Provider(_rows())
    result = NiftyFuturesMonitor(provider).resolve(
        as_of_date=date(2026, 8, 20)
    )

    assert futures_monitor_log_values(result) == (
        "READY",
        "Nearest non-expired NIFTY futures contract resolved.",
        "NSE_FO|58072",
        "NIFTY FUT 25 AUG 26",
        "2026-08-25",
        "4",
        "NONE",
    )
