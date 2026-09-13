"""Historical NIFTY 1-minute OHLC sidecar for midpoint-structure research.

This module intentionally creates a separate, read-only research sidecar.
It does not change PCR, positioning, option OHLC, or observation caches.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from .domain import HistoricalCandle

PROVENANCE = "HISTORICAL_UNDERLYING_CANDLE_RECONSTRUCTION"
SCHEMA_VERSION = 1


class HistoricalUnderlyingOHLCGateway(Protocol):
    def historical_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...


@dataclass(frozen=True)
class UnderlyingOHLCRow:
    session_date: date
    underlying: str
    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    provenance: str = PROVENANCE


@dataclass(frozen=True)
class UnderlyingOHLCSession:
    schema_version: int
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    underlying: str
    session_date: date
    row_count: int
    rows: tuple[UnderlyingOHLCRow, ...]
    issues: tuple[str, ...]
    provenance: str = PROVENANCE


def reconstruct_session(
    gateway: HistoricalUnderlyingOHLCGateway,
    underlying: str,
    session_date: date,
) -> UnderlyingOHLCSession:
    candles = sorted(
        gateway.historical_candles(underlying, session_date),
        key=lambda x: x.timestamp,
    )
    if not candles:
        return UnderlyingOHLCSession(
            SCHEMA_VERSION,
            "UNAVAILABLE",
            underlying,
            session_date,
            0,
            (),
            ("No historical underlying candles returned.",),
        )

    rows = tuple(
        UnderlyingOHLCRow(
            session_date=session_date,
            underlying=underlying,
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candles
    )
    return UnderlyingOHLCSession(
        SCHEMA_VERSION,
        "AVAILABLE",
        underlying,
        session_date,
        len(rows),
        rows,
        (),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(x) for x in value]
    if isinstance(value, list):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def session_to_dict(session: UnderlyingOHLCSession) -> dict[str, Any]:
    return _jsonable(asdict(session))


def write_combined_csv(
    sessions: Sequence[UnderlyingOHLCSession], output: str | Path
) -> int:
    rows = [
        row
        for session in sessions
        if session.status == "AVAILABLE"
        for row in session.rows
    ]
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0

    fieldnames = list(asdict(rows[0]).keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_jsonable(asdict(row)))
    return len(rows)


def write_combined_json(
    sessions: Sequence[UnderlyingOHLCSession], output: str | Path
) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provenance": PROVENANCE,
        "session_count": len(sessions),
        "available_session_count": sum(s.status == "AVAILABLE" for s in sessions),
        "row_count": sum(
            s.row_count for s in sessions if s.status == "AVAILABLE"
        ),
        "sessions": [session_to_dict(s) for s in sessions],
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _main() -> None:
    from dotenv import load_dotenv

    from .gateways import GatewayError, UpstoxGateway
    from .historical_batch import load_historical_batch_manifest

    parser = argparse.ArgumentParser(
        description="Build raw historical underlying 1-minute OHLC sidecar"
    )
    parser.add_argument("--underlying", default="NSE_INDEX|Nifty 50")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output", required=True)
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    manifest = load_historical_batch_manifest(args.manifest)
    gateway = UpstoxGateway()

    sessions: list[UnderlyingOHLCSession] = []
    for spec in manifest.sessions:
        try:
            sessions.append(
                reconstruct_session(
                    gateway,
                    args.underlying,
                    spec.session_date,
                )
            )
        except (GatewayError, OSError, ValueError) as error:
            sessions.append(
                UnderlyingOHLCSession(
                    SCHEMA_VERSION,
                    "UNAVAILABLE",
                    args.underlying,
                    spec.session_date,
                    0,
                    (),
                    (str(error),),
                )
            )

    write_combined_json(sessions, args.output)
    row_count = write_combined_csv(sessions, args.csv_output)

    print(
        json.dumps(
            {
                "status": (
                    "AVAILABLE"
                    if all(s.status == "AVAILABLE" for s in sessions)
                    else "PARTIAL"
                ),
                "requested_session_count": len(sessions),
                "available_session_count": sum(
                    s.status == "AVAILABLE" for s in sessions
                ),
                "unavailable_session_count": sum(
                    s.status == "UNAVAILABLE" for s in sessions
                ),
                "row_count": row_count,
                "output": args.output,
                "csv_output": args.csv_output,
                "provenance": PROVENANCE,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()
