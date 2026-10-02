
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from .domain import IST
from .oi_vwap_live_futures_v1 import FuturesCandle, completed_futures_vwap

API_BASE = "https://api.upstox.com"
NIFTY_UNDERLYING_KEY = "NSE_INDEX|Nifty 50"


class UpstoxLiveFuturesError(RuntimeError):
    pass


@dataclass(frozen=True)
class FuturesInstrument:
    instrument_key: str
    trading_symbol: str
    expiry: date
    lot_size: int
    underlying_key: str
    underlying_symbol: str


def _headers(token: str) -> dict[str, str]:
    if not token:
        raise UpstoxLiveFuturesError("UPSTOX_ACCESS_TOKEN is missing")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _safe_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        return f"HTTP {response.status_code}"
    code = body.get("errors", [{}])[0].get("errorCode") if isinstance(body, dict) else None
    message = body.get("errors", [{}])[0].get("message") if isinstance(body, dict) else None
    return f"HTTP {response.status_code}" + (f" {code}" if code else "") + (f": {message}" if message else "")


class UpstoxLiveFuturesGatewayV1:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.token = token
        self.client = client or httpx.Client(timeout=20)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        response = self.client.get(
            f"{API_BASE}{path}",
            params=params,
            headers=_headers(self.token),
        )
        if response.status_code != 200:
            raise UpstoxLiveFuturesError(_safe_error(response))
        try:
            body = response.json()
        except Exception as exc:
            raise UpstoxLiveFuturesError("Upstox returned non-JSON response") from exc
        if body.get("status") != "success":
            raise UpstoxLiveFuturesError("Upstox response status was not success")
        return body

    def _search(self, expiry: str) -> list[dict]:
        body = self._get(
            "/v2/instruments/search",
            params={
                "query": "NIFTY",
                "exchanges": "NSE",
                "segments": "FO",
                "instrument_types": "FUT",
                "expiry": expiry,
                "page_number": 1,
                "records": 30,
            },
        )
        return list(body.get("data", []))

    def resolve_nifty_front_future(self, *, today: date | None = None) -> FuturesInstrument:
        today = today or datetime.now(IST).date()

        candidates: list[dict] = []
        # Current month should contain the active front contract. next_month is
        # queried as a fallback for expiry-day / provider-transition edge cases.
        for expiry_filter in ("current_month", "next_month"):
            for row in self._search(expiry_filter):
                if row.get("instrument_type") != "FUT":
                    continue
                if row.get("segment") != "NSE_FO":
                    continue
                if row.get("underlying_symbol") != "NIFTY":
                    continue
                if row.get("underlying_key") != NIFTY_UNDERLYING_KEY:
                    continue
                try:
                    expiry = date.fromisoformat(row["expiry"])
                except Exception:
                    continue
                if expiry < today:
                    continue
                candidates.append(row)

        if not candidates:
            raise UpstoxLiveFuturesError("No active NIFTY futures contract found")

        # Deduplicate because current_month/next_month queries can overlap.
        by_key = {row["instrument_key"]: row for row in candidates}
        selected = min(
            by_key.values(),
            key=lambda row: (date.fromisoformat(row["expiry"]), row["instrument_key"]),
        )
        return FuturesInstrument(
            instrument_key=selected["instrument_key"],
            trading_symbol=selected.get("trading_symbol", ""),
            expiry=date.fromisoformat(selected["expiry"]),
            lot_size=int(selected.get("lot_size") or selected.get("minimum_lot") or 0),
            underlying_key=selected["underlying_key"],
            underlying_symbol=selected["underlying_symbol"],
        )

    def fetch_intraday_5m(self, instrument_key: str) -> list[FuturesCandle]:
        encoded = quote(instrument_key, safe="")
        body = self._get(
            f"/v3/historical-candle/intraday/{encoded}/minutes/5"
        )
        candles = []
        for raw in body.get("data", {}).get("candles", []):
            if not isinstance(raw, list) or len(raw) < 6:
                raise UpstoxLiveFuturesError("Malformed futures candle row")
            try:
                ts = datetime.fromisoformat(str(raw[0]).replace("Z", "+00:00"))
                candles.append(
                    FuturesCandle(
                        timestamp=ts,
                        open=float(raw[1]),
                        high=float(raw[2]),
                        low=float(raw[3]),
                        close=float(raw[4]),
                        volume=int(raw[5]),
                    )
                )
            except Exception as exc:
                raise UpstoxLiveFuturesError("Invalid futures candle schema") from exc
        candles.sort(key=lambda c: c.timestamp)
        return candles

    def latest_completed_vwap(self, *, available_at: datetime | None = None):
        available_at = available_at or datetime.now(IST)
        instrument = self.resolve_nifty_front_future(today=available_at.astimezone(IST).date())
        candles = self.fetch_intraday_5m(instrument.instrument_key)
        vwap = completed_futures_vwap(candles, available_at=available_at)
        return instrument, vwap


def _diagnose() -> int:
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    gateway = UpstoxLiveFuturesGatewayV1(token)
    try:
        now = datetime.now(IST)
        instrument, vwap = gateway.latest_completed_vwap(available_at=now)
        print(json.dumps({
            "status": "PASS",
            "available_at": now.isoformat(),
            "instrument": {
                "instrument_key": instrument.instrument_key,
                "trading_symbol": instrument.trading_symbol,
                "expiry": instrument.expiry.isoformat(),
                "lot_size": instrument.lot_size,
            },
            "latest_completed_vwap": {
                "candle_time": vwap.candle_time,
                "available_at": vwap.available_at,
                "close": vwap.close,
                "volume": vwap.volume,
                "cumulative_vwap": vwap.cumulative_vwap,
                "distance": vwap.distance,
                "side": vwap.side,
            },
        }, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL",
            "reason": type(exc).__name__,
            "detail": str(exc),
        }, indent=2))
        return 2
    finally:
        gateway.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m market_lab.upstox_live_futures_v1")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnose")
    args = parser.parse_args()
    if args.command == "diagnose":
        raise SystemExit(_diagnose())


if __name__ == "__main__":
    main()
