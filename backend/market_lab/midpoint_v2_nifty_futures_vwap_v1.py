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


def resolve_active_future(
    client: httpx.Client,
    session_date: date,
    expiries: Iterable[date],
) -> FutureContract:
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
            x for x in rows
            if str(x.get("instrument_type") or "").upper() == "FUT"
        ]
        if not fut_rows:
            continue
        row = fut_rows[0]
        return FutureContract(
            instrument_key=str(row["instrument_key"]),
            expiry=date.fromisoformat(str(row.get("expiry") or expiry.isoformat())[:10]),
            trading_symbol=row.get("trading_symbol"),
            instrument_type=row.get("instrument_type"),
        )
    raise RuntimeError(f"No NIFTY future found for {session_date}")


def fetch_one_minute_candles(
    client: httpx.Client,
    instrument_key: str,
    session_date: date,
) -> list[dict]:
    encoded = quote(instrument_key, safe="")
    path = (
        f"/v2/expired-instruments/historical-candle/"
        f"{encoded}/1minute/{session_date.isoformat()}/{session_date.isoformat()}"
    )
    r = client.get(path)
    r.raise_for_status()
    raw = r.json().get("data", {}).get("candles", [])
    rows = []
    for v in raw:
        if not isinstance(v, list) or len(v) < 6:
            continue
        rows.append({
            "timestamp": v[0],
            "open": float(v[1]),
            "high": float(v[2]),
            "low": float(v[3]),
            "close": float(v[4]),
            "volume": int(v[5]) if v[5] is not None else None,
            "open_interest": int(v[6]) if len(v) >= 7 and v[6] is not None else None,
        })
    rows.sort(key=lambda x: datetime.fromisoformat(x["timestamp"]))
    return rows


def add_session_vwap(rows: list[dict]) -> list[dict]:
    cum_pv = 0.0
    cum_vol = 0
    out = []
    for row in rows:
        vol = row["volume"]
        if vol is None or vol < 0:
            raise ValueError("Futures volume missing/invalid; VWAP cannot be computed")
        typical = (row["high"] + row["low"] + row["close"]) / 3.0
        cum_pv += typical * vol
        cum_vol += vol
        vwap = (cum_pv / cum_vol) if cum_vol > 0 else None
        out.append({
            **row,
            "typical_price": typical,
            "session_cumulative_volume": cum_vol,
            "session_vwap": vwap,
        })
    return out


def load_session_dates(path: Path) -> list[date]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        values.append(date.fromisoformat(s))
    return sorted(set(values))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-dates-file", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    session_dates = load_session_dates(Path(args.session_dates_file))
    if not session_dates:
        raise SystemExit("No session dates supplied")

    all_rows = []
    with _client() as client:
        expiries = available_expiries(client)
        for session_date in session_dates:
            contract = resolve_active_future(client, session_date, expiries)
            rows = add_session_vwap(
                fetch_one_minute_candles(client, contract.instrument_key, session_date)
            )
            for r in rows:
                all_rows.append({
                    "session_date": session_date.isoformat(),
                    "expiry": contract.expiry.isoformat(),
                    "instrument_key": contract.instrument_key,
                    "trading_symbol": contract.trading_symbol,
                    **r,
                })
            print(
                f"{session_date}: {contract.instrument_key} "
                f"expiry={contract.expiry} candles={len(rows)}"
            )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "session_date", "expiry", "instrument_key", "trading_symbol",
        "timestamp", "open", "high", "low", "close", "volume", "open_interest",
        "typical_price", "session_cumulative_volume", "session_vwap",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows -> {out}")


if __name__ == "__main__":
    main()
