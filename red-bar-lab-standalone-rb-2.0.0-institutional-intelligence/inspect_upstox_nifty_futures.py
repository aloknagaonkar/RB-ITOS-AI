from __future__ import annotations

import gzip
import io
import json

import requests


URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"


def main() -> None:
    response = requests.get(URL, timeout=60)
    response.raise_for_status()

    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as handle:
        records = json.loads(handle.read().decode("utf-8"))

    matches = []

    for row in records:
        instrument_type = str(row.get("instrument_type") or "").upper()
        trading_symbol = str(
            row.get("trading_symbol")
            or row.get("tradingsymbol")
            or ""
        ).upper()

        underlying = str(
            row.get("underlying_symbol")
            or row.get("name")
            or ""
        ).upper()

        if instrument_type not in {"FUTIDX", "FUT"}:
            continue

        if "NIFTY" not in trading_symbol and underlying != "NIFTY":
            continue

        matches.append(
            {
                "instrument_key": row.get("instrument_key"),
                "trading_symbol": (
                    row.get("trading_symbol")
                    or row.get("tradingsymbol")
                ),
                "instrument_type": row.get("instrument_type"),
                "expiry": row.get("expiry"),
                "underlying_symbol": row.get("underlying_symbol"),
                "name": row.get("name"),
                "segment": row.get("segment"),
                "exchange": row.get("exchange"),
                "lot_size": row.get("lot_size"),
            }
        )

    matches.sort(key=lambda row: str(row.get("expiry") or ""))

    print("NIFTY FUTURES FOUND:", len(matches))
    for row in matches[:20]:
        print(json.dumps(row, indent=2, default=str))


if __name__ == "__main__":
    main()
