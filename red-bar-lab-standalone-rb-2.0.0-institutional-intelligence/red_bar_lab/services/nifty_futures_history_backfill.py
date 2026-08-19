from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Sequence

import pandas as pd
import requests

from red_bar_lab.services.historical_service import (
    RedBarHistoricalService,
    normalize_candles,
)
from red_bar_lab.services.nifty_futures_resolver import (
    NiftyFuturesContract,
    NiftyFuturesResolutionError,
    resolve_nifty_monthly_future,
)
from red_bar_lab.services.upstox_service import RedBarUpstoxService


NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"
UPSTOX_NSE_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
)


class ExpiredFuturesGateway(Protocol):
    def expiries(self, instrument_key: str) -> Sequence[str]: ...

    def future_contracts(
        self, instrument_key: str, expiry_date: str
    ) -> Sequence[Mapping[str, object]]: ...

    def historical_candles(
        self, expired_instrument_key: str, trading_date: date
    ) -> pd.DataFrame: ...


class UpstoxExpiredFuturesGateway:
    """Small adapter for Upstox expired-futures APIs.

    The repository already exposes expiry discovery and expired candle retrieval.
    Only the expired future-contract lookup is performed here, keeping the change
    additive and isolated from the shared broker client.
    """

    def __init__(
        self,
        provider: RedBarUpstoxService,
        *,
        timeout: int = 20,
        session: requests.Session | None = None,
    ) -> None:
        self.provider = provider
        self.timeout = timeout
        self.session = session or requests.Session()

    def expiries(self, instrument_key: str) -> Sequence[str]:
        return self.provider.expired_option_expiries(instrument_key)

    def future_contracts(
        self, instrument_key: str, expiry_date: str
    ) -> Sequence[Mapping[str, object]]:
        response = self.session.get(
            "https://api.upstox.com/v2/expired-instruments/future/contract",
            params={
                "instrument_key": instrument_key,
                "expiry_date": expiry_date,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.provider.access_token}",
            },
            timeout=self.timeout,
        )
        if not response.ok:
            try:
                payload = response.json()
                errors = payload.get("errors") or []
                message = (
                    errors[0].get("message")
                    if errors and isinstance(errors[0], dict)
                    else payload.get("message")
                )
            except (TypeError, ValueError):
                message = response.text
            raise RuntimeError(
                f"Expired future contract lookup failed: HTTP {response.status_code}: "
                f"{message or 'request failed'}"
            )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("Malformed expired future-contract response.")
        return [dict(item) for item in data if isinstance(item, dict)]

    def historical_candles(
        self, expired_instrument_key: str, trading_date: date
    ) -> pd.DataFrame:
        return self.provider.expired_option_historical_candles(
            expired_instrument_key,
            trading_date.isoformat(),
            interval_minutes=1,
        )


@dataclass(frozen=True)
class FuturesBackfillDayResult:
    trading_date: str
    status: str
    source_type: str
    instrument_key: str | None
    trading_symbol: str | None
    expiry: str | None
    rows: int
    cache_path: str | None
    reason: str | None = None


@dataclass(frozen=True)
class FuturesBackfillResult:
    days: tuple[FuturesBackfillDayResult, ...]
    downloaded_days: int
    existing_days: int
    blocked_days: int
    rows_stored: int
    manifest_path: Path


def load_upstox_nse_instruments(
    *,
    url: str = UPSTOX_NSE_INSTRUMENTS_URL,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> list[dict[str, object]]:
    client = session or requests.Session()
    response = client.get(url, timeout=timeout)
    response.raise_for_status()
    payload = pd.read_json(BytesIO(response.content), compression="gzip")
    return [dict(row) for row in payload.to_dict(orient="records")]


def _contract_from_expired_row(
    row: Mapping[str, object], *, expiry: date
) -> NiftyFuturesContract | None:
    underlying = str(
        row.get("underlying_symbol") or row.get("name") or ""
    ).strip().upper()
    instrument_type = str(row.get("instrument_type") or "").strip().upper()
    segment = str(row.get("segment") or "").strip().upper()
    instrument_key = str(row.get("instrument_key") or "").strip()
    trading_symbol = str(row.get("trading_symbol") or "").strip()
    if underlying != "NIFTY":
        return None
    if instrument_type not in {"FUT", "FUTIDX", "FUTURES"}:
        return None
    if segment not in {"NSE_FO", "NFO"}:
        return None
    if not instrument_key.startswith("NSE_FO|") or not trading_symbol:
        return None
    return NiftyFuturesContract(
        instrument_key=instrument_key,
        trading_symbol=trading_symbol,
        expiry=expiry,
        underlying="NIFTY",
        segment="NSE_FO",
        instrument_type=instrument_type,
        source="UPSTOX_EXPIRED_FUTURES_API",
    )


def resolve_expired_nifty_future(
    gateway: ExpiredFuturesGateway,
    *,
    trading_date: date,
    underlying_key: str = NIFTY_INDEX_KEY,
    maximum_days_to_expiry: int = 45,
) -> NiftyFuturesContract:
    candidates: list[date] = []
    for value in gateway.expiries(underlying_key):
        try:
            expiry = date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
        if trading_date <= expiry <= trading_date + timedelta(days=maximum_days_to_expiry):
            candidates.append(expiry)

    for expiry in sorted(set(candidates)):
        rows = gateway.future_contracts(underlying_key, expiry.isoformat())
        contracts = [
            contract
            for row in rows
            if (contract := _contract_from_expired_row(row, expiry=expiry)) is not None
        ]
        if contracts:
            return min(contracts, key=lambda item: item.instrument_key)

    raise NiftyFuturesResolutionError(
        f"EXPIRED_NIFTY_FUTURES_CONTRACT_NOT_FOUND for {trading_date.isoformat()}"
    )


def _resolve_contract_for_date(
    trading_date: date,
    *,
    active_instruments: Sequence[Mapping[str, object]],
    expired_gateway: ExpiredFuturesGateway,
) -> tuple[NiftyFuturesContract, str]:
    """Prefer the true expired current-month contract before today's BOD file.

    Current BOD instruments may contain later expiries that were already listed on
    an older trading date. Selecting from BOD first would incorrectly map July
    sessions to the August contract. The expired API is therefore authoritative
    whenever it exposes a monthly future for the requested historical date.
    """
    try:
        return (
            resolve_expired_nifty_future(
                expired_gateway,
                trading_date=trading_date,
            ),
            "EXPIRED",
        )
    except NiftyFuturesResolutionError:
        return (
            resolve_nifty_monthly_future(
                active_instruments,
                as_of_date=trading_date,
            ),
            "ACTIVE",
        )


def _write_expired_day(
    historical: RedBarHistoricalService,
    gateway: ExpiredFuturesGateway,
    *,
    contract: NiftyFuturesContract,
    trading_date: date,
    force: bool,
) -> tuple[str, int, Path]:
    path = historical.layout.candle_path(
        historical.provider_name,
        contract.instrument_key,
        1,
        trading_date.isoformat(),
    )
    if path.exists() and not force:
        cached = historical.read_day(contract.instrument_key, trading_date, 1)
        return "EXISTING", len(cached), path

    source = gateway.historical_candles(contract.instrument_key, trading_date)
    frame = historical._filter_session_date(source, trading_date)
    if frame.empty:
        return "BLOCKED", 0, path
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_candles(frame).to_csv(path, index=False)
    return "DOWNLOADED", len(frame), path


def backfill_nifty_futures_history(
    trading_dates: Iterable[date],
    *,
    historical: RedBarHistoricalService,
    active_instruments: Sequence[Mapping[str, object]],
    expired_gateway: ExpiredFuturesGateway,
    artifacts_root: str | Path,
    force: bool = False,
    manifest_name: str = "red_bar_v2_validation_manifest.csv",
) -> FuturesBackfillResult:
    results: list[FuturesBackfillDayResult] = []
    manifest_rows: list[dict[str, object]] = []

    for trading_date in sorted(set(trading_dates)):
        try:
            contract, source_type = _resolve_contract_for_date(
                trading_date,
                active_instruments=active_instruments,
                expired_gateway=expired_gateway,
            )
        except Exception as exc:
            results.append(
                FuturesBackfillDayResult(
                    trading_date=trading_date.isoformat(),
                    status="BLOCKED",
                    source_type="UNRESOLVED",
                    instrument_key=None,
                    trading_symbol=None,
                    expiry=None,
                    rows=0,
                    cache_path=None,
                    reason=str(exc),
                )
            )
            continue

        try:
            if source_type == "ACTIVE":
                download = historical.load_or_download(
                    contract.instrument_key,
                    trading_date,
                    trading_date,
                    interval_minutes=1,
                    force=force,
                )
                if download.downloaded_dates:
                    status = "DOWNLOADED"
                elif download.existing_dates:
                    status = "EXISTING"
                else:
                    status = "BLOCKED"
                frame = historical.read_day(contract.instrument_key, trading_date, 1)
                rows = len(frame)
                path = historical.layout.candle_path(
                    historical.provider_name,
                    contract.instrument_key,
                    1,
                    trading_date.isoformat(),
                )
            else:
                status, rows, path = _write_expired_day(
                    historical,
                    expired_gateway,
                    contract=contract,
                    trading_date=trading_date,
                    force=force,
                )
        except Exception as exc:
            results.append(
                FuturesBackfillDayResult(
                    trading_date=trading_date.isoformat(),
                    status="BLOCKED",
                    source_type=source_type,
                    instrument_key=contract.instrument_key,
                    trading_symbol=contract.trading_symbol,
                    expiry=contract.expiry.isoformat(),
                    rows=0,
                    cache_path=None,
                    reason=str(exc),
                )
            )
            continue

        reason = None if status != "BLOCKED" else "NO_FUTURES_CANDLES_RETURNED"
        results.append(
            FuturesBackfillDayResult(
                trading_date=trading_date.isoformat(),
                status=status,
                source_type=source_type,
                instrument_key=contract.instrument_key,
                trading_symbol=contract.trading_symbol,
                expiry=contract.expiry.isoformat(),
                rows=rows,
                cache_path=str(path),
                reason=reason,
            )
        )
        if status in {"DOWNLOADED", "EXISTING"} and rows > 0:
            manifest_rows.append(
                {
                    "trading_date": trading_date.isoformat(),
                    "futures_instrument_key": contract.instrument_key,
                    "futures_symbol": contract.trading_symbol,
                    "futures_expiry": contract.expiry.isoformat(),
                    "exit_timestamps": "",
                    "expected_regime": "",
                }
            )

    report_root = Path(artifacts_root) / "reports" / "red_bar_v2_multiday"
    report_root.mkdir(parents=True, exist_ok=True)
    manifest_path = report_root / manifest_name
    pd.DataFrame(
        manifest_rows,
        columns=[
            "trading_date",
            "futures_instrument_key",
            "futures_symbol",
            "futures_expiry",
            "exit_timestamps",
            "expected_regime",
        ],
    ).to_csv(manifest_path, index=False)

    return FuturesBackfillResult(
        days=tuple(results),
        downloaded_days=sum(item.status == "DOWNLOADED" for item in results),
        existing_days=sum(item.status == "EXISTING" for item in results),
        blocked_days=sum(item.status == "BLOCKED" for item in results),
        rows_stored=sum(item.rows for item in results),
        manifest_path=manifest_path,
    )
