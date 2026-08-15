from __future__ import annotations

import pandas as pd


def build_reversal_diagnostics(
    candles: pd.DataFrame,
    *,
    moment,
    direction: str,
    reversal_decision,
    active_invalidation,
    reset_rebreak_reason,
) -> dict[str, object]:
    result = {
        "reversal_state": getattr(
            getattr(reversal_decision, "state", None), "value", None
        ),
        "reversal_reason": getattr(reversal_decision, "reason", None),
        "reversal_provisional": bool(
            getattr(reversal_decision, "provisional", False)
        ),
        "reversal_confirmed": bool(
            getattr(reversal_decision, "confirmed", False)
        ),
        "reversal_ema10_value": None,
        "reversal_ema10_slope": None,
        "reversal_ema10_ok": None,
        "reversal_ema30_value": None,
        "reversal_ema30_slope": None,
        "reversal_ema30_ok": None,
        "reversal_two_directional_closes": None,
        "reversal_momentum_ok": getattr(
            reversal_decision, "momentum_ok", None
        ),
        "reversal_active_invalidation": active_invalidation,
        "reversal_invalidation_broken": getattr(
            reversal_decision, "invalidation_broken", None
        ),
        "reset_rebreak_reason": reset_rebreak_reason,
    }

    if candles is None or candles.empty or "timestamp" not in candles.columns:
        return result

    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], errors="coerce", utc=True
    ).dt.tz_convert("Asia/Kolkata")
    ts = pd.Timestamp(moment)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Kolkata")
    else:
        ts = ts.tz_convert("Asia/Kolkata")

    frame = frame.loc[frame["timestamp"] <= ts].copy()
    for column in ("open", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "close"]).sort_values("timestamp")
    if len(frame) < 2:
        return result

    close = frame["close"]
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema30 = close.ewm(span=30, adjust=False).mean()
    latest_close = float(close.iloc[-1])
    ema10_value = float(ema10.iloc[-1])
    ema10_slope = ema10_value - float(ema10.iloc[-2])
    ema30_value = float(ema30.iloc[-1])
    ema30_slope = ema30_value - float(ema30.iloc[-2])
    direction = str(direction or "").upper()

    last_two = frame.tail(2)
    if direction == "BULLISH":
        two_closes = bool(
            (last_two["close"] > last_two["open"]).all()
            and last_two["close"].is_monotonic_increasing
        )
        ema10_ok = latest_close > ema10_value and ema10_slope > 0
        ema30_ok = (
            len(frame) >= 30
            and latest_close > ema30_value
            and ema30_slope > 0
        )
        invalidation_broken = (
            active_invalidation is not None
            and latest_close > float(active_invalidation)
        )
    else:
        two_closes = bool(
            (last_two["close"] < last_two["open"]).all()
            and last_two["close"].is_monotonic_decreasing
        )
        ema10_ok = latest_close < ema10_value and ema10_slope < 0
        ema30_ok = (
            len(frame) >= 30
            and latest_close < ema30_value
            and ema30_slope < 0
        )
        invalidation_broken = (
            active_invalidation is not None
            and latest_close < float(active_invalidation)
        )

    result.update(
        {
            "reversal_ema10_value": round(ema10_value, 4),
            "reversal_ema10_slope": round(ema10_slope, 6),
            "reversal_ema10_ok": bool(ema10_ok),
            "reversal_ema30_value": round(ema30_value, 4),
            "reversal_ema30_slope": round(ema30_slope, 6),
            "reversal_ema30_ok": bool(ema30_ok),
            "reversal_two_directional_closes": two_closes,
            "reversal_active_invalidation": active_invalidation,
            "reversal_invalidation_broken": bool(invalidation_broken),
        }
    )
    return result
