#!/usr/bin/env python3
"""
V22 PREP — discover exactly 100 valid NIFTY trading sessions before the
original Family-B 180-session research universe.

Research boundary
-----------------
Original B-family historical universe begins: 2025-12-12
V22 discovery therefore ends at:              2025-12-11

The script walks backward through weekdays, asks the existing UpstoxGateway
for NIFTY 1-minute candles, and accepts only sessions with exactly 375 bars.

It writes:
- data/historical-validation/manifest-b-v22-untouched-100.json
- data/historical-validation/session-dates-b-v22-untouched-100.txt

"Untouched" here means untouched by the canonical Family-B 180-session
research universe. Do not reinterpret this as a claim about every historical
experiment ever performed in the repository.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from market_lab.gateways import UpstoxGateway
from market_lab.midpoint_v2_nifty_futures_vwap_v1 import (
    UNDERLYING,
    _client,
    available_expiries,
)

TARGET = 100
END_DATE = date(2025, 12, 11)
MIN_DATE = date(2025, 1, 1)

MANIFEST = Path(
    "data/historical-validation/manifest-b-v22-untouched-100.json"
)
DATES_FILE = Path(
    "data/historical-validation/session-dates-b-v22-untouched-100.txt"
)


def fetch_with_retry(gateway: UpstoxGateway, d: date):
    last = None
    for attempt in range(4):
        try:
            return gateway.historical_candles(UNDERLYING, d)
        except Exception as exc:
            last = exc
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise last


def main():
    load_dotenv(Path(".env"))

    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit(
            "UPSTOX_ACCESS_TOKEN is not set. Run: set -a; source .env; set +a"
        )

    gateway = UpstoxGateway(token)

    with _client() as client:
        expiries = available_expiries(client)

    selected = []
    d = END_DATE

    print("V22 PREP — DISCOVER 100 VALID PRE-2025-12-12 SESSIONS")
    print("=" * 110)

    while d >= MIN_DATE and len(selected) < TARGET:
        if d.weekday() >= 5:
            d -= timedelta(days=1)
            continue

        candles = fetch_with_retry(gateway, d)
        count = len(candles)

        if count == 375:
            future_expiries = [x for x in expiries if x >= d]
            if not future_expiries:
                raise RuntimeError(f"No Upstox expiry metadata available for {d}")

            expiry = future_expiries[0]
            selected.append({
                "session_date": d.isoformat(),
                "expiry": expiry.isoformat(),
            })
            print(
                f"ACCEPT {d} bars={count} "
                f"({len(selected):3d}/{TARGET}) expiry_meta={expiry}"
            )
        else:
            print(f"SKIP   {d} bars={count}")

        time.sleep(0.25)
        d -= timedelta(days=1)

    if len(selected) != TARGET:
        raise SystemExit(
            f"STOP: only discovered {len(selected)} valid sessions "
            f"between {MIN_DATE} and {END_DATE}"
        )

    selected.sort(key=lambda x: x["session_date"])

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps({"sessions": selected}, indent=2) + "\n",
        encoding="utf-8",
    )
    DATES_FILE.write_text(
        "\n".join(x["session_date"] for x in selected) + "\n",
        encoding="utf-8",
    )

    print()
    print("PASS")
    print("sessions :", len(selected))
    print("first    :", selected[0]["session_date"])
    print("last     :", selected[-1]["session_date"])
    print("manifest :", MANIFEST)
    print("dates    :", DATES_FILE)


if __name__ == "__main__":
    main()
