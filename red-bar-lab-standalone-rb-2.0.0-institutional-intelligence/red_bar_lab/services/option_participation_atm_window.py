from __future__ import annotations

from datetime import datetime
from statistics import median

import pandas as pd

from red_bar_lab.services.option_participation import (
    OptionParticipationSummary,
    _f,
    _intraday_metrics,
    _rsi14,
    build_option_participation_summary,
)


def detect_atm_strike_window(
    *,
    spot_price: float,
    available_strikes: list[float],
    steps_each_side: int = 4,
) -> tuple[float, float | None, tuple[float, ...]]:
    """Return nearest ATM, detected interval and available ATM ± N strikes.

    The interval is derived from the point-in-time option-chain strikes. The
    returned window is bounded by the strikes actually available in the chain;
    no synthetic or hard-coded strike is created.
    """
    strikes = sorted({float(value) for value in available_strikes})
    if not strikes:
        raise ValueError("available_strikes must contain at least one strike")

    atm_index = min(
        range(len(strikes)),
        key=lambda index: (abs(strikes[index] - float(spot_price)), strikes[index]),
    )
    atm = strikes[atm_index]
    differences = [
        right - left
        for left, right in zip(strikes, strikes[1:])
        if right > left
    ]
    strike_interval = float(median(differences)) if differences else None
    start = max(0, atm_index - max(0, int(steps_each_side)))
    stop = min(len(strikes), atm_index + max(0, int(steps_each_side)) + 1)
    return atm, strike_interval, tuple(strikes[start:stop])


def _moneyness(option_type: str, strike: float, atm: float) -> str:
    if strike == atm:
        return "ATM"
    if option_type == "CE":
        return "ITM" if strike < atm else "OTM"
    return "ITM" if strike > atm else "OTM"


def capture_option_participation_atm_window(
    *,
    intelligence,
    adapter,
    underlying_name: str,
    underlying_key: str,
    observed_at: datetime,
    steps_each_side: int = 4,
) -> OptionParticipationSummary:
    """Capture the same point-in-time ATM ± N strikes for CE and PE.

    With the default N=4, nine strike levels are collected for CE and the same
    nine strike levels for PE, producing up to eighteen option observations.
    This function is read-only and has no execution authority.
    """
    snapshot = intelligence.snapshot(underlying_key=underlying_key, force=True)
    spot = _f(snapshot.spot_price)
    if spot is None or snapshot.chain.empty:
        return build_option_participation_summary(
            observed_at=observed_at,
            underlying_name=underlying_name,
            spot_price=spot,
            expiry=snapshot.expiry,
            pcr_oi=snapshot.pcr_oi,
            underlying_rsi=None,
            rows=(),
        )

    chain = snapshot.chain.copy()
    chain["strike"] = pd.to_numeric(chain["strike"], errors="coerce")
    valid_strikes = [float(value) for value in chain["strike"].dropna().unique()]
    atm, strike_interval, selected_strikes = detect_atm_strike_window(
        spot_price=spot,
        available_strikes=valid_strikes,
        steps_each_side=steps_each_side,
    )
    # Rank by proximity to ATM so rank 1 is ATM, then ±1, ±2, and so on.
    ranked_strikes = sorted(selected_strikes, key=lambda strike: (abs(strike - atm), strike))

    contracts = adapter.nfo_options(underlying_name=underlying_name)
    contract_by_key: dict[str, dict[str, object]] = {}
    if not contracts.empty and "instrument_key" in contracts.columns:
        for _, contract in contracts.iterrows():
            contract_by_key[str(contract.get("instrument_key"))] = dict(contract)

    underlying_rsi = None
    try:
        underlying_frame = intelligence.provider.intraday_candles(
            underlying_key,
            interval_minutes=5,
        )
        underlying_rsi = _rsi14(underlying_frame)
    except Exception:
        underlying_rsi = None

    rows: list[dict[str, object]] = []
    for option_type, prefix in (("CE", "call"), ("PE", "put")):
        for distance_rank, strike in enumerate(ranked_strikes, start=1):
            match = chain[chain["strike"] == strike]
            if match.empty:
                continue
            chain_row = match.iloc[0]
            instrument_key = str(chain_row.get(f"{prefix}_instrument_key") or "")
            contract = contract_by_key.get(instrument_key, {})
            token = contract.get("instrument_token")
            ltp = _f(chain_row.get(f"{prefix}_ltp"))
            candle_metrics = {
                "vwap": None,
                "option_rsi": None,
                "premium_change_pct": None,
            }
            if token not in (None, ""):
                try:
                    candles = adapter.historical_candles(
                        instrument_token=int(token),
                        interval="minute",
                        date_from=observed_at.date().isoformat(),
                        date_to=observed_at.date().isoformat(),
                        include_oi=True,
                    )
                    candle_metrics = _intraday_metrics(candles, ltp)
                except Exception:
                    pass

            oi = _f(chain_row.get(f"{prefix}_oi"))
            prev_oi = _f(chain_row.get(f"{prefix}_prev_oi"))
            oi_change = _f(chain_row.get(f"{prefix}_oi_change"))
            if oi_change is None and oi is not None and prev_oi is not None:
                oi_change = oi - prev_oi
            oi_change_pct = (
                round(oi_change / prev_oi * 100.0, 4)
                if oi_change is not None and prev_oi not in (None, 0)
                else None
            )
            volume = _f(chain_row.get(f"{prefix}_volume"))
            lot_size = int(_f(contract.get("lot_size")) or 0) or None
            contract_volume = (
                round(volume / lot_size, 2)
                if volume is not None and lot_size not in (None, 0)
                else None
            )
            bid = _f(chain_row.get(f"{prefix}_bid"))
            ask = _f(chain_row.get(f"{prefix}_ask"))
            spread = (
                ask - bid
                if ask is not None and bid is not None and ask >= bid
                else None
            )
            strike_offset_steps = (
                int(round((strike - atm) / strike_interval))
                if strike_interval not in (None, 0)
                else 0
            )
            rows.append({
                "distance_rank": distance_rank,
                "strike_interval": strike_interval,
                "strike_offset_steps": strike_offset_steps,
                "moneyness": _moneyness(option_type, strike, atm),
                "instrument_key": instrument_key or None,
                "instrument_token": int(token) if token not in (None, "") else None,
                "tradingsymbol": str(
                    contract.get("tradingsymbol")
                    or instrument_key
                    or f"{strike:g} {option_type}"
                ),
                "option_type": option_type,
                "strike": strike,
                "expiry": str(snapshot.expiry),
                "lot_size": lot_size,
                "current_price": ltp,
                "vwap": candle_metrics["vwap"],
                "premium_change_pct": candle_metrics["premium_change_pct"],
                "volume": volume,
                "contract_volume": contract_volume,
                "oi": oi,
                "prev_oi": prev_oi,
                "oi_change": oi_change,
                "oi_change_pct": oi_change_pct,
                "delta": _f(chain_row.get(f"{prefix}_delta")),
                "iv": _f(chain_row.get(f"{prefix}_iv")),
                "option_rsi": candle_metrics["option_rsi"],
                "underlying_rsi": underlying_rsi,
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "pcr_oi": _f(snapshot.pcr_oi),
            })

    return build_option_participation_summary(
        observed_at=observed_at,
        underlying_name=underlying_name,
        spot_price=spot,
        expiry=str(snapshot.expiry),
        pcr_oi=snapshot.pcr_oi,
        underlying_rsi=underlying_rsi,
        rows=rows,
    )
