from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import os
from typing import Callable

import pandas as pd

from red_bar_lab.brokers.upstox_client import UpstoxClient


class MissingAccessToken(RuntimeError):
    pass


def resolve_access_token(session_token: str = "") -> str:
    token = (session_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()
    if not token:
        raise MissingAccessToken(
            "Upstox access token is required. Enter it in the Red Bar sidebar "
            "or set UPSTOX_ACCESS_TOKEN."
        )
    return token


@dataclass
class RedBarUpstoxService:
    access_token: str
    client_factory: Callable[[str], UpstoxClient] = UpstoxClient

    def _client(self) -> UpstoxClient:
        return self.client_factory(self.access_token)

    def historical_candles(
        self,
        instrument_key: str,
        start_date: date,
        end_date: date,
        interval_minutes: int = 1,
    ) -> pd.DataFrame:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        return self._client().get_historical_candles(
            instrument_key,
            from_date=start_date.isoformat(),
            to_date=end_date.isoformat(),
            interval=interval_minutes,
            unit="minutes",
        )

    def intraday_candles(
        self,
        instrument_key: str,
        interval_minutes: int = 1,
    ) -> pd.DataFrame:
        return self._client().get_intraday_candles(
            instrument_key,
            interval=interval_minutes,
            unit="minutes",
        )



    def expired_option_expiries(
        self,
        instrument_key: str,
    ) -> list[str]:
        return self._client().get_expired_option_expiries(
            instrument_key
        )

    def expired_option_contracts(
        self,
        instrument_key: str,
        expiry_date: str,
    ) -> list[dict[str, object]]:
        return self._client().get_expired_option_contracts(
            instrument_key, expiry_date
        )

    def expired_option_historical_candles(
        self,
        expired_instrument_key: str,
        trading_date: str,
        interval_minutes: int = 1,
    ) -> pd.DataFrame:
        return self._client().get_expired_historical_candles(
            expired_instrument_key, trading_date, trading_date,
            interval=interval_minutes,
        )

    def historical_oi(
        self,
        instrument_key: str,
        expiry: str,
        trading_date: str,
    ) -> dict[str, object]:
        return self._client().get_historical_oi(
            instrument_key,
            expiry,
            trading_date,
        )

    def historical_change_oi(
        self,
        instrument_key: str,
        expiry: str,
        trading_date: str,
        interval_days: int = 1,
    ) -> dict[str, object]:
        return self._client().get_historical_change_oi(
            instrument_key,
            expiry,
            trading_date,
            interval_days=interval_days,
        )


    def option_contracts(
        self,
        instrument_key: str,
        expiry_date: str | None = None,
    ) -> list[dict[str, object]]:
        return self._client().get_option_contracts(
            instrument_key,
            expiry_date,
        )

    def option_greeks(
        self,
        instrument_keys: list[str],
    ) -> dict[str, dict[str, object]]:
        return self._client().get_option_greeks(instrument_keys)

    def option_expiries(self, instrument_key: str) -> list[str]:
        return self._client().get_option_expiries(instrument_key)

    def option_chain(
        self,
        instrument_key: str,
        expiry_date: str,
    ) -> list[dict[str, object]]:
        return self._client().get_option_chain(
            instrument_key,
            expiry_date,
        )

    def option_chain_dataframe(
        self,
        records: list[dict[str, object]],
    ) -> pd.DataFrame:
        return self._client().option_chain_to_dataframe(records)
    def connection_health(self) -> dict[str, object]:
        try:
            today = date.today()
            frame = self.historical_candles(
                "NSE_INDEX|Nifty 50",
                today - timedelta(days=10),
                today,
                interval_minutes=1,
            )
            return {
                "ok": not frame.empty,
                "message": "Connected" if not frame.empty else "Connected, but no candles returned",
                "rows": len(frame),
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc), "rows": 0}
