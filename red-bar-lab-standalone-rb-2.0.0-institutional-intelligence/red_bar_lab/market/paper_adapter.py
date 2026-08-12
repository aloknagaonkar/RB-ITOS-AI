from __future__ import annotations

from datetime import date
from time import monotonic
import pandas as pd


class UpstoxPaperMarketAdapter:
    provider_name = "UPSTOX"
    """Compatibility adapter for the existing Red Bar paper engine.

    It exposes the same read-only shape used by the current paper engine while
    sourcing every quote/candle from Upstox.
    """

    def __init__(self, intelligence, underlying_name: str, underlying_key: str):
        self.intelligence = intelligence
        self.provider = intelligence.provider
        self.underlying_name = underlying_name
        self.underlying_key = underlying_key
        self._token_to_key: dict[int, str] = {}
        self._symbol_to_key: dict[str, str] = {}
        self._candle_cache: dict[
            tuple[int, str, str, str],
            tuple[float, object],
        ] = {}
        self.candle_cache_ttl_seconds = 15.0

    def nfo_options(self, underlying_name: str, as_of=None) -> pd.DataFrame:
        frame = self.intelligence.option_contracts(
            underlying_key=self.underlying_key
        ).copy()
        if frame.empty:
            return frame

        frame["name"] = (
            "NIFTY"
            if underlying_name == "NIFTY 50"
            else "BANKNIFTY"
        )
        frame["instrument_type"] = frame["instrument_type"].astype(str)
        for _, row in frame.iterrows():
            try:
                token = int(row["instrument_token"])
                key = str(row["instrument_key"])
                symbol = str(row["tradingsymbol"])
            except Exception:
                continue
            self._token_to_key[token] = key
            self._symbol_to_key[symbol] = key
        return frame

    def ltp(self, instruments: list[str]) -> dict[str, float]:
        snap = self.intelligence.snapshot(
            underlying_key=self.underlying_key
        )
        result = {}
        for item in instruments:
            text = str(item)
            if text in {
                "NSE:NIFTY 50",
                "NSE:NIFTY BANK",
                self.underlying_key,
            }:
                if snap.spot_price is not None:
                    result[text] = float(snap.spot_price)
        return result

    def quote(self, instruments: list[str]) -> dict[str, object]:
        snap = self.intelligence.snapshot(
            underlying_key=self.underlying_key
        )
        frame = snap.chain
        result = {}

        for requested in instruments:
            symbol = str(requested).split(":", 1)[-1]
            instrument_key = self._symbol_to_key.get(symbol, symbol)

            match = None
            side = None
            call_match = frame[
                frame["call_instrument_key"].astype(str) == instrument_key
            ]
            if not call_match.empty:
                match = call_match.iloc[0]
                side = "call"
            else:
                put_match = frame[
                    frame["put_instrument_key"].astype(str) == instrument_key
                ]
                if not put_match.empty:
                    match = put_match.iloc[0]
                    side = "put"

            if match is None:
                continue

            bid = float(match.get(f"{side}_bid") or 0.0)
            ask = float(match.get(f"{side}_ask") or 0.0)
            bid_qty = int(match.get(f"{side}_bid_qty") or 0)
            ask_qty = int(match.get(f"{side}_ask_qty") or 0)

            result[str(requested)] = {
                "last_price": float(match.get(f"{side}_ltp") or 0.0),
                "volume": float(match.get(f"{side}_volume") or 0.0),
                "oi": float(match.get(f"{side}_oi") or 0.0),
                "buy_quantity": bid_qty,
                "sell_quantity": ask_qty,
                "iv": float(match.get(f"{side}_iv") or 0.0),
                "delta": float(match.get(f"{side}_delta") or 0.0),
                "gamma": float(match.get(f"{side}_gamma") or 0.0),
                "theta": float(match.get(f"{side}_theta") or 0.0),
                "vega": float(match.get(f"{side}_vega") or 0.0),
                "depth": {
                    "buy": [{"price": bid, "quantity": bid_qty}] if bid > 0 else [],
                    "sell": [{"price": ask, "quantity": ask_qty}] if ask > 0 else [],
                },
            }
        return result

    def historical_candles(
        self,
        instrument_token: int,
        interval: str,
        date_from,
        date_to,
        include_oi: bool = True,
    ):
        cache_key = (
            int(instrument_token),
            str(interval),
            str(date_from),
            str(date_to),
        )
        now_mono = monotonic()
        cached = self._candle_cache.get(cache_key)
        if (
            cached
            and now_mono - cached[0] <= self.candle_cache_ttl_seconds
        ):
            # The paper engine treats candle payloads as read-only.
            return cached[1]

        instrument_key = self._token_to_key.get(int(instrument_token))
        if not instrument_key:
            contracts = self.nfo_options(self.underlying_name)
            instrument_key = self._token_to_key.get(int(instrument_token))
        if not instrument_key:
            raise ValueError(
                f"Unknown Upstox instrument token {instrument_token}."
            )

        if str(date_from) == str(date_to) == date.today().isoformat():
            result = self.provider.intraday_candles(
                instrument_key,
                interval_minutes=1,
            )
        else:
            result = self.provider.historical_candles(
                instrument_key,
                date.fromisoformat(str(date_from)),
                date.fromisoformat(str(date_to)),
                interval_minutes=1,
            )
        self._candle_cache[cache_key] = (now_mono, result)
        return result
