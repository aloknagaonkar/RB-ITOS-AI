from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from red_bar_lab.services.nifty_futures_resolver import (
    NiftyFuturesContract,
    NiftyFuturesResolutionError,
    resolve_nifty_monthly_future,
)


class InstrumentSearchProvider(Protocol):
    def search_instruments(
        self,
        *,
        query: str,
        exchanges: str,
        segments: str,
        instrument_types: str,
        expiry: str,
        page_number: int,
        records: int,
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class NiftyFuturesDiscovery:
    contract: NiftyFuturesContract
    requested_expiries: tuple[str, ...]
    records_seen: int


def discover_active_nifty_future(
    provider: InstrumentSearchProvider,
    *,
    as_of_date: date,
) -> NiftyFuturesDiscovery:
    """Discover the active NIFTY future through Upstox instrument search.

    Current-month and next-month futures are requested independently. The
    existing strict resolver then performs exact-underlying filtering and
    nearest non-expired selection, preserving rollover safety.
    """

    requested = ("current_month", "next_month")
    records: list[dict[str, object]] = []
    errors: list[str] = []

    for expiry in requested:
        try:
            rows = provider.search_instruments(
                query="NIFTY",
                exchanges="NSE",
                segments="FO",
                instrument_types="FUT",
                expiry=expiry,
                page_number=1,
                records=30,
            )
        except Exception as exc:
            errors.append(f"{expiry}:{type(exc).__name__}:{exc}")
            continue
        records.extend(dict(row) for row in rows if isinstance(row, dict))

    try:
        contract = resolve_nifty_monthly_future(
            records,
            as_of_date=as_of_date,
        )
    except NiftyFuturesResolutionError as exc:
        detail = " | ".join(errors) if errors else "no search errors"
        raise NiftyFuturesResolutionError(
            f"{exc}; discovery={detail}; records_seen={len(records)}"
        ) from exc

    return NiftyFuturesDiscovery(
        contract=contract,
        requested_expiries=requested,
        records_seen=len(records),
    )
