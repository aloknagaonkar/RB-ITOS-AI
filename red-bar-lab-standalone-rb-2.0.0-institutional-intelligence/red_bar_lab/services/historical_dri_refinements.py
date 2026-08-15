from __future__ import annotations

from dataclasses import is_dataclass, replace
from types import SimpleNamespace

import pandas as pd


RESET_WINDOW_BARS = 5
EMA10_NEAR_TOUCH_PCT = 0.08


def strong_expansion_candle(
    frame: pd.DataFrame,
    direction: str,
    *,
    minimum_body_ratio: float = 0.60,
    structure_bars: int = 1,
) -> bool:
    if frame is None or len(frame) < structure_bars + 1:
        return False

    latest = frame.iloc[-1]
    prior = frame.iloc[-1 - structure_bars : -1]

    open_price = float(latest["open"])
    high = float(latest["high"])
    low = float(latest["low"])
    close = float(latest["close"])
    candle_range = max(high - low, 0.0)
    if candle_range <= 0:
        return False

    body_ratio = abs(close - open_price) / candle_range
    direction = str(direction or "").upper()

    if direction == "BULLISH":
        break_level = float(prior["high"].max())
        return bool(
            close > open_price
            and body_ratio >= float(minimum_body_ratio)
            and close > break_level
        )

    break_level = float(prior["low"].min())
    return bool(
        close < open_price
        and body_ratio >= float(minimum_body_ratio)
        and close < break_level
    )


def _to_frame(candles: pd.DataFrame, moment) -> pd.DataFrame:
    if candles is None or candles.empty or "timestamp" not in candles.columns:
        return pd.DataFrame()

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
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(
        subset=["open", "high", "low", "close"]
    ).sort_values("timestamp")

    if not frame.empty:
        frame["ema10"] = frame["close"].ewm(
            span=10, adjust=False
        ).mean()
        frame["ema30"] = frame["close"].ewm(
            span=30, adjust=False
        ).mean()

    return frame


def reset_reexpansion_diagnostics(
    candles: pd.DataFrame,
    *,
    moment,
    direction: str,
    momentum_ok: bool,
) -> dict[str, object]:
    result = {
        "reset_seen": False,
        "reexpansion_detected": False,
        "reset_candle_time": None,
        "ema10_touch_detected": False,
        "reexpansion_break_level": None,
        "strong_expansion_candle": False,
        "momentum_ok": bool(momentum_ok),
        "reset_classification": "NONE",
        "reset_window_bars": RESET_WINDOW_BARS,
        "reset_counter_candle_seen": False,
        "reset_near_touch_detected": False,
        "shallow_reset_detected": False,
    }

    frame = _to_frame(candles, moment)
    if len(frame) < 3:
        return result

    latest = frame.iloc[-1]
    prior_window = frame.iloc[
        max(0, len(frame) - RESET_WINDOW_BARS - 1) : -1
    ].copy()
    if prior_window.empty:
        return result

    direction = str(direction or "").upper()
    tolerance = EMA10_NEAR_TOUCH_PCT / 100.0

    if direction == "BULLISH":
        counter_mask = prior_window["close"] < prior_window["open"]
        near_touch_mask = (
            prior_window["low"]
            <= prior_window["ema10"] * (1.0 + tolerance)
        )
        ema10_aligned = (
            float(latest["close"]) > float(latest["ema10"])
            and float(latest["ema10"])
            > float(frame.iloc[-2]["ema10"])
        )
        ema30_aligned = (
            len(frame) >= 30
            and float(latest["close"]) > float(latest["ema30"])
            and float(latest["ema30"])
            > float(frame.iloc[-2]["ema30"])
        )
    else:
        counter_mask = prior_window["close"] > prior_window["open"]
        near_touch_mask = (
            prior_window["high"]
            >= prior_window["ema10"] * (1.0 - tolerance)
        )
        ema10_aligned = (
            float(latest["close"]) < float(latest["ema10"])
            and float(latest["ema10"])
            < float(frame.iloc[-2]["ema10"])
        )
        ema30_aligned = (
            len(frame) >= 30
            and float(latest["close"]) < float(latest["ema30"])
            and float(latest["ema30"])
            < float(frame.iloc[-2]["ema30"])
        )

    counter_seen = bool(counter_mask.any())
    near_touch_seen = bool(near_touch_mask.any())

    reset_candidates = prior_window.loc[counter_mask]
    reset_row = (
        reset_candidates.iloc[-1]
        if not reset_candidates.empty
        else None
    )

    if reset_row is not None:
        reset_position = prior_window.index.get_loc(reset_row.name)
        post_reset = prior_window.iloc[reset_position:]
    else:
        post_reset = prior_window

    if post_reset.empty:
        post_reset = prior_window

    if direction == "BULLISH":
        break_level = float(post_reset["high"].max())
        reexpanded = bool(
            momentum_ok
            and ema10_aligned
            and float(latest["close"]) > float(latest["open"])
            and float(latest["close"]) > break_level
        )
    else:
        break_level = float(post_reset["low"].min())
        reexpanded = bool(
            momentum_ok
            and ema10_aligned
            and float(latest["close"]) < float(latest["open"])
            and float(latest["close"]) < break_level
        )

    normal_expansion = strong_expansion_candle(
        frame.tail(2),
        direction,
        minimum_body_ratio=0.60,
        structure_bars=1,
    )
    shallow_expansion = strong_expansion_candle(
        frame.tail(3),
        direction,
        minimum_body_ratio=0.70,
        structure_bars=2,
    )

    reset_window_confirmed = bool(
        counter_seen
        and near_touch_seen
        and reexpanded
        and normal_expansion
    )

    shallow_reset_confirmed = bool(
        counter_seen
        and not near_touch_seen
        and reexpanded
        and shallow_expansion
        and ema10_aligned
        and ema30_aligned
    )

    if reset_window_confirmed:
        classification = "RESET_WINDOW_CONFIRMED"
    elif shallow_reset_confirmed:
        classification = "SHALLOW_RESET_EXPANSION"
    else:
        classification = "NONE"

    result.update(
        {
            "reset_seen": bool(counter_seen),
            "reexpansion_detected": reexpanded,
            "reset_candle_time": (
                reset_row.get("timestamp")
                if reset_row is not None
                else None
            ),
            "ema10_touch_detected": near_touch_seen,
            "reexpansion_break_level": break_level,
            "strong_expansion_candle": normal_expansion,
            "reset_classification": classification,
            "reset_counter_candle_seen": counter_seen,
            "reset_near_touch_detected": near_touch_seen,
            "shallow_reset_detected": shallow_reset_confirmed,
        }
    )
    return result


def reset_momentum_reexpansion(
    candles: pd.DataFrame,
    *,
    moment,
    direction: str,
    momentum_ok: bool,
) -> bool:
    diagnostics = reset_reexpansion_diagnostics(
        candles,
        moment=moment,
        direction=direction,
        momentum_ok=momentum_ok,
    )
    return diagnostics["reset_classification"] in {
        "RESET_WINDOW_CONFIRMED",
        "SHALLOW_RESET_EXPANSION",
    }


def override_reset_rebreak_if_reexpanded(
    result,
    candles: pd.DataFrame,
    *,
    moment,
    direction: str,
    momentum_ok: bool,
):
    if getattr(result, "reason", None) != "NO_FRESH_STRUCTURE_REBREAK":
        return result

    diagnostics = reset_reexpansion_diagnostics(
        candles,
        moment=moment,
        direction=direction,
        momentum_ok=momentum_ok,
    )
    classification = str(
        diagnostics.get("reset_classification") or "NONE"
    )
    if classification == "NONE":
        return result

    updates = {
        "reason": "RESET_MOMENTUM_REEXPANSION",
    }
    for name in ("allowed", "eligible", "passed", "confirmed"):
        if hasattr(result, name):
            updates[name] = True

    if is_dataclass(result):
        valid = {
            field_name: value
            for field_name, value in updates.items()
            if hasattr(result, field_name)
        }
        return replace(result, **valid)

    values = dict(getattr(result, "__dict__", {}))
    values.update(updates)
    return SimpleNamespace(**values)
