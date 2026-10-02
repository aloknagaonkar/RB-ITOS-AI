"""Historical raw option OHLC sidecar for deterministic premium backtests.

This module intentionally leaves the existing PCR and positioning caches untouched.
It reconstructs the same option universe required by the historical research pipeline,
then persists raw 1-minute option OHLCV+OI by exact instrument key so later backtests
can follow a frozen contract even after it leaves the moving ATM ±N basket.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal, Protocol, Sequence

from .domain import HistoricalCandle, HistoricalOptionCandleSeries, HistoricalOptionContract, IST
from .historical import (
    load_historical_option_candles,
    resolve_historical_atm,
    resolve_historical_option_contracts,
)

PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"
SCHEMA_VERSION = 1


class HistoricalOptionOHLCGateway(Protocol):
    def historical_candles(self, instrument_key: str, session_date: date) -> list[HistoricalCandle]: ...
    def historical_option_contracts(self, underlying: str, expiry: date) -> list[HistoricalOptionContract]: ...
    def historical_option_candles(self, instrument_key: str, session_date: date) -> list[HistoricalCandle]: ...


@dataclass(frozen=True)
class HistoricalOptionOHLCRow:
    session_date: date
    expiry: date
    underlying: str
    instrument_key: str
    strike: float
    side: str
    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    open_interest: float | None
    provenance: str = PROVENANCE


@dataclass(frozen=True)
class HistoricalOptionOHLCSession:
    schema_version: int
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    underlying: str
    session_date: date
    expiry: date
    wings: int
    strike_interval: int
    row_count: int
    rows: tuple[HistoricalOptionOHLCRow, ...]
    issues: tuple[str, ...]
    provenance: str = PROVENANCE


def rows_from_series(
    *,
    underlying: str,
    expiry: date,
    option_series: Sequence[HistoricalOptionCandleSeries],
) -> list[HistoricalOptionOHLCRow]:
    rows: list[HistoricalOptionOHLCRow] = []
    for series in sorted(option_series, key=lambda x: (x.contract.strike, x.contract.side, x.contract.instrument_key)):
        c = series.contract
        for candle in sorted(series.candles, key=lambda x: x.timestamp):
            rows.append(HistoricalOptionOHLCRow(
                session_date=series.session_date,
                expiry=expiry,
                underlying=underlying,
                instrument_key=c.instrument_key,
                strike=c.strike,
                side=c.side,
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                open_interest=candle.open_interest,
            ))
    return rows


def reconstruct_ohlc_session(
    gateway: HistoricalOptionOHLCGateway,
    underlying: str,
    session_date: date,
    expiry: date,
    wings: int,
    strike_interval: int = 50,
    fixed_anchor_time: time = time(9, 20),
) -> HistoricalOptionOHLCSession:
    underlying_candles = sorted(gateway.historical_candles(underlying, session_date), key=lambda c: c.timestamp)
    if not underlying_candles:
        return HistoricalOptionOHLCSession(
            SCHEMA_VERSION, "UNAVAILABLE", underlying, session_date, expiry, wings, strike_interval,
            0, (), ("underlying_candles_unavailable",),
        )

    atms = resolve_historical_atm(underlying_candles, strike_interval)
    anchor = next(
        (c for c in underlying_candles if c.timestamp.astimezone(IST).time().replace(tzinfo=None) == fixed_anchor_time),
        None,
    )
    fixed_atm = resolve_historical_atm([anchor], strike_interval)[0].atm if anchor is not None else None
    required_atms = {item.atm for item in atms}
    if fixed_atm is not None:
        required_atms.add(fixed_atm)

    catalog = gateway.historical_option_contracts(underlying, expiry)
    selected_by_identity: dict[tuple[float, str], HistoricalOptionContract] = {}
    for atm in sorted(required_atms):
        for contract in resolve_historical_option_contracts(catalog, underlying, expiry, atm, wings, strike_interval):
            identity = (contract.strike, contract.side)
            existing = selected_by_identity.get(identity)
            if existing is not None and existing != contract:
                raise ValueError("Conflicting historical option contract identity")
            selected_by_identity[identity] = contract

    selected = sorted(selected_by_identity.values(), key=lambda c: (c.strike, 0 if c.side == "CE" else 1))
    option_series = load_historical_option_candles(gateway, selected, session_date)
    rows = rows_from_series(underlying=underlying, expiry=expiry, option_series=option_series)
    return HistoricalOptionOHLCSession(
        SCHEMA_VERSION, "AVAILABLE", underlying, session_date, expiry, wings, strike_interval,
        len(rows), tuple(rows), (),
    )


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def session_to_dict(session: HistoricalOptionOHLCSession) -> dict:
    return _jsonable(asdict(session))


def _cache_path(cache_dir: str | Path, underlying: str, session_date: date, expiry: date, wings: int) -> Path:
    safe_underlying = underlying.replace("|", "_").replace("/", "_").replace(" ", "_")
    return Path(cache_dir) / f"{safe_underlying}__{session_date.isoformat()}__{expiry.isoformat()}__w{wings}.json"


def store_session_cache(cache_dir: str | Path, session: HistoricalOptionOHLCSession) -> Path:
    path = _cache_path(cache_dir, session.underlying, session.session_date, session.expiry, session.wings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session_to_dict(session), indent=2) + "\n", encoding="utf-8")
    return path


def load_session_cache(
    cache_dir: str | Path,
    underlying: str,
    session_date: date,
    expiry: date,
    wings: int,
) -> HistoricalOptionOHLCSession | None:
    path = _cache_path(cache_dir, underlying, session_date, expiry, wings)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    rows = []
    for raw in data.get("rows", []):
        item = dict(raw)
        item["session_date"] = date.fromisoformat(item["session_date"])
        item["expiry"] = date.fromisoformat(item["expiry"])
        item["timestamp"] = datetime.fromisoformat(item["timestamp"])
        rows.append(HistoricalOptionOHLCRow(**item))
    return HistoricalOptionOHLCSession(
        schema_version=data["schema_version"],
        status=data["status"],
        underlying=data["underlying"],
        session_date=date.fromisoformat(data["session_date"]),
        expiry=date.fromisoformat(data["expiry"]),
        wings=data["wings"],
        strike_interval=data["strike_interval"],
        row_count=data["row_count"],
        rows=tuple(rows),
        issues=tuple(data.get("issues", [])),
        provenance=data.get("provenance", PROVENANCE),
    )


def write_combined_csv(sessions: Sequence[HistoricalOptionOHLCSession], output: str | Path) -> int:
    rows = [row for session in sessions if session.status == "AVAILABLE" for row in session.rows]
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    fieldnames = list(asdict(rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_jsonable(asdict(row)))
    return len(rows)


def write_combined_json(sessions: Sequence[HistoricalOptionOHLCSession], output: str | Path) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provenance": PROVENANCE,
        "session_count": len(sessions),
        "available_session_count": sum(s.status == "AVAILABLE" for s in sessions),
        "row_count": sum(s.row_count for s in sessions if s.status == "AVAILABLE"),
        "sessions": [session_to_dict(s) for s in sessions],
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _main() -> None:
    from dotenv import load_dotenv
    from .gateways import GatewayError, UpstoxGateway
    from .historical_batch import load_historical_batch_manifest

    parser = argparse.ArgumentParser(description="Build raw historical option OHLC sidecar")
    parser.add_argument("--underlying", default="NSE_INDEX|Nifty 50")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--wings", type=int, default=5)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output", required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    manifest = load_historical_batch_manifest(args.manifest)
    gateway = None
    sessions: list[HistoricalOptionOHLCSession] = []
    hits = misses = fetches = writes = 0
    try:
        for spec in sorted(manifest.sessions, key=lambda item: item.session_date):
            cached = None if args.refresh else load_session_cache(
                args.cache_dir, args.underlying, spec.session_date, spec.expiry, args.wings
            )
            if cached is not None:
                hits += 1
                sessions.append(cached)
                continue
            misses += 1
            try:
                if gateway is None:
                    gateway = UpstoxGateway(os.getenv("UPSTOX_ACCESS_TOKEN", ""))
                fetches += 1
                session = reconstruct_ohlc_session(
                    gateway, args.underlying, spec.session_date, spec.expiry, args.wings
                )
                sessions.append(session)
                if session.status == "AVAILABLE":
                    store_session_cache(args.cache_dir, session)
                    writes += 1
            except (GatewayError, OSError, ValueError) as error:
                sessions.append(HistoricalOptionOHLCSession(
                    SCHEMA_VERSION, "UNAVAILABLE", args.underlying, spec.session_date, spec.expiry,
                    args.wings, 50, 0, (), (str(error),),
                ))
    finally:
        if gateway is not None:
            gateway.close()

    write_combined_json(sessions, args.output)
    row_count = write_combined_csv(sessions, args.csv_output)
    available = sum(s.status == "AVAILABLE" for s in sessions)
    summary = {
        "status": "AVAILABLE" if available == len(sessions) else "PARTIAL",
        "requested_session_count": len(sessions),
        "available_session_count": available,
        "unavailable_session_count": len(sessions) - available,
        "row_count": row_count,
        "cache_hits": hits,
        "cache_misses": misses,
        "provider_fetches": fetches,
        "cache_writes": writes,
        "cache_dir": args.cache_dir,
        "output": args.output,
        "csv_output": args.csv_output,
        "provenance": PROVENANCE,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    _main()
