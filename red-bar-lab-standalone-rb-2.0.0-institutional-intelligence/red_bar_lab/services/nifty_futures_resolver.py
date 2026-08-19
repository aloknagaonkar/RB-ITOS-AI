from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Mapping


@dataclass(frozen=True)
class NiftyFuturesContract:
    instrument_key: str
    trading_symbol: str
    expiry: date
    underlying: str
    segment: str
    instrument_type: str
    source: str = "UPSTOX_NSE_INSTRUMENT_MASTER"


class NiftyFuturesResolutionError(ValueError):
    """Raised when a trustworthy NIFTY monthly futures contract is unavailable."""


def _expiry_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return datetime.fromtimestamp(number, tz=timezone.utc).date()
    text = str(value or "").strip()
    if not text:
        raise ValueError("expiry is empty")
    if text.isdigit():
        return _expiry_date(int(text))
    return date.fromisoformat(text[:10])


def _value(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def resolve_nifty_monthly_future(
    instruments: Iterable[Mapping[str, object]],
    *,
    as_of_date: date,
) -> NiftyFuturesContract:
    """Select the nearest non-expired exact NIFTY NSE futures contract.

    Exact underlying matching deliberately excludes BANKNIFTY, FINNIFTY,
    MIDCPNIFTY, NIFTYNXT50 and other symbols containing the word NIFTY.
    """
    candidates: list[NiftyFuturesContract] = []
    for row in instruments:
        underlying = str(
            _value(row, "underlying_symbol", "underlying", "name") or ""
        ).strip().upper()
        segment = str(_value(row, "segment", "exchange") or "").strip().upper()
        instrument_type = str(
            _value(row, "instrument_type", "instrumentType", "type") or ""
        ).strip().upper()
        if underlying != "NIFTY":
            continue
        if segment not in {"NSE_FO", "NFO"}:
            continue
        if instrument_type not in {"FUT", "FUTIDX", "FUTURES"}:
            continue
        try:
            expiry = _expiry_date(_value(row, "expiry", "expiry_date"))
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        if expiry < as_of_date:
            continue
        instrument_key = str(
            _value(row, "instrument_key", "instrumentKey") or ""
        ).strip()
        trading_symbol = str(
            _value(row, "trading_symbol", "tradingsymbol", "tradingSymbol") or ""
        ).strip()
        if not instrument_key.startswith("NSE_FO|"):
            continue
        if not trading_symbol:
            continue
        candidates.append(
            NiftyFuturesContract(
                instrument_key=instrument_key,
                trading_symbol=trading_symbol,
                expiry=expiry,
                underlying=underlying,
                segment="NSE_FO",
                instrument_type=instrument_type,
            )
        )

    if not candidates:
        raise NiftyFuturesResolutionError(
            f"NIFTY_FUTURES_CONTRACT_NOT_FOUND for {as_of_date.isoformat()}"
        )
    return min(candidates, key=lambda item: (item.expiry, item.instrument_key))
