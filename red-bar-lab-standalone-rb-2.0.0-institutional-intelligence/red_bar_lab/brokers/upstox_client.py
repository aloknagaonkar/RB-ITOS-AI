from __future__ import annotations

from datetime import date, timedelta
import logging
import re
from typing import Any
from urllib.parse import quote, unquote

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


class UpstoxAPIError(RuntimeError):
    pass


class ObservableRetry(Retry):
    """Bounded idempotent retry policy with credential-safe telemetry."""

    def increment(self, method=None, url=None, response=None, error=None, *args, **kwargs):
        next_retry = super().increment(
            method=method,
            url=url,
            response=response,
            error=error,
            *args,
            **kwargs,
        )
        endpoint = str(url or "").split("?", 1)[0]
        logger.warning(
            "broker_get_retry method=%s endpoint=%s status=%s remaining=%s error=%s",
            str(method or "UNKNOWN").upper(),
            endpoint,
            getattr(response, "status", "NONE"),
            getattr(next_retry, "total", "UNKNOWN"),
            type(error).__name__ if error is not None else "NONE",
        )
        return next_retry


class UpstoxClient:
    BASE_URL_V2 = "https://api.upstox.com/v2"
    BASE_URL_V3 = "https://api.upstox.com/v3"

    def __init__(
        self,
        access_token: str,
        timeout: int = 20,
        session: requests.Session | None = None,
    ) -> None:
        self.access_token = access_token.strip()
        self.timeout = timeout
        self.session = session or requests.Session()
        self._configure_get_retry_policy()

    def _configure_get_retry_policy(self) -> None:
        retry = ObservableRetry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        mount = getattr(self.session, "mount", None)
        if callable(mount):
            adapter = HTTPAdapter(max_retries=retry)
            mount("https://", adapter)
            mount("http://", adapter)
        self.get_retry_policy = {
            "total": 3,
            "backoff_factor": 0.5,
            "status_forcelist": (429, 502, 503, 504),
            "allowed_methods": ("GET", "HEAD", "OPTIONS"),
            "respect_retry_after_header": True,
            "observability": "broker_get_retry",
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    @staticmethod
    def _raise_for_api_error(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            payload = response.json()
            errors = payload.get("errors") or []
            message = (
                errors[0].get("message")
                if errors and isinstance(errors[0], dict)
                else payload.get("message")
            )
        except ValueError:
            message = response.text
        raise UpstoxAPIError(f"HTTP {response.status_code}: {message or 'Request failed'}")

    def exchange_code(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.BASE_URL_V2}/login/authorization/token",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "code": code.strip(),
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "redirect_uri": redirect_uri.strip(),
                "grant_type": "authorization_code",
            },
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        return response.json()

    def get_option_expiries(self, instrument_key: str) -> list[str]:
        response = self.session.get(
            f"{self.BASE_URL_V2}/option/contract",
            params={"instrument_key": instrument_key},
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        expiries = sorted(
            {
                str(contract.get("expiry"))
                for contract in (payload.get("data") or [])
                if contract.get("expiry")
            }
        )
        if not expiries:
            raise UpstoxAPIError(f"No active option expiries found for {instrument_key}.")
        return expiries

    def get_option_contracts(
        self,
        instrument_key: str,
        expiry_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"instrument_key": instrument_key}
        if expiry_date:
            params["expiry_date"] = expiry_date
        response = self.session.get(
            f"{self.BASE_URL_V2}/option/contract",
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise UpstoxAPIError("Malformed option-contract response.")
        return [dict(row) for row in data if isinstance(row, dict)]

    def get_option_greeks(
        self,
        instrument_keys: list[str],
    ) -> dict[str, dict[str, Any]]:
        keys = [str(key).strip() for key in instrument_keys if str(key).strip()]
        if not keys:
            return {}
        if len(keys) > 50:
            raise ValueError(
                "Upstox Option Greeks API supports at most 50 instrument keys "
                "per request."
            )
        response = self.session.get(
            f"{self.BASE_URL_V3}/market-quote/option-greek",
            params={"instrument_key": ",".join(keys)},
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise UpstoxAPIError("Malformed option-greeks response.")
        return {
            str(key): dict(value)
            for key, value in data.items()
            if isinstance(value, dict)
        }

    def get_option_chain(self, instrument_key: str, expiry_date: str) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.BASE_URL_V2}/option/chain",
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") or []
        if not data:
            raise UpstoxAPIError(
                f"No option-chain records returned for instrument_key={instrument_key}, "
                f"expiry_date={expiry_date}."
            )
        return data

    def get_historical_oi(
        self,
        instrument_key: str,
        expiry: str,
        trading_date: str,
    ) -> dict[str, Any]:
        response = self.session.get(
            f"{self.BASE_URL_V2}/market/oi",
            params={
                "instrument_key": instrument_key,
                "expiry": expiry,
                "date": trading_date,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise UpstoxAPIError("Malformed historical OI response.")
        return dict(data)

    def get_historical_change_oi(
        self,
        instrument_key: str,
        expiry: str,
        trading_date: str,
        interval_days: int = 1,
    ) -> dict[str, Any]:
        response = self.session.get(
            f"{self.BASE_URL_V2}/market/change-oi",
            params={
                "instrument_key": instrument_key,
                "expiry": expiry,
                "date": trading_date,
                "interval": int(interval_days),
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise UpstoxAPIError("Malformed historical Change-in-OI response.")
        return dict(data)

    def get_expired_option_expiries(self, instrument_key: str, *, timeout: float | None = None) -> list[str]:
        response = self.session.get(
            f"{self.BASE_URL_V2}/expired-instruments/expiries",
            params={"instrument_key": instrument_key},
            headers=self._headers(),
            timeout=timeout or self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise UpstoxAPIError("Malformed expired-expiry response.")
        return sorted(
            {
                str(item.get("expiry") if isinstance(item, dict) else item)
                for item in data
                if (item.get("expiry") if isinstance(item, dict) else item)
            }
        )

    def get_expired_option_contracts(self, instrument_key: str, expiry_date: str, *, timeout: float | None = None) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.BASE_URL_V2}/expired-instruments/option/contract",
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
            headers=self._headers(),
            timeout=timeout or self.timeout,
        )
        self._raise_for_api_error(response)
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise UpstoxAPIError("Malformed expired-contract response.")
        return [dict(item) for item in data if isinstance(item, dict)]

    def get_expired_historical_candles(
        self,
        expired_instrument_key: str,
        from_date: str,
        to_date: str,
        *,
        interval: int = 1,
        timeout: float | None = None,
    ) -> pd.DataFrame:
        path = (
            "/expired-instruments/historical-candle/"
            + self._encode_instrument_key(expired_instrument_key)
            + f"/{interval}minute/{to_date}/{from_date}"
        )
        response = self.session.get(
            f"{self.BASE_URL_V2}{path}",
            headers=self._headers(),
            timeout=timeout or self.timeout,
        )
        if response.status_code in (401, 403, 429):
            self._raise_for_api_error(response)
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise UpstoxAPIError("Malformed expired-candle response.") from None
        data = payload.get("data") if isinstance(payload, dict) else None
        candles = data.get("candles") if isinstance(data, dict) else None
        if not response.ok or not isinstance(candles, list):
            raise UpstoxAPIError("Expired historical candles unavailable.")
        return self.candles_to_dataframe(candles)

    def get_historical_candles(
        self,
        instrument_key: str,
        from_date: str,
        to_date: str,
        interval: int = 5,
        unit: str = "minutes",
    ) -> pd.DataFrame:
        path = (
            "/historical-candle/"
            f"{self._encode_instrument_key(instrument_key)}/{unit}/{interval}/"
            f"{to_date}/{from_date}"
        )
        return self._request_candles(instrument_key, path)

    def get_intraday_candles(
        self,
        instrument_key: str,
        interval: int = 5,
        unit: str = "minutes",
    ) -> pd.DataFrame:
        path = (
            "/historical-candle/intraday/"
            f"{self._encode_instrument_key(instrument_key)}/{unit}/{interval}"
        )
        intraday = self._request_candles(instrument_key, path)
        if not intraday.empty:
            return intraday
        today = date.today()
        historical = self.get_historical_candles(
            instrument_key,
            from_date=(today - timedelta(days=10)).isoformat(),
            to_date=today.isoformat(),
            interval=interval,
            unit=unit,
        )
        if historical.empty:
            return self.empty_candles()
        trading_dates = historical["timestamp"].dt.date
        return historical.loc[trading_dates == trading_dates.max()].reset_index(drop=True)

    @staticmethod
    def _encode_instrument_key(instrument_key: str) -> str:
        return quote(unquote(str(instrument_key)), safe="")

    def _request_candles(self, instrument_key: str, path: str) -> pd.DataFrame:
        response = self.session.get(
            f"{self.BASE_URL_V3}{path}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        error_code = error_message = ""
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = {}
            error_message = "Malformed JSON response"

        if isinstance(payload, dict):
            error_code, parsed_message = self._parse_error(payload)
            error_message = parsed_message or error_message
            data = payload.get("data")
            candles = data.get("candles") if isinstance(data, dict) else None
        else:
            candles = None
            error_message = "Malformed response payload"

        frame = self.candles_to_dataframe(candles)
        safe_error_message = self._sanitize_log_text(
            error_message,
            secrets=(self.access_token,),
        )
        logger.info(
            "Upstox candles instrument_key=%s endpoint=%s http_status=%s "
            "error_code=%s error_message=%s candle_count=%d",
            instrument_key,
            path,
            response.status_code,
            error_code,
            safe_error_message,
            len(frame),
        )
        if response.status_code in (401, 403, 429):
            message = (
                "Upstox authentication failed."
                if response.status_code in (401, 403)
                else "Upstox rate limit reached."
            )
            error = UpstoxAPIError(message)
            error.status_code = response.status_code
            raise error
        return frame if response.ok else self.empty_candles()

    @staticmethod
    def _parse_error(payload: dict[str, Any]) -> tuple[str, str]:
        errors = payload.get("errors")
        error: dict[str, Any] = {}
        if isinstance(errors, dict):
            error = errors
        elif isinstance(errors, (list, tuple)) and errors and isinstance(errors[0], dict):
            error = errors[0]
        code = error.get("errorCode") or error.get("code") or payload.get("errorCode") or payload.get("code")
        message = error.get("message") or payload.get("message")
        return UpstoxClient._safe_text(code), UpstoxClient._safe_text(message)

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return ""

    @classmethod
    def _sanitize_log_text(
        cls,
        value: Any,
        *,
        secrets: tuple[str, ...] = (),
        maximum_length: int = 256,
    ) -> str:
        text = cls._safe_text(value)
        text = " ".join(text.split())
        text = re.sub(
            r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+",
            "Bearer [REDACTED]",
            text,
        )
        text = re.sub(
            r"(?i)\b(access[_ -]?token|authorization|api[_ -]?secret|cookie)\b\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            text,
        )
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        if len(text) > maximum_length:
            text = text[: maximum_length - 3].rstrip() + "..."
        return text

    @staticmethod
    def empty_candles() -> pd.DataFrame:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
        )

    @staticmethod
    def candles_to_dataframe(candles: Any) -> pd.DataFrame:
        rows = []
        if not isinstance(candles, list):
            return UpstoxClient.empty_candles()
        for candle in candles:
            if not isinstance(candle, (list, tuple)) or len(candle) < 6:
                continue
            rows.append(
                {
                    "timestamp": candle[0],
                    "open": candle[1],
                    "high": candle[2],
                    "low": candle[3],
                    "close": candle[4],
                    "volume": candle[5],
                    "oi": candle[6] if len(candle) > 6 else None,
                }
            )
        df = pd.DataFrame(rows)
        if df.empty:
            return UpstoxClient.empty_candles()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        numeric = ["open", "high", "low", "close", "volume", "oi"]
        df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
        if df.empty:
            return UpstoxClient.empty_candles()
        return df.sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def _optional_value(mapping: dict[str, Any], key: str) -> Any | None:
        raw = mapping.get(key)
        if raw is None:
            return None
        try:
            if pd.isna(raw):
                return None
        except (TypeError, ValueError):
            pass
        return raw

    @staticmethod
    def _optional_difference(left: Any | None, right: Any | None) -> float | None:
        if left is None or right is None:
            return None
        try:
            return float(left) - float(right)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def option_chain_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        value = UpstoxClient._optional_value
        difference = UpstoxClient._optional_difference
        for item in records:
            call = item.get("call_options") or {}
            put = item.get("put_options") or {}
            cmd = call.get("market_data") or {}
            pmd = put.get("market_data") or {}
            cg = call.get("option_greeks") or {}
            pg = put.get("option_greeks") or {}
            call_ltp = value(cmd, "ltp")
            put_ltp = value(pmd, "ltp")
            call_close = value(cmd, "close_price")
            put_close = value(pmd, "close_price")
            call_oi = value(cmd, "oi")
            put_oi = value(pmd, "oi")
            call_prev_oi = value(cmd, "prev_oi")
            put_prev_oi = value(pmd, "prev_oi")
            rows.append(
                {
                    "expiry": item.get("expiry"),
                    "spot": value(item, "underlying_spot_price"),
                    "strike": value(item, "strike_price"),
                    "strike_pcr": value(item, "pcr"),
                    "call_instrument_key": call.get("instrument_key", ""),
                    "call_ltp": call_ltp,
                    "call_close": call_close,
                    "call_price_change": difference(call_ltp, call_close),
                    "call_volume": value(cmd, "volume"),
                    "call_oi": call_oi,
                    "call_prev_oi": call_prev_oi,
                    "call_oi_change": difference(call_oi, call_prev_oi),
                    "call_bid": value(cmd, "bid_price"),
                    "call_bid_qty": value(cmd, "bid_qty"),
                    "call_ask": value(cmd, "ask_price"),
                    "call_ask_qty": value(cmd, "ask_qty"),
                    "call_iv": value(cg, "iv"),
                    "call_delta": value(cg, "delta"),
                    "call_gamma": value(cg, "gamma"),
                    "call_theta": value(cg, "theta"),
                    "call_vega": value(cg, "vega"),
                    "call_pop": value(cg, "pop"),
                    "put_instrument_key": put.get("instrument_key", ""),
                    "put_ltp": put_ltp,
                    "put_close": put_close,
                    "put_price_change": difference(put_ltp, put_close),
                    "put_volume": value(pmd, "volume"),
                    "put_oi": put_oi,
                    "put_prev_oi": put_prev_oi,
                    "put_oi_change": difference(put_oi, put_prev_oi),
                    "put_bid": value(pmd, "bid_price"),
                    "put_bid_qty": value(pmd, "bid_qty"),
                    "put_ask": value(pmd, "ask_price"),
                    "put_ask_qty": value(pmd, "ask_qty"),
                    "put_iv": value(pg, "iv"),
                    "put_delta": value(pg, "delta"),
                    "put_gamma": value(pg, "gamma"),
                    "put_theta": value(pg, "theta"),
                    "put_vega": value(pg, "vega"),
                    "put_pop": value(pg, "pop"),
                }
            )
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        text_columns = {"expiry", "call_instrument_key", "put_instrument_key"}
        numeric = [column for column in frame.columns if column not in text_columns]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        return frame.sort_values("strike", na_position="last").reset_index(drop=True)


__all__ = ["ObservableRetry", "UpstoxAPIError", "UpstoxClient"]
