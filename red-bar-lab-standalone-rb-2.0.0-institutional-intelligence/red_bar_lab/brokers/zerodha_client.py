from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from hashlib import sha256
from urllib.parse import urlencode

import pandas as pd
import requests


class ZerodhaAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZerodhaSession:
    user_id: str | None
    user_name: str | None
    email: str | None
    broker: str | None


class ZerodhaKiteClient:
    """Read-only Kite Connect client for Red Bar paper execution.

    RB-0.7.4.5 intentionally exposes no order-placement method. Zerodha is used
    for authentication, instrument discovery, quotes and candles only.
    """

    API_ROOT = "https://api.kite.trade"
    LOGIN_ROOT = "https://kite.zerodha.com/connect/login"

    def __init__(
        self,
        api_key: str,
        access_token: str | None = None,
        *,
        timeout: int = 15,
    ):
        self.api_key = (api_key or "").strip()
        self.access_token = (access_token or "").strip()
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("Zerodha API key is required.")
        self._instrument_cache: dict[str, pd.DataFrame] = {}

    @property
    def login_url(self) -> str:
        return f"{self.LOGIN_ROOT}?{urlencode({'v': 3, 'api_key': self.api_key})}"

    def _headers(self, authenticated: bool = True):
        headers = {"X-Kite-Version": "3"}
        if authenticated:
            if not self.access_token:
                raise ZerodhaAPIError(
                    "Zerodha access token is required for this request."
                )
            headers["Authorization"] = (
                f"token {self.api_key}:{self.access_token}"
            )
        return headers

    @staticmethod
    def _json_or_error(response: requests.Response):
        try:
            payload = response.json()
        except ValueError as exc:
            raise ZerodhaAPIError(
                f"Zerodha returned non-JSON response: HTTP "
                f"{response.status_code}"
            ) from exc

        if response.status_code >= 400 or payload.get("status") == "error":
            message = (
                payload.get("message")
                or payload.get("error_type")
                or f"HTTP {response.status_code}"
            )
            raise ZerodhaAPIError(str(message))
        return payload

    def exchange_request_token(
        self,
        *,
        request_token: str,
        api_secret: str,
    ) -> str:
        request_token = (request_token or "").strip()
        api_secret = (api_secret or "").strip()
        if not request_token or not api_secret:
            raise ValueError(
                "request_token and api_secret are required."
            )

        checksum = sha256(
            f"{self.api_key}{request_token}{api_secret}".encode("utf-8")
        ).hexdigest()

        response = requests.post(
            f"{self.API_ROOT}/session/token",
            data={
                "api_key": self.api_key,
                "request_token": request_token,
                "checksum": checksum,
            },
            headers={"X-Kite-Version": "3"},
            timeout=self.timeout,
        )
        payload = self._json_or_error(response)
        token = str(payload.get("data", {}).get("access_token") or "")
        if not token:
            raise ZerodhaAPIError(
                "Zerodha token response did not contain access_token."
            )
        self.access_token = token
        return token

    def profile(self) -> ZerodhaSession:
        response = requests.get(
            f"{self.API_ROOT}/user/profile",
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_or_error(response)
        data = payload.get("data") or {}
        return ZerodhaSession(
            user_id=data.get("user_id"),
            user_name=data.get("user_name"),
            email=data.get("email"),
            broker=data.get("broker"),
        )

    def instruments(self, exchange: str = "NFO") -> pd.DataFrame:
        exchange = str(exchange).upper()
        cached = self._instrument_cache.get(exchange)
        if cached is not None:
            return cached.copy()

        response = requests.get(
            f"{self.API_ROOT}/instruments/{exchange}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            self._json_or_error(response)
        frame = pd.read_csv(StringIO(response.text))
        if "expiry" in frame.columns:
            frame["expiry"] = pd.to_datetime(
                frame["expiry"], errors="coerce"
            ).dt.date
        for col in ("strike", "last_price", "tick_size"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(
                    frame[col], errors="coerce"
                )
        if "instrument_token" in frame.columns:
            frame["instrument_token"] = pd.to_numeric(
                frame["instrument_token"], errors="coerce"
            ).astype("Int64")
        if "lot_size" in frame.columns:
            frame["lot_size"] = pd.to_numeric(
                frame["lot_size"], errors="coerce"
            ).fillna(1).astype(int)
        self._instrument_cache[exchange] = frame.copy()
        return frame

    def quote(self, instruments: list[str]) -> dict[str, object]:
        if not instruments:
            return {}
        response = requests.get(
            f"{self.API_ROOT}/quote",
            params=[("i", item) for item in instruments],
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_or_error(response)
        return dict(payload.get("data") or {})

    def ltp(self, instruments: list[str]) -> dict[str, float]:
        if not instruments:
            return {}
        response = requests.get(
            f"{self.API_ROOT}/quote/ltp",
            params=[("i", item) for item in instruments],
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_or_error(response)
        out = {}
        for key, value in (payload.get("data") or {}).items():
            try:
                out[str(key)] = float(value["last_price"])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def historical_candles(
        self,
        *,
        instrument_token: int,
        interval: str,
        date_from: datetime | date | str,
        date_to: datetime | date | str,
        include_oi: bool = True,
    ) -> pd.DataFrame:
        response = requests.get(
            (
                f"{self.API_ROOT}/instruments/historical/"
                f"{int(instrument_token)}/{interval}"
            ),
            params={
                "from": str(date_from),
                "to": str(date_to),
                "oi": 1 if include_oi else 0,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_or_error(response)
        candles = (payload.get("data") or {}).get("candles") or []
        rows = []
        for candle in candles:
            if len(candle) < 6:
                continue
            rows.append(
                {
                    "timestamp": pd.to_datetime(
                        candle[0], errors="coerce"
                    ),
                    "open": candle[1],
                    "high": candle[2],
                    "low": candle[3],
                    "close": candle[4],
                    "volume": candle[5],
                    "oi": candle[6] if len(candle) > 6 else None,
                }
            )
        return pd.DataFrame(rows)

    def nfo_options(
        self,
        *,
        underlying_name: str,
        as_of: date | None = None,
    ) -> pd.DataFrame:
        as_of = as_of or date.today()
        frame = self.instruments("NFO")
        if frame.empty:
            return frame

        name = (
            "NIFTY"
            if underlying_name.upper() == "NIFTY 50"
            else "BANKNIFTY"
            if underlying_name.upper() == "BANK NIFTY"
            else underlying_name.upper().replace(" ", "")
        )

        options = frame[
            frame["instrument_type"].isin(["CE", "PE"])
            & (frame["name"].astype(str).str.upper() == name)
        ].copy()
        if "expiry" in options.columns:
            options = options[
                options["expiry"].notna()
                & (options["expiry"] >= as_of)
            ]
        return options.sort_values(
            ["expiry", "strike", "instrument_type"]
        ).reset_index(drop=True)
