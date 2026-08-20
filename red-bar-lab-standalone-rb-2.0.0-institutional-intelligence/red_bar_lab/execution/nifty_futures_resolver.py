from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping


FUTURES_READY = "READY"
FUTURES_MISSING = "MISSING"
FUTURES_INVALID = "INVALID"
FUTURES_EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ActiveFuturesContract:
    status: str
    reason: str
    instrument_key: str | None = None
    trading_symbol: str | None = None
    expiry: str | None = None
    lot_size: int | None = None
    exchange_token: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == FUTURES_READY


def _value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _expiry(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _normalise_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _is_nifty_future(row: Mapping[str, Any]) -> bool:
    instrument_type = _normalise_name(
        _value(row, "instrument_type", "segment_type", "type")
    )
    if instrument_type not in {"FUT", "FUTIDX", "INDEXFUTURE", "FUTURE"}:
        return False

    underlying = _normalise_name(
        _value(
            row,
            "underlying_symbol",
            "underlying_name",
            "name",
            "short_name",
            "trading_symbol",
            "tradingsymbol",
        )
    )
    return underlying.startswith("NIFTY") and not underlying.startswith("NIFTYBANK")


def resolve_active_nifty_future(
    records: Iterable[Mapping[str, Any]],
    *,
    as_of: date | datetime | None = None,
) -> ActiveFuturesContract:
    """Resolve the nearest non-expired NIFTY index future.

    Selection is deterministic and rollover-safe: expired contracts are ignored,
    the nearest valid expiry wins, and instrument key plus symbol break ties.
    This resolver is observational and has no execution authority.
    """

    current = (
        as_of.date()
        if isinstance(as_of, datetime)
        else as_of
        if isinstance(as_of, date)
        else date.today()
    )

    candidates: list[tuple[date, str, str, Mapping[str, Any]]] = []
    invalid_matches = 0
    expired_matches = 0

    for row in records or ():
        if not isinstance(row, Mapping) or not _is_nifty_future(row):
            continue

        expiry = _expiry(_value(row, "expiry", "expiry_date", "contract_expiry"))
        instrument_key = str(
            _value(row, "instrument_key", "instrument_token", "exchange_token") or ""
        ).strip()
        symbol = str(
            _value(row, "trading_symbol", "tradingsymbol", "symbol") or ""
        ).strip()

        if expiry is None or not instrument_key or not symbol:
            invalid_matches += 1
            continue
        if expiry < current:
            expired_matches += 1
            continue

        candidates.append((expiry, instrument_key, symbol, row))

    if not candidates:
        if invalid_matches:
            return ActiveFuturesContract(
                FUTURES_INVALID,
                "NIFTY futures records were found but required contract fields were invalid.",
            )
        if expired_matches:
            return ActiveFuturesContract(
                FUTURES_EXPIRED,
                "Only expired NIFTY futures contracts were available.",
            )
        return ActiveFuturesContract(
            FUTURES_MISSING,
            "No NIFTY futures contract was available.",
        )

    expiry, instrument_key, symbol, row = sorted(
        candidates,
        key=lambda item: (item[0], item[1], item[2]),
    )[0]

    lot_raw = _value(row, "lot_size", "minimum_lot", "market_lot")
    try:
        lot_size = int(float(lot_raw)) if lot_raw not in (None, "") else None
    except (TypeError, ValueError):
        lot_size = None

    exchange_token = _value(row, "exchange_token", "instrument_token")
    return ActiveFuturesContract(
        FUTURES_READY,
        "Nearest non-expired NIFTY futures contract selected.",
        instrument_key=instrument_key,
        trading_symbol=symbol,
        expiry=expiry.isoformat(),
        lot_size=lot_size,
        exchange_token=(str(exchange_token) if exchange_token not in (None, "") else None),
    )
