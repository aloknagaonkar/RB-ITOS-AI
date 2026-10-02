#!/usr/bin/env python3
"""
V29.1 DATA-INTEGRITY REPAIR

Problem addressed
-----------------
The original V29 prep accepted sessions using NIFTY underlying availability only.
At least one accepted session (2024-11-29) has no 1-minute futures candles from
the canonical futures collector, so the OOS validator correctly stopped.

This repair does NOT change Family-B, V20, or the frozen V29 exit candidate.

It rebuilds the SAME 100-session pre-V23 OOS universe using a stricter rule:
  - exactly 375 NIFTY underlying 1m bars
  - canonical futures collector succeeds
  - exactly 375 futures 1m/VWAP rows

The latest possible date remains 2025-02-05.
If an originally accepted session lacks futures data, it is excluded and an
older dual-valid session is discovered.

Outputs overwrite only the V29 manifest/date-list after the full 100-session
dual-valid set is found:
- data/historical-validation/manifest-b-v29-pre-v23-100.json
- data/historical-validation/session-dates-b-v29-pre-v23-100.txt

It also writes an audit:
- data/historical-validation/b-v29-dual-validity-audit-v29_1.json
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
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
END_DATE = date(2025, 2, 5)
MIN_DATE = date(2023, 1, 1)

MANIFEST = Path(
    "data/historical-validation/manifest-b-v29-pre-v23-100.json"
)
DATES_FILE = Path(
    "data/historical-validation/session-dates-b-v29-pre-v23-100.txt"
)
AUDIT_FILE = Path(
    "data/historical-validation/b-v29-dual-validity-audit-v29_1.json"
)


def fetch_underlying(gateway: UpstoxGateway, d: date):
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


def validate_futures_one_day(d: date):
    """
    Use the canonical collector itself as the validator.
    No duplicated futures-resolution logic is introduced here.
    """
    with tempfile.TemporaryDirectory(prefix="b-v29-futures-check-") as td:
        td = Path(td)
        dates = td / "date.txt"
        output = td / "futures.csv"
        dates.write_text(d.isoformat() + "\n", encoding="utf-8")

        cmd = [
            sys.executable,
            "-m",
            "market_lab.midpoint_v2_nifty_futures_vwap_v1",
            "--session-dates-file",
            str(dates),
            "--output",
            str(output),
        ]

        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if p.returncode != 0:
            tail = "\n".join(p.stdout.splitlines()[-4:])
            return False, 0, tail

        if not output.exists():
            return False, 0, "collector succeeded but output file is missing"

        with output.open(newline="") as fh:
            rows = list(csv.DictReader(fh))

        return len(rows) == 375, len(rows), p.stdout.strip()


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
    audit = []
    d = END_DATE

    print("V29.1 — DISCOVER 100 DUAL-VALID UNDERLYING + FUTURES SESSIONS")
    print("=" * 110)

    while d >= MIN_DATE and len(selected) < TARGET:
        if d.weekday() >= 5:
            d -= timedelta(days=1)
            continue

        underlying = fetch_underlying(gateway, d)
        ucount = len(underlying)

        if ucount != 375:
            print(f"SKIP-U {d} underlying={ucount}")
            audit.append({
                "session_date": d.isoformat(),
                "underlying_rows": ucount,
                "futures_rows": None,
                "accepted": False,
                "reason": "UNDERLYING_NOT_375",
            })
            d -= timedelta(days=1)
            continue

        ok, fcount, detail = validate_futures_one_day(d)

        if not ok:
            print(f"SKIP-F {d} underlying=375 futures={fcount}")
            audit.append({
                "session_date": d.isoformat(),
                "underlying_rows": 375,
                "futures_rows": fcount,
                "accepted": False,
                "reason": "FUTURES_NOT_375",
                "collector_tail": detail,
            })
            d -= timedelta(days=1)
            time.sleep(0.15)
            continue

        future_expiries = [x for x in expiries if x >= d]
        if not future_expiries:
            raise RuntimeError(f"No expiry metadata available for {d}")

        expiry = future_expiries[0]

        selected.append({
            "session_date": d.isoformat(),
            "expiry": expiry.isoformat(),
        })
        audit.append({
            "session_date": d.isoformat(),
            "underlying_rows": 375,
            "futures_rows": 375,
            "accepted": True,
            "reason": "DUAL_VALID",
        })

        print(
            f"ACCEPT {d} underlying=375 futures=375 "
            f"({len(selected):3d}/{TARGET})"
        )

        d -= timedelta(days=1)
        time.sleep(0.15)

    if len(selected) != TARGET:
        raise SystemExit(
            f"STOP: only found {len(selected)} dual-valid sessions "
            f"between {MIN_DATE} and {END_DATE}"
        )

    selected.sort(key=lambda x: x["session_date"])

    payload = {"sessions": selected}

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    DATES_FILE.write_text(
        "\n".join(x["session_date"] for x in selected) + "\n",
        encoding="utf-8",
    )
    AUDIT_FILE.write_text(
        json.dumps(
            {
                "version": "B_V29_DUAL_VALIDITY_REPAIR_V29_1",
                "target": TARGET,
                "accepted": len(selected),
                "first": selected[0]["session_date"],
                "last": selected[-1]["session_date"],
                "checks": audit,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    rejected_futures = [
        x for x in audit if x["reason"] == "FUTURES_NOT_375"
    ]

    print()
    print("PASS")
    print("dual-valid sessions :", len(selected))
    print("first               :", selected[0]["session_date"])
    print("last                :", selected[-1]["session_date"])
    print("futures rejects     :", len(rejected_futures))
    print(
        "rejected dates      :",
        ", ".join(x["session_date"] for x in rejected_futures) or "none",
    )
    print("manifest            :", MANIFEST)
    print("dates               :", DATES_FILE)
    print("audit               :", AUDIT_FILE)
    print()
    print("IMPORTANT: regenerate BOTH V29 underlying and futures files before validator.")


if __name__ == "__main__":
    main()
