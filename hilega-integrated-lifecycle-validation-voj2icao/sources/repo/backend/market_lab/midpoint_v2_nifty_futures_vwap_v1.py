from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import httpx

BASE_URL = "https://api.upstox.com"
UNDERLYING = "NSE_INDEX|Nifty 50"


@dataclass(frozen=True)
class FutureContract:
    instrument_key: str
    expiry: date
    trading_symbol: str | None
    instrument_type: str | None
    source: str


def _client() -> httpx.Client:
    token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise SystemExit(
            "UPSTOX_ACCESS_TOKEN is not set. Load .env first with: "
            "set -a; source .env; set +a"
        )
    return httpx.Client(
        base_url=BASE_URL,
        timeout=30,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )


def available_expiries(client: httpx.Client) -> list[date]:
    r = client.get(
        "/v2/expired-instruments/expiries",
        params={"instrument_key": UNDERLYING},
    )
    r.raise_for_status()
    return sorted(date.fromisoformat(x) for x in (r.json().get("data") or []))


def resolve_expired_future(
    client: httpx.Client,
    session_date: date,
    expiries: Iterable[date],
) -> FutureContract | None:
    """
    Resolve the nearest already-expired NIFTY futures contract that was active
    for the requested historical session.

    The expired-instruments expiry list can contain weekly option expiries as
    well as monthly futures expiries, so each candidate expiry is queried and
    only an actual FUT row is accepted.
    """
    for expiry in [x for x in expiries if x >= session_date]:
        r = client.get(
            "/v2/expired-instruments/future/contract",
            params={
                "instrument_key": UNDERLYING,
                "expiry_date": expiry.isoformat(),
            },
        )
        if r.status_code != 200:
            continue

        rows = r.json().get("data") or []
        fut_rows = [
            x
            for x in rows
            if str(x.get("instrument_type") or "").upper() == "FUT"
        ]
        if not fut_rows:
            continue

        row = fut_rows[0]
        return FutureContract(
            instrument_key=str(row["instrument_key"]),
            expiry=date.fromisoformat(
                str(row.get("expiry") or expiry.isoformat())[:10]
            ),
            trading_symbol=row.get("trading_symbol"),
            instrument_type=row.get("instrument_type"),
            source="EXPIRED_FUTURE_API",
        )

    return None


def search_current_nifty_futures(client: httpx.Client) -> list[dict]:
    """
    Query the current Upstox instrument search API for live/current NIFTY
    futures. This is required when the historical session belongs to the
    presently active monthly future, which is not yet available through the
    expired-futures API.
    """
    r = client.get(
        "/v2/instruments/search",
        params={
            "query": "NIFTY",
            "exchanges": "NSE",
            "segments": "FUT",
            "instrument_types": "FUT",
            "records": 30,
            "page_number": 1,
        },
    )
    r.raise_for_status()

    rows = r.json().get("data") or []
    result = []
    for row in rows:
        if str(row.get("instrument_type") or "").upper() != "FUT":
            continue

        underlying_symbol = str(row.get("underlying_symbol") or "").upper()
        trading_symbol = str(row.get("trading_symbol") or "").upper()
        name = str(row.get("name") or "").upper()

        is_nifty = (
            underlying_symbol == "NIFTY"
            or trading_symbol.startswith("NIFTY FUT")
            or name == "NIFTY"
            or name == "NIFTY 50"
        )
        if not is_nifty:
            continue

        raw_expiry = row.get("expiry")
        if not raw_expiry:
            continue

        result.append(row)

    return result


def resolve_current_future(
    client: httpx.Client,
    session_date: date,
) -> FutureContract | None:
    rows = search_current_nifty_futures(client)

    candidates = []
    for row in rows:
        expiry = date.fromisoformat(str(row["expiry"])[:10])
        if expiry >= session_date:
            candidates.append((expiry, row))

    if not candidates:
        return None

    expiry, row = sorted(candidates, key=lambda x: x[0])[0]

    return FutureContract(
        instrument_key=str(row["instrument_key"]),
        expiry=expiry,
        trading_symbol=row.get("trading_symbol"),
        instrument_type=row.get("instrument_type"),
        source="CURRENT_INSTRUMENT_SEARCH_API",
    )


def resolve_active_future(
    client: httpx.Client,
    session_date: date,
    expired_expiries: Iterable[date],
) -> FutureContract:
    """
    Resolution order:
      1. expired futures API
      2. current instrument-search API

    This handles the boundary where, for example, Aug-26/Sep sessions belong to
    the still-live September monthly future and therefore are absent from the
    expired-futures endpoint.
    """
    expired = resolve_expired_future(client, session_date, expired_expiries)
    if expired is not None:
        return expired

    current = resolve_current_future(client, session_date)
    if current is not None:
        return current

    raise RuntimeError(
        f"No NIFTY future found for {session_date} in either expired or current APIs"
    )


def fetch_expired_one_minute_candles(
    client: httpx.Client,
    instrument_key: str,
    session_date: date,
) -> list[list]:
    encoded = quote(instrument_key, safe="")
    path = (
        f"/v2/expired-instruments/historical-candle/"
        f"{encoded}/1minute/{session_date.isoformat()}/{session_date.isoformat()}"
    )
    r = client.get(path)
    r.raise_for_status()
    return r.json().get("data", {}).get("candles", [])


def fetch_current_one_minute_candles(
    client: httpx.Client,
    instrument_key: str,
    session_date: date,
) -> list[list]:
    encoded = quote(instrument_key, safe="")
    path = (
        f"/v3/historical-candle/{encoded}/minutes/1/"
        f"{session_date.isoformat()}/{session_date.isoformat()}"
    )
    r = client.get(path)
    r.raise_for_status()
    return r.json().get("data", {}).get("candles", [])


def normalize_candles(raw: list[list]) -> list[dict]:
    rows = []
    for v in raw:
        if not isinstance(v, list) or len(v) < 6:
            continue

        rows.append(
            {
                "timestamp": v[0],
                "open": float(v[1]),
                "high": float(v[2]),
                "low": float(v[3]),
                "close": float(v[4]),
                "volume": int(v[5]) if v[5] is not None else None,
                "open_interest": (
                    int(v[6])
                    if len(v) >= 7 and v[6] is not None
                    else None
                ),
            }
        )

    rows.sort(key=lambda x: datetime.fromisoformat(x["timestamp"]))
    return rows


def fetch_one_minute_candles(
    client: httpx.Client,
    contract: FutureContract,
    session_date: date,
) -> list[dict]:
    if contract.source == "EXPIRED_FUTURE_API":
        raw = fetch_expired_one_minute_candles(
            client, contract.instrument_key, session_date
        )
    elif contract.source == "CURRENT_INSTRUMENT_SEARCH_API":
        raw = fetch_current_one_minute_candles(
            client, contract.instrument_key, session_date
        )
    else:
        raise ValueError(f"Unsupported contract source: {contract.source}")

    return normalize_candles(raw)


def add_session_vwap(rows: list[dict]) -> list[dict]:
    cum_pv = 0.0
    cum_vol = 0
    out = []

    for row in rows:
        vol = row["volume"]
        if vol is None or vol < 0:
            raise ValueError(
                "Futures volume missing/invalid; VWAP cannot be computed"
            )

        typical = (row["high"] + row["low"] + row["close"]) / 3.0
        cum_pv += typical * vol
        cum_vol += vol
        vwap = (cum_pv / cum_vol) if cum_vol > 0 else None

        out.append(
            {
                **row,
                "typical_price": typical,
                "session_cumulative_volume": cum_vol,
                "session_vwap": vwap,
            }
        )

    return out


def load_session_dates(path: Path) -> list[date]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        values.append(date.fromisoformat(s))
    return sorted(set(values))


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "session_date",
        "expiry",
        "instrument_key",
        "trading_symbol",
        "contract_source",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
        "typical_price",
        "session_cumulative_volume",
        "session_vwap",
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-dates-file", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    session_dates = load_session_dates(Path(args.session_dates_file))
    if not session_dates:
        raise SystemExit("No session dates supplied")

    out = Path(args.output)
    all_rows = []

    with _client() as client:
        expired_expiries = available_expiries(client)

        for session_date in session_dates:
            contract = resolve_active_future(
                client,
                session_date,
                expired_expiries,
            )

            rows = add_session_vwap(
                fetch_one_minute_candles(client, contract, session_date)
            )

            if not rows:
                raise RuntimeError(
                    f"No 1-minute futures candles returned for "
                    f"{session_date} {contract.instrument_key}"
                )

            for r in rows:
                all_rows.append(
                    {
                        "session_date": session_date.isoformat(),
                        "expiry": contract.expiry.isoformat(),
                        "instrument_key": contract.instrument_key,
                        "trading_symbol": contract.trading_symbol,
                        "contract_source": contract.source,
                        **r,
                    }
                )

            # Checkpoint after every successfully completed session so an API
            # failure never discards already-collected research data.
            write_rows(out, all_rows)

            print(
                f"{session_date}: {contract.instrument_key} "
                f"expiry={contract.expiry} source={contract.source} "
                f"candles={len(rows)}"
            )

    print(f"Wrote {len(all_rows)} rows -> {out}")


if __name__ == "__main__":
    main()
