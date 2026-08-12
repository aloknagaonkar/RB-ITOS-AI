from __future__ import annotations

from typing import Iterable

import pandas as pd


def _as_ts(value) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("Asia/Kolkata")
        else:
            ts = ts.tz_convert("Asia/Kolkata")
        return ts
    except Exception:
        return None


def _normalise_candles(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    candles = frame.copy()
    timestamp = None
    for name in ("timestamp", "date", "datetime", "time"):
        if name in candles.columns:
            timestamp = pd.to_datetime(candles[name], errors="coerce")
            break
    if timestamp is None and isinstance(candles.index, pd.DatetimeIndex):
        timestamp = pd.Series(candles.index, index=candles.index)
    if timestamp is None:
        try:
            timestamp = pd.to_datetime(candles.index, errors="coerce")
        except Exception:
            return pd.DataFrame()
    timestamp = pd.Series(timestamp, index=candles.index)
    try:
        if timestamp.dt.tz is None:
            timestamp = timestamp.dt.tz_localize("Asia/Kolkata")
        else:
            timestamp = timestamp.dt.tz_convert("Asia/Kolkata")
    except Exception:
        timestamp = pd.to_datetime(timestamp, errors="coerce", utc=True).dt.tz_convert("Asia/Kolkata")
    candles["_trace_timestamp"] = timestamp
    candles["close"] = pd.to_numeric(candles.get("close"), errors="coerce")
    candles = candles.dropna(subset=["_trace_timestamp", "close"])
    return candles.sort_values("_trace_timestamp")


def _price_at_or_before(candles: pd.DataFrame, when) -> tuple[float | None, str | None]:
    target = _as_ts(when)
    if target is None or candles.empty:
        return None, None
    eligible = candles[candles["_trace_timestamp"] <= target]
    if eligible.empty:
        later = candles[candles["_trace_timestamp"] > target]
        if later.empty:
            return None, None
        row = later.iloc[0]
        delta = row["_trace_timestamp"] - target
        if delta.total_seconds() > 65:
            return None, None
    else:
        row = eligible.iloc[-1]
    return round(float(row["close"]), 2), row["_trace_timestamp"].isoformat()


def _pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return round((end - start) / start * 100.0, 2)


def _first_consumed_row(
    all_rows: Iterable[dict[str, object]],
    *,
    signal_id: str,
    candidate_symbol: str,
) -> dict[str, object] | None:
    matches = [
        row for row in all_rows
        if str(row.get("signal_id") or "") == signal_id
        and str(row.get("candidate_symbol") or "") == candidate_symbol
        and "REWARD_CONSUMED" in str(row.get("reason") or "").upper()
    ]
    if not matches:
        return None
    return min(matches, key=lambda row: str(row.get("evaluated_at") or ""))


def build_all_candidate_contract_price_trace(
    *,
    market,
    underlying_name: str,
    trading_date: str,
    signal: dict[str, object],
    scan_rows: list[dict[str, object]],
    all_day_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Pull same-contract premium history for every candidate in one scan.

    Prices come from the same market provider's historical one-minute option
    candles. The exact candidate symbol is kept fixed across signal, consumed,
    and evaluation timestamps, so comparisons never substitute a later contract.
    """
    if not scan_rows:
        return []
    signal_id = str(signal.get("signal_id") or scan_rows[0].get("signal_id") or "")
    signal_time = signal.get("confirmation_timestamp")

    instruments = market.nfo_options(
        underlying_name=underlying_name,
        as_of=pd.Timestamp(trading_date).date(),
    )
    if instruments is None or instruments.empty:
        return [
            {
                "candidate_symbol": row.get("candidate_symbol"),
                "status": "CONTRACT_NOT_RESOLVED",
            }
            for row in scan_rows
        ]

    by_symbol = {}
    for _, item in instruments.iterrows():
        symbol = str(item.get("tradingsymbol") or "")
        if symbol:
            by_symbol[symbol] = item

    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in scan_rows:
        symbol = str(row.get("candidate_symbol") or "")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        contract = by_symbol.get(symbol)
        if contract is None:
            result.append({
                "candidate_symbol": symbol,
                "status": "CONTRACT_NOT_RESOLVED",
                "signal_price": None,
                "first_consumed_price": None,
                "evaluation_price": None,
            })
            continue
        try:
            token = int(contract.get("instrument_token"))
            candles = market.historical_candles(
                instrument_token=token,
                interval="minute",
                date_from=trading_date,
                date_to=trading_date,
                include_oi=True,
            )
        except Exception as exc:
            result.append({
                "candidate_symbol": symbol,
                "status": f"CANDLE_FETCH_FAILED[{type(exc).__name__}]",
                "signal_price": None,
                "first_consumed_price": None,
                "evaluation_price": None,
            })
            continue

        normalised = _normalise_candles(candles)
        signal_price, signal_price_time = _price_at_or_before(normalised, signal_time)
        evaluation_time = row.get("evaluated_at")
        evaluation_price, evaluation_price_time = _price_at_or_before(normalised, evaluation_time)
        consumed = _first_consumed_row(
            all_day_rows,
            signal_id=signal_id,
            candidate_symbol=symbol,
        )
        consumed_time = consumed.get("evaluated_at") if consumed else None
        consumed_price, consumed_price_time = _price_at_or_before(normalised, consumed_time)

        result.append({
            "candidate_symbol": symbol,
            "instrument_token": token,
            "option_type": contract.get("instrument_type"),
            "strike": contract.get("strike"),
            "expiry": str(contract.get("expiry") or ""),
            "signal_time": signal_time,
            "signal_price": signal_price,
            "signal_price_candle": signal_price_time,
            "first_consumed_time": consumed_time,
            "first_consumed_price": consumed_price,
            "first_consumed_price_candle": consumed_price_time,
            "evaluation_time": evaluation_time,
            "evaluation_price": evaluation_price,
            "evaluation_price_candle": evaluation_price_time,
            "signal_to_consumed_change_pct": _pct_change(signal_price, consumed_price),
            "signal_to_evaluation_change_pct": _pct_change(signal_price, evaluation_price),
            "reward_remaining_pct": row.get("reward_remaining_pct"),
            "move_consumed_pct": row.get("move_consumed_pct"),
            "opportunity_score": row.get("opportunity_score"),
            "decision": row.get("decision"),
            "reason": row.get("reason"),
            "status": "OK" if signal_price is not None else "SIGNAL_PRICE_UNAVAILABLE",
        })
    return result
