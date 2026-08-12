from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class UpstoxMarketSnapshot:
    underlying_key: str
    expiry: str
    captured_at: str
    spot_price: float | None
    pcr_oi: float | None
    call_wall: float | None
    put_wall: float | None
    max_pain: float | None
    chain: pd.DataFrame


def _f(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_pain(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    work = frame.copy()
    for col in ("strike", "call_oi", "put_oi"):
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
    strikes = work["strike"].dropna().tolist()
    if not strikes:
        return None

    best_strike = None
    best_pain = None
    for settlement in strikes:
        call_pain = (
            (float(settlement) - work["strike"]).clip(lower=0.0)
            * work["call_oi"]
        ).sum()
        put_pain = (
            (work["strike"] - float(settlement)).clip(lower=0.0)
            * work["put_oi"]
        ).sum()
        total = float(call_pain + put_pain)
        if best_pain is None or total < best_pain:
            best_pain = total
            best_strike = float(settlement)
    return best_strike


class UnifiedUpstoxMarketIntelligenceService:
    """Single shared Upstox view for options, paper trading and future AI."""

    def __init__(
        self,
        provider,
        *,
        cache_ttl_seconds: float = 2.0,
    ):
        self.provider = provider
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self._snapshot_cache: dict[
            tuple[str, str], tuple[float, UpstoxMarketSnapshot]
        ] = {}
        self._contracts_cache: dict[
            tuple[str, str | None], tuple[float, pd.DataFrame]
        ] = {}

    def option_contracts(
        self,
        *,
        underlying_key: str,
        expiry: str | None = None,
        max_age_seconds: float = 300.0,
    ) -> pd.DataFrame:
        cache_key = (underlying_key, expiry)
        cached = self._contracts_cache.get(cache_key)
        now_mono = monotonic()
        if cached and now_mono - cached[0] <= float(max_age_seconds):
            return cached[1].copy()

        records = self.provider.option_contracts(
            underlying_key,
            expiry,
        )
        frame = pd.DataFrame(records)
        if frame.empty:
            return frame

        rename = {
            "exchange_token": "instrument_token",
            "trading_symbol": "tradingsymbol",
            "strike_price": "strike",
        }
        frame = frame.rename(columns=rename)
        if "expiry" in frame.columns:
            frame["expiry"] = pd.to_datetime(
                frame["expiry"], errors="coerce"
            ).dt.date
        if "instrument_token" in frame.columns:
            frame["instrument_token"] = pd.to_numeric(
                frame["instrument_token"], errors="coerce"
            ).astype("Int64")
        for col in ("strike", "lot_size"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(
                    frame[col], errors="coerce"
                )
        frame["exchange"] = "UPSTOX"
        self._contracts_cache[cache_key] = (now_mono, frame.copy())
        return frame

    def snapshot(
        self,
        *,
        underlying_key: str,
        expiry: str | None = None,
        force: bool = False,
    ) -> UpstoxMarketSnapshot:
        if not expiry:
            expiries = self.provider.option_expiries(underlying_key)
            if not expiries:
                raise RuntimeError(
                    f"No Upstox option expiry returned for {underlying_key}."
                )
            expiry = str(expiries[0])

        cache_key = (underlying_key, expiry)
        cached = self._snapshot_cache.get(cache_key)
        now_mono = monotonic()
        if (
            not force
            and cached
            and now_mono - cached[0] <= self.cache_ttl_seconds
        ):
            return cached[1]

        records = self.provider.option_chain(
            underlying_key,
            expiry,
        )
        frame = self.provider.option_chain_dataframe(records)
        if frame.empty:
            raise RuntimeError(
                f"Upstox returned an empty option chain for {expiry}."
            )

        call_oi = pd.to_numeric(
            frame["call_oi"], errors="coerce"
        ).fillna(0.0)
        put_oi = pd.to_numeric(
            frame["put_oi"], errors="coerce"
        ).fillna(0.0)
        total_call = float(call_oi.sum())
        total_put = float(put_oi.sum())
        pcr = total_put / total_call if total_call > 0 else None

        call_wall = (
            float(frame.loc[call_oi.idxmax(), "strike"])
            if total_call > 0 else None
        )
        put_wall = (
            float(frame.loc[put_oi.idxmax(), "strike"])
            if total_put > 0 else None
        )
        spot = _f(frame.iloc[0].get("spot"))

        snapshot = UpstoxMarketSnapshot(
            underlying_key=underlying_key,
            expiry=expiry,
            captured_at=datetime.now(IST).isoformat(),
            spot_price=spot,
            pcr_oi=pcr,
            call_wall=call_wall,
            put_wall=put_wall,
            max_pain=_max_pain(frame),
            chain=frame.copy(),
        )
        self._snapshot_cache[cache_key] = (now_mono, snapshot)
        return snapshot

    def nearby_options(
        self,
        *,
        underlying_key: str,
        direction: str,
        strike_count_each_side: int = 2,
        expiry: str | None = None,
    ) -> pd.DataFrame:
        snap = self.snapshot(
            underlying_key=underlying_key,
            expiry=expiry,
        )
        frame = snap.chain.copy()
        option_type = (
            "CE" if str(direction).upper() == "BULLISH" else "PE"
        )
        prefix = "call" if option_type == "CE" else "put"

        frame["distance"] = (
            pd.to_numeric(frame["strike"], errors="coerce")
            - float(snap.spot_price or 0.0)
        ).abs()
        selected = frame.sort_values(
            ["distance", "strike"]
        ).head(1 + 2 * int(strike_count_each_side))

        out = pd.DataFrame({
            "instrument_key": selected[f"{prefix}_instrument_key"],
            "option_type": option_type,
            "strike": selected["strike"],
            "expiry": selected["expiry"],
            "ltp": selected[f"{prefix}_ltp"],
            "volume": selected[f"{prefix}_volume"],
            "oi": selected[f"{prefix}_oi"],
            "prev_oi": selected[f"{prefix}_prev_oi"],
            "oi_change": selected[f"{prefix}_oi_change"],
            "best_bid": selected[f"{prefix}_bid"],
            "best_bid_qty": selected[f"{prefix}_bid_qty"],
            "best_ask": selected[f"{prefix}_ask"],
            "best_ask_qty": selected[f"{prefix}_ask_qty"],
            "iv": selected[f"{prefix}_iv"],
            "delta": selected[f"{prefix}_delta"],
            "gamma": selected[f"{prefix}_gamma"],
            "theta": selected[f"{prefix}_theta"],
            "vega": selected[f"{prefix}_vega"],
            "pop": selected[f"{prefix}_pop"],
        })
        return out.reset_index(drop=True)
