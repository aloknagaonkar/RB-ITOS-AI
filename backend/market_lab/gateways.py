"""Provider boundary. No strategies depend on Upstox response objects."""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote

import httpx

from .domain import Contract, HistoricalCandle, PCRConfig, Quote, Snapshot

UTC = timezone.utc


class GatewayError(Exception):
    """Safe operational message; never contains tokens or response bodies."""


class DataGateway(Protocol):
    def collect(self, config: PCRConfig) -> Snapshot: ...


def parse_timestamp(value) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value) / 1000, UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def normalize_upstox(config, catalog_body, chain_body, spot_body, started, received):
    def valid_oi(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
            return None
        return int(value)

    def valid_price(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return None
        return float(value)

    contracts = []
    for row in catalog_body["data"]:
        if row["expiry"] != config.expiry.isoformat() or row["underlying_key"] != config.underlying:
            raise ValueError("Contract catalog identity mismatch")
        contracts.append(
            Contract(key=row["instrument_key"], strike=row["strike_price"], side=row["instrument_type"])
        )
    by_key = {c.key: c for c in contracts}
    quotes = []
    for row in chain_body["data"]:
        if row["expiry"] != config.expiry.isoformat() or row["underlying_key"] != config.underlying:
            raise ValueError("Chain identity mismatch")
        for side, field in (("CE", "call_options"), ("PE", "put_options")):
            option = row.get(field)
            if not option:
                continue
            key = option["instrument_key"]
            contract = by_key.get(key)
            if contract is None or (contract.strike, contract.side) != (row["strike_price"], side):
                raise ValueError("Quote contract identity mismatch")
            market_data = option.get("market_data", {})
            oi = valid_oi(market_data.get("oi"))
            prev_oi = valid_oi(market_data.get("prev_oi"))
            # Preserve absent/invalid OI as unavailable. Do not coerce booleans, negatives or fractions.
            quotes.append(Quote(
                key=key,
                oi=oi,
                prev_oi=prev_oi,
                ltp=valid_price(market_data.get("ltp")),
                bid=valid_price(market_data.get("bid_price")),
                ask=valid_price(market_data.get("ask_price")),
                volume=valid_oi(market_data.get("volume")),
            ))
    spots = [q for q in spot_body["data"].values() if q.get("instrument_token") == config.underlying]
    if len(spots) != 1:
        raise ValueError("Underlying quote missing or ambiguous")
    spot = spots[0]
    return Snapshot(
        provider="upstox",
        underlying=config.underlying,
        expiry=config.expiry,
        started_at=started,
        received_at=received,
        spot=spot["last_price"],
        spot_feed_at=parse_timestamp(spot.get("timestamp")),
        catalog=contracts,
        quotes=quotes,
        raw={"catalog": catalog_body, "chain": chain_body, "spot": spot_body},
    )


def normalize_upstox_historical_candles(
    instrument_key: str, session_date: date, body: dict
) -> list[HistoricalCandle]:
    """Normalize Upstox V3 [time, O, H, L, C, volume?, OI?] candles."""

    def number(value, field):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Historical candle {field} is invalid")
        return float(value)

    def optional_integer(values, index, field):
        if index >= len(values) or values[index] is None:
            return None
        value = values[index]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
            raise ValueError(f"Historical candle {field} is invalid")
        return int(value)

    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise ValueError("Historical candle response data is invalid")
    values = body["data"].get("candles")
    if not isinstance(values, list):
        raise ValueError("Historical candle collection is invalid")
    candles = []
    for value in values:
        if not isinstance(value, list) or len(value) < 5:
            raise ValueError("Historical candle is incomplete")
        timestamp = parse_timestamp(value[0])
        if timestamp is None:
            raise ValueError("Historical candle timestamp is invalid")
        candles.append(HistoricalCandle(
            provider="upstox",
            instrument_key=instrument_key,
            session_date=session_date,
            timestamp=timestamp,
            open=number(value[1], "open"),
            high=number(value[2], "high"),
            low=number(value[3], "low"),
            close=number(value[4], "close"),
            volume=optional_integer(value, 5, "volume"),
            open_interest=optional_integer(value, 6, "open interest"),
        ))
    candles.sort(key=lambda candle: candle.timestamp)
    if len({candle.timestamp for candle in candles}) != len(candles):
        raise ValueError("Historical candle timestamps are duplicated")
    return candles

class UpstoxGateway:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise GatewayError(
                "Upstox token missing. Set UPSTOX_ACCESS_TOKEN locally and restart the worker."
            )
        self.client = client or httpx.Client(base_url="https://api.upstox.com", timeout=10)
        self.token = token

    def _get(self, path, params):
        try:
            response = self.client.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            )
        except httpx.RequestError:
            raise GatewayError("Upstox network error or timeout; next attempt uses worker backoff.") from None
        if response.status_code in (401, 403):
            raise GatewayError("Upstox authentication or entitlement rejected. Check token and subscription.")
        if response.status_code == 429:
            raise GatewayError("Upstox rate limit reached; collection enters backoff.")
        if response.status_code != 200:
            raise GatewayError(f"Upstox returned HTTP {response.status_code}.")
        try:
            body = response.json()
            if body.get("status") != "success" or "data" not in body:
                raise ValueError
            return body
        except (ValueError, AttributeError):
            raise GatewayError("Upstox response schema invalid.") from None

    def collect(self, config):
        started = datetime.now(UTC)
        params = {"instrument_key": config.underlying, "expiry_date": config.expiry.isoformat()}
        # Catalog fetched independently so a truncated chain cannot define its own expected coverage.
        catalog = self._get("/v2/option/contract", params)
        chain = self._get("/v2/option/chain", params)
        spot = self._get("/v2/market-quote/quotes", {"instrument_key": config.underlying})
        received = datetime.now(UTC)
        try:
            return normalize_upstox(config, catalog, chain, spot, started, received)
        except (ValueError, KeyError, TypeError):
            raise GatewayError(
                "Upstox data failed contract/schema validation; observation rejected."
            ) from None

    def historical_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]:
        encoded_key = quote(instrument_key, safe="")
        requested_date = session_date.isoformat()
        body = self._get(
            f"/v3/historical-candle/{encoded_key}/minutes/1/{requested_date}/{requested_date}",
            {},
        )
        try:
            return normalize_upstox_historical_candles(instrument_key, session_date, body)
        except (ValueError, KeyError, TypeError):
            raise GatewayError(
                "Upstox historical candle data failed schema validation."
            ) from None
    def close(self):
        self.client.close()


class DemoGateway:
    """Deterministic synthetic market; generated times are explicitly not wall-clock quotes."""

    def collect_at(self, config: PCRConfig, at: datetime, step: int) -> Snapshot:
        contracts, quotes = [], []
        spot = 25000 + 135 * math.sin(step / 13) + step * 0.35
        for strike in range(24000, 26001, 50):
            for side in ("CE", "PE"):
                key = f"DEMO|{config.expiry}|{strike}|{side}"
                contracts.append(Contract(key=key, strike=strike, side=side))
                distance = (strike - 25000) / 50
                base = 100000 + 550000 * math.exp(-((distance / 9) ** 2))
                skew = 1 + (0.25 if side == "PE" else -0.12) * math.sin(step / 15 + distance / 5)
                current = round(base * skew)
                previous_step = max(0, step - 1)
                previous_skew = 1 + (0.25 if side == "PE" else -0.12) * math.sin(
                    previous_step / 15 + distance / 5
                )
                quotes.append(Quote(key=key, oi=current, prev_oi=round(base * previous_skew)))
        return Snapshot(
            provider="demo",
            underlying=config.underlying,
            expiry=config.expiry,
            started_at=at - timedelta(milliseconds=80),
            received_at=at,
            spot=spot,
            spot_feed_at=at,
            oi_source_at=at,
            oi_unit="synthetic_units",
            catalog=contracts,
            quotes=quotes,
            raw={"generator": "demo-v1", "step": step, "synthetic": True},
        )
