from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from .domain import IST
from .historical_replay_data_v1 import (
    futures_cache_path,
    option_cache_path,
)
from .live_option_minute_source_v1 import CompletedOptionMinute


@dataclass(frozen=True)
class HistoricalFuturesOIResultV1:
    state: str | None
    price_change: float | None
    oi_change: float | None
    health_state: str
    health_allowed: bool
    health_reason: str | None


def _dt(value: str | datetime) -> datetime:
    out = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return out.astimezone(IST)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text())


def _futures_state(price_change: float, oi_change: float) -> str | None:
    if price_change > 0 and oi_change > 0:
        return "LONG_BUILDUP"
    if price_change < 0 and oi_change > 0:
        return "SHORT_BUILDUP"
    if price_change > 0 and oi_change < 0:
        return "SHORT_COVERING"
    if price_change < 0 and oi_change < 0:
        return "LONG_UNWINDING"
    return None


class HistoricalReplayMarketSourcesV1:
    """
    Adapter matching the two methods used by LiveShadowProductionCoordinatorV1:
      - futures_oi_at_checkpoint(checkpoint)
      - option_intraday_1m(instrument_key)

    It reads only replay-cache data and downloads an exact option instrument
    on demand when absent. It never substitutes a nearest strike.
    """

    def __init__(
        self,
        session_date: date,
        *,
        cache_root: str | Path = "data/live-observation/replay-cache",
    ):
        self.session_date = session_date
        self.cache_root = Path(cache_root)
        self._futures = self._load_futures()
        self._options: dict[str, list[CompletedOptionMinute]] = {}

    def _load_futures(self) -> list[dict[str, Any]]:
        payload = _load_json(futures_cache_path(self.session_date, self.cache_root))
        rows = list(payload.get("candles") or [])
        if not rows:
            raise RuntimeError(
                f"No cached NIFTY futures candles for {self.session_date}"
            )
        rows.sort(key=lambda row: _dt(row["timestamp"]))
        return rows

    def futures_oi_at_checkpoint(
        self,
        checkpoint: datetime,
    ) -> HistoricalFuturesOIResultV1:
        checkpoint = checkpoint.astimezone(IST)

        # Causal completed 5m windows:
        # current  [T-5m, T)
        # previous [T-10m, T-5m)
        current_start = checkpoint - timedelta(minutes=5)
        previous_start = checkpoint - timedelta(minutes=10)

        current = [
            row for row in self._futures
            if current_start <= _dt(row["timestamp"]) < checkpoint
        ]
        previous = [
            row for row in self._futures
            if previous_start <= _dt(row["timestamp"]) < current_start
        ]

        if len(current) != 5 or len(previous) != 5:
            return HistoricalFuturesOIResultV1(
                state=None,
                price_change=None,
                oi_change=None,
                health_state="INCOMPLETE",
                health_allowed=False,
                health_reason=(
                    "STRICT_5M_CONTINUITY_FAILED:"
                    f"previous={len(previous)},current={len(current)}"
                ),
            )

        # Verify exact 1m continuity, not merely row count.
        expected_current = [
            current_start + timedelta(minutes=i) for i in range(5)
        ]
        expected_previous = [
            previous_start + timedelta(minutes=i) for i in range(5)
        ]
        if [_dt(x["timestamp"]) for x in current] != expected_current:
            return HistoricalFuturesOIResultV1(
                None, None, None, "INCOMPLETE", False,
                "CURRENT_5M_MINUTE_TIMESTAMPS_NOT_EXACT",
            )
        if [_dt(x["timestamp"]) for x in previous] != expected_previous:
            return HistoricalFuturesOIResultV1(
                None, None, None, "INCOMPLETE", False,
                "PREVIOUS_5M_MINUTE_TIMESTAMPS_NOT_EXACT",
            )

        previous_close = float(previous[-1]["close"])
        current_close = float(current[-1]["close"])
        previous_oi = previous[-1].get("open_interest")
        current_oi = current[-1].get("open_interest")

        if previous_oi is None or current_oi is None:
            return HistoricalFuturesOIResultV1(
                None, None, None, "INCOMPLETE", False,
                "FUTURES_OI_MISSING",
            )

        price_change = current_close - previous_close
        oi_change = float(current_oi) - float(previous_oi)
        state = _futures_state(price_change, oi_change)

        if state is None:
            return HistoricalFuturesOIResultV1(
                state=None,
                price_change=price_change,
                oi_change=oi_change,
                health_state="DEGRADED",
                health_allowed=True,
                health_reason="ZERO_PRICE_OR_OI_DELTA",
            )

        return HistoricalFuturesOIResultV1(
            state=state,
            price_change=price_change,
            oi_change=oi_change,
            health_state="HEALTHY",
            health_allowed=True,
            health_reason=None,
        )

    def _fetch_exact_option(self, instrument_key: str) -> list[dict[str, Any]]:
        """
        Fetch exactly the selected instrument. Resolution order:
          1. expired-option endpoint through UpstoxGateway
          2. current historical V3 endpoint
          3. same-day current intraday V3 endpoint

        No nearest-strike/instrument fallback.
        """
        load_dotenv(".env")
        token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not token:
            raise RuntimeError("UPSTOX_ACCESS_TOKEN is not set")

        # First reuse the existing gateway's expired option support.
        try:
            from .gateways import UpstoxGateway
            gateway = UpstoxGateway(token)
            candles = gateway.historical_option_candles(
                instrument_key,
                self.session_date,
            )
            if candles:
                return [
                    {
                        "timestamp": c.timestamp.isoformat(),
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in candles
                ]
        except Exception:
            pass

        # Current/non-expired instrument fallback.
        import httpx

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        encoded = quote(instrument_key, safe="")
        session = self.session_date.isoformat()

        with httpx.Client(
            base_url="https://api.upstox.com",
            timeout=30,
            headers=headers,
        ) as client:
            paths = [
                f"/v3/historical-candle/{encoded}/minutes/1/{session}/{session}",
            ]
            if self.session_date == datetime.now(IST).date():
                paths.append(
                    f"/v3/historical-candle/intraday/{encoded}/minutes/1"
                )

            errors = []
            for path in paths:
                try:
                    response = client.get(path)
                    response.raise_for_status()
                    raw = (
                        response.json()
                        .get("data", {})
                        .get("candles", [])
                    )
                    if raw:
                        rows = []
                        for value in raw:
                            if not isinstance(value, list) or len(value) < 5:
                                continue
                            rows.append({
                                "timestamp": value[0],
                                "open": float(value[1]),
                                "high": float(value[2]),
                                "low": float(value[3]),
                                "close": float(value[4]),
                                "volume": (
                                    float(value[5])
                                    if len(value) >= 6 and value[5] is not None
                                    else None
                                ),
                            })
                        rows.sort(key=lambda row: _dt(row["timestamp"]))
                        if rows:
                            return rows
                except Exception as exc:
                    errors.append(f"{path}: {type(exc).__name__}: {exc}")

        raise RuntimeError(
            "Exact option 1m data unavailable for "
            f"{self.session_date} {instrument_key}; "
            + " | ".join(errors)
        )

    def _load_or_download_option(
        self,
        instrument_key: str,
    ) -> list[CompletedOptionMinute]:
        if instrument_key in self._options:
            return self._options[instrument_key]

        path = option_cache_path(
            self.session_date,
            instrument_key,
            self.cache_root,
        )
        rows: list[dict[str, Any]] = []

        if path.exists():
            payload = _load_json(path)
            rows = list(payload.get("candles") or [])

        if not rows:
            rows = self._fetch_exact_option(instrument_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "model": "HISTORICAL_REPLAY_ENGINE_V1",
                "session_date": self.session_date.isoformat(),
                "instrument_key": instrument_key,
                "candles": rows,
            }, indent=2, default=str))

        bars = [
            CompletedOptionMinute(
                instrument_key=instrument_key,
                timestamp=_dt(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=(
                    float(row["volume"])
                    if row.get("volume") is not None
                    else None
                ),
            )
            for row in rows
            if _dt(row["timestamp"]).date() == self.session_date
        ]
        bars.sort(key=lambda bar: bar.timestamp)

        if not bars:
            raise RuntimeError(
                f"No exact option 1m bars for {instrument_key} "
                f"on {self.session_date}"
            )

        self._options[instrument_key] = bars
        return bars

    def option_intraday_1m(
        self,
        instrument_key: str,
    ) -> list[CompletedOptionMinute]:
        return list(self._load_or_download_option(instrument_key))
