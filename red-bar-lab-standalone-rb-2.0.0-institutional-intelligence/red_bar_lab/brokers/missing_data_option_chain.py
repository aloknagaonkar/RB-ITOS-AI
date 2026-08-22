from __future__ import annotations

from typing import Any

import pandas as pd


def _value(mapping: dict[str, Any], key: str) -> Any | None:
    """Return the source value without inventing a numeric zero."""
    raw = mapping.get(key)
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass
    return raw


def _difference(left: Any | None, right: Any | None) -> float | None:
    if left is None or right is None:
        return None
    try:
        return float(left) - float(right)
    except (TypeError, ValueError):
        return None


def option_chain_to_dataframe_preserving_missing(
    records: list[dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in records:
        call = item.get("call_options") or {}
        put = item.get("put_options") or {}
        cmd = call.get("market_data") or {}
        pmd = put.get("market_data") or {}
        cg = call.get("option_greeks") or {}
        pg = put.get("option_greeks") or {}

        call_ltp = _value(cmd, "ltp")
        put_ltp = _value(pmd, "ltp")
        call_close = _value(cmd, "close_price")
        put_close = _value(pmd, "close_price")
        call_oi = _value(cmd, "oi")
        put_oi = _value(pmd, "oi")
        call_prev_oi = _value(cmd, "prev_oi")
        put_prev_oi = _value(pmd, "prev_oi")

        rows.append({
            "expiry": item.get("expiry"),
            "spot": _value(item, "underlying_spot_price"),
            "strike": _value(item, "strike_price"),
            "strike_pcr": _value(item, "pcr"),
            "call_instrument_key": call.get("instrument_key", ""),
            "call_ltp": call_ltp,
            "call_close": call_close,
            "call_price_change": _difference(call_ltp, call_close),
            "call_volume": _value(cmd, "volume"),
            "call_oi": call_oi,
            "call_prev_oi": call_prev_oi,
            "call_oi_change": _difference(call_oi, call_prev_oi),
            "call_bid": _value(cmd, "bid_price"),
            "call_bid_qty": _value(cmd, "bid_qty"),
            "call_ask": _value(cmd, "ask_price"),
            "call_ask_qty": _value(cmd, "ask_qty"),
            "call_iv": _value(cg, "iv"),
            "call_delta": _value(cg, "delta"),
            "call_gamma": _value(cg, "gamma"),
            "call_theta": _value(cg, "theta"),
            "call_vega": _value(cg, "vega"),
            "call_pop": _value(cg, "pop"),
            "put_instrument_key": put.get("instrument_key", ""),
            "put_ltp": put_ltp,
            "put_close": put_close,
            "put_price_change": _difference(put_ltp, put_close),
            "put_volume": _value(pmd, "volume"),
            "put_oi": put_oi,
            "put_prev_oi": put_prev_oi,
            "put_oi_change": _difference(put_oi, put_prev_oi),
            "put_bid": _value(pmd, "bid_price"),
            "put_bid_qty": _value(pmd, "bid_qty"),
            "put_ask": _value(pmd, "ask_price"),
            "put_ask_qty": _value(pmd, "ask_qty"),
            "put_iv": _value(pg, "iv"),
            "put_delta": _value(pg, "delta"),
            "put_gamma": _value(pg, "gamma"),
            "put_theta": _value(pg, "theta"),
            "put_vega": _value(pg, "vega"),
            "put_pop": _value(pg, "pop"),
        })

    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    text_columns = {"expiry", "call_instrument_key", "put_instrument_key"}
    numeric = [column for column in frame.columns if column not in text_columns]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    return frame.sort_values("strike", na_position="last").reset_index(drop=True)


def install() -> None:
    from red_bar_lab.brokers.upstox_client import UpstoxClient

    UpstoxClient.option_chain_to_dataframe = staticmethod(
        option_chain_to_dataframe_preserving_missing
    )


__all__ = ["install", "option_chain_to_dataframe_preserving_missing"]
