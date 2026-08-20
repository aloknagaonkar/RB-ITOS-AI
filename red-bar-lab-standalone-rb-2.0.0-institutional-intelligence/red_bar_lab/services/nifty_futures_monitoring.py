from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from red_bar_lab.services.nifty_futures_discovery import (
    NiftyFuturesDiscovery,
    discover_active_nifty_future,
)
from red_bar_lab.services.nifty_futures_resolver import (
    NiftyFuturesResolutionError,
)


@dataclass(frozen=True)
class NiftyFuturesMonitorResult:
    status: str
    reason: str
    instrument_key: str | None = None
    trading_symbol: str | None = None
    expiry: str | None = None
    records_seen: int = 0
    error: str | None = None


class NiftyFuturesMonitor:
    """Daily-cached, read-only active NIFTY futures discovery.

    Paper-monitor cycles can run every few seconds, while the active monthly
    contract normally changes only at expiry. Caching by trading date avoids
    repeated instrument-search calls and refreshes automatically on the next
    trading date for rollover safety.
    """

    def __init__(self, provider) -> None:
        self.provider = provider
        self._cached_date: date | None = None
        self._cached_result: NiftyFuturesMonitorResult | None = None

    def resolve(self, *, as_of_date: date) -> NiftyFuturesMonitorResult:
        if self._cached_date == as_of_date and self._cached_result is not None:
            return self._cached_result

        try:
            discovery: NiftyFuturesDiscovery = discover_active_nifty_future(
                self.provider,
                as_of_date=as_of_date,
            )
        except NiftyFuturesResolutionError as exc:
            result = NiftyFuturesMonitorResult(
                status="UNAVAILABLE",
                reason="Active NIFTY futures contract could not be resolved.",
                error=str(exc),
            )
        except Exception as exc:
            result = NiftyFuturesMonitorResult(
                status="ERROR",
                reason="NIFTY futures discovery request failed.",
                error=f"{type(exc).__name__}:{exc}",
            )
        else:
            contract = discovery.contract
            result = NiftyFuturesMonitorResult(
                status="READY",
                reason="Nearest non-expired NIFTY futures contract resolved.",
                instrument_key=contract.instrument_key,
                trading_symbol=contract.trading_symbol,
                expiry=contract.expiry.isoformat(),
                records_seen=discovery.records_seen,
            )

        self._cached_date = as_of_date
        self._cached_result = result
        return result


def futures_monitor_log_values(result: NiftyFuturesMonitorResult) -> tuple[str, ...]:
    return (
        result.status,
        result.reason,
        result.instrument_key or "NA",
        result.trading_symbol or "NA",
        result.expiry or "NA",
        str(result.records_seen),
        result.error or "NONE",
    )
