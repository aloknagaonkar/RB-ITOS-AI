from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

import pandas as pd


@dataclass(frozen=True)
class OptionParticipationSummary:
    observed_at: str
    underlying_name: str
    spot_price: float | None
    atm_strike: float | None
    expiry: str | None
    pcr_oi: float | None
    underlying_rsi: float | None
    ce_score: float
    pe_score: float
    recommended_side: str
    recommended_direction: str
    grade: str
    reason: str
    rows: tuple[dict[str, object], ...]
    authority: str = "OBSERVATIONAL_ONLY"


def _f(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rsi14(frame: pd.DataFrame | None) -> float | None:
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    last_gain = _f(avg_gain.iloc[-1])
    last_loss = _f(avg_loss.iloc[-1])
    if last_gain is None or last_loss is None:
        return None
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    rs = last_gain / last_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _intraday_metrics(frame: pd.DataFrame | None, fallback_ltp: float | None) -> dict[str, float | None]:
    if frame is None or frame.empty:
        return {"vwap": None, "option_rsi": None, "premium_change_pct": None}
    work = frame.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    timestamp_col = next((name for name in ("timestamp", "date", "datetime", "time") if name in work.columns), None)
    if timestamp_col:
        order = pd.to_datetime(work[timestamp_col], errors="coerce")
        work = work.assign(_order=order).sort_values("_order").drop(columns=["_order"])
    close = work["close"].dropna() if "close" in work.columns else pd.Series(dtype=float)
    if close.empty:
        return {"vwap": None, "option_rsi": None, "premium_change_pct": None}
    high = work["high"] if "high" in work.columns else work["close"]
    low = work["low"] if "low" in work.columns else work["close"]
    typical = (high + low + work["close"]) / 3.0
    volume = work["volume"].fillna(0.0) if "volume" in work.columns else pd.Series(0.0, index=work.index)
    cumulative_volume = volume.cumsum()
    vwap_series = (typical * volume).cumsum() / cumulative_volume.where(cumulative_volume != 0)
    vwap = _f(vwap_series.iloc[-1]) if not vwap_series.empty else None
    first_price = None
    if "open" in work.columns:
        valid_open = work["open"].dropna()
        if not valid_open.empty:
            first_price = _f(valid_open.iloc[0])
    if first_price is None:
        first_price = _f(close.iloc[0])
    current = fallback_ltp if fallback_ltp not in (None, 0) else _f(close.iloc[-1])
    premium_change_pct = (
        ((float(current) - float(first_price)) / float(first_price)) * 100.0
        if current is not None and first_price not in (None, 0)
        else None
    )
    return {
        "vwap": round(vwap, 4) if vwap is not None else None,
        "option_rsi": _rsi14(work),
        "premium_change_pct": round(premium_change_pct, 4) if premium_change_pct is not None else None,
    }


def _participation_state(premium_change_pct: float | None, oi_change: float | None) -> str:
    if premium_change_pct is None or oi_change is None:
        return "INSUFFICIENT"
    if premium_change_pct > 0 and oi_change > 0:
        return "FRESH_BUYING"
    if premium_change_pct < 0 and oi_change > 0:
        return "WRITING_PRESSURE"
    if premium_change_pct > 0 and oi_change < 0:
        return "SHORT_COVERING"
    if premium_change_pct < 0 and oi_change < 0:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def _score_strike(
    *,
    state: str,
    current_price: float | None,
    vwap: float | None,
    volume: float | None,
    max_side_volume: float,
    oi_change: float | None,
    option_rsi: float | None,
    delta: float | None,
) -> float:
    directional = {
        "FRESH_BUYING": 30.0,
        "SHORT_COVERING": 22.0,
        "NEUTRAL": 10.0,
        "INSUFFICIENT": 5.0,
        "WRITING_PRESSURE": 0.0,
        "LONG_UNWINDING": 0.0,
    }.get(state, 0.0)
    vwap_score = 0.0
    if current_price is not None and vwap not in (None, 0):
        vwap_score = 20.0 if current_price >= float(vwap) else 0.0
    volume_score = 0.0
    if volume is not None and max_side_volume > 0:
        volume_score = min(15.0, max(0.0, float(volume) / max_side_volume * 15.0))
    oi_score = 0.0
    if oi_change is not None:
        if state == "FRESH_BUYING":
            oi_score = 15.0
        elif state == "SHORT_COVERING":
            oi_score = 10.0
        elif oi_change == 0:
            oi_score = 5.0
    rsi_score = 0.0
    if option_rsi is not None:
        if 55.0 <= option_rsi <= 70.0:
            rsi_score = 10.0
        elif 50.0 <= option_rsi < 55.0:
            rsi_score = 7.0
        elif 70.0 < option_rsi <= 75.0:
            rsi_score = 6.0
        elif 45.0 <= option_rsi < 50.0:
            rsi_score = 4.0
        elif option_rsi > 75.0:
            rsi_score = 2.0
    delta_score = 0.0
    if delta is not None:
        abs_delta = abs(float(delta))
        if 0.40 <= abs_delta <= 0.65:
            delta_score = 10.0
        elif 0.30 <= abs_delta < 0.40 or 0.65 < abs_delta <= 0.75:
            delta_score = 7.0
        elif 0.20 <= abs_delta < 0.30:
            delta_score = 4.0
    return round(directional + vwap_score + volume_score + oi_score + rsi_score + delta_score, 2)


def _weighted_side_score(rows: Iterable[Mapping[str, object]]) -> float:
    items = list(rows)
    if not items:
        return 0.0
    weights = [max(0.0, _f(item.get("volume")) or 0.0) for item in items]
    if sum(weights) <= 0:
        return round(sum(_f(item.get("strike_score")) or 0.0 for item in items) / len(items), 2)
    return round(
        sum((_f(item.get("strike_score")) or 0.0) * weight for item, weight in zip(items, weights)) / sum(weights),
        2,
    )


def build_option_participation_summary(
    *,
    observed_at: datetime | str,
    underlying_name: str,
    spot_price: float | None,
    expiry: str | None,
    pcr_oi: float | None,
    underlying_rsi: float | None,
    rows: Iterable[Mapping[str, object]],
) -> OptionParticipationSummary:
    observed = observed_at.isoformat() if isinstance(observed_at, datetime) else str(observed_at)
    materialized = [dict(item) for item in rows]
    ce_rows = [item for item in materialized if str(item.get("option_type")).upper() == "CE"]
    pe_rows = [item for item in materialized if str(item.get("option_type")).upper() == "PE"]
    for side_rows in (ce_rows, pe_rows):
        max_volume = max((_f(item.get("volume")) or 0.0 for item in side_rows), default=0.0)
        for item in side_rows:
            current = _f(item.get("current_price"))
            vwap = _f(item.get("vwap"))
            item["price_vs_vwap_pct"] = (
                round((current - vwap) / vwap * 100.0, 4)
                if current is not None and vwap not in (None, 0)
                else None
            )
            item["participation_state"] = _participation_state(
                _f(item.get("premium_change_pct")), _f(item.get("oi_change"))
            )
            item["strike_score"] = _score_strike(
                state=str(item["participation_state"]),
                current_price=current,
                vwap=vwap,
                volume=_f(item.get("volume")),
                max_side_volume=max_volume,
                oi_change=_f(item.get("oi_change")),
                option_rsi=_f(item.get("option_rsi")),
                delta=_f(item.get("delta")),
            )
    ordered = ce_rows + pe_rows
    ce_score = _weighted_side_score(ce_rows)
    pe_score = _weighted_side_score(pe_rows)
    gap = abs(ce_score - pe_score)
    best = max(ce_score, pe_score)
    if best < 50.0 or gap < 8.0:
        side, direction = "WAIT", "NEUTRAL"
    elif ce_score > pe_score:
        side, direction = "CE", "BULLISH"
    else:
        side, direction = "PE", "BEARISH"
    if side == "WAIT":
        grade = "CONFLICTED" if best >= 50.0 else "NO_TRADE"
        reason = f"CE score {ce_score:.1f} vs PE score {pe_score:.1f}; separation is insufficient."
    elif best >= 80.0:
        grade = "STRONG"
        reason = f"{side} participation dominates with score {best:.1f} and {gap:.1f}-point separation."
    elif best >= 65.0:
        grade = "MODERATE"
        reason = f"{side} participation leads with score {best:.1f}."
    else:
        grade = "CAUTIOUS"
        reason = f"{side} participation leads, but score {best:.1f} needs confirmation."
    atm = None
    strikes = sorted({_f(item.get("strike")) for item in ordered if _f(item.get("strike")) is not None})
    if spot_price is not None and strikes:
        atm = min(strikes, key=lambda strike: abs(float(strike) - float(spot_price)))
    return OptionParticipationSummary(
        observed_at=observed,
        underlying_name=underlying_name,
        spot_price=_f(spot_price),
        atm_strike=atm,
        expiry=expiry,
        pcr_oi=_f(pcr_oi),
        underlying_rsi=_f(underlying_rsi),
        ce_score=ce_score,
        pe_score=pe_score,
        recommended_side=side,
        recommended_direction=direction,
        grade=grade,
        reason=reason,
        rows=tuple(ordered),
    )


def capture_option_participation(
    *,
    intelligence,
    adapter,
    underlying_name: str,
    underlying_key: str,
    observed_at: datetime,
) -> OptionParticipationSummary:
    """Capture ATM + two OTM CE and ATM + two OTM PE strikes, read-only."""
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
    valid_strikes = sorted(float(value) for value in chain["strike"].dropna().unique())
    atm = min(valid_strikes, key=lambda strike: abs(strike - spot))
    ce_strikes = [strike for strike in valid_strikes if strike >= atm][:3]
    pe_strikes = [strike for strike in reversed(valid_strikes) if strike <= atm][:3]

    contracts = adapter.nfo_options(underlying_name=underlying_name)
    contract_by_key: dict[str, dict[str, object]] = {}
    if not contracts.empty and "instrument_key" in contracts.columns:
        for _, contract in contracts.iterrows():
            contract_by_key[str(contract.get("instrument_key"))] = dict(contract)

    underlying_rsi = None
    try:
        underlying_frame = intelligence.provider.intraday_candles(underlying_key, interval_minutes=5)
        underlying_rsi = _rsi14(underlying_frame)
    except Exception:
        underlying_rsi = None

    rows: list[dict[str, object]] = []
    for option_type, strikes, prefix in (("CE", ce_strikes, "call"), ("PE", pe_strikes, "put")):
        for distance_rank, strike in enumerate(strikes, start=1):
            match = chain[chain["strike"] == strike]
            if match.empty:
                continue
            chain_row = match.iloc[0]
            instrument_key = str(chain_row.get(f"{prefix}_instrument_key") or "")
            contract = contract_by_key.get(instrument_key, {})
            token = contract.get("instrument_token")
            ltp = _f(chain_row.get(f"{prefix}_ltp"))
            candle_metrics = {"vwap": None, "option_rsi": None, "premium_change_pct": None}
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
            spread = ask - bid if ask is not None and bid is not None and ask >= bid else None
            rows.append({
                "distance_rank": distance_rank,
                "instrument_key": instrument_key or None,
                "instrument_token": int(token) if token not in (None, "") else None,
                "tradingsymbol": str(contract.get("tradingsymbol") or instrument_key or f"{strike:g} {option_type}"),
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
