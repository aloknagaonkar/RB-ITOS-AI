from __future__ import annotations

from dataclasses import replace
import pandas as pd

from red_bar_lab.services.historical_dri_trailing_validation import (
    TrailingStopConfig,
    simulate_trailing_stop,
)


def _point_in_time_frame(candles: pd.DataFrame, moment) -> pd.DataFrame:
    if candles is None or candles.empty or "timestamp" not in candles.columns:
        return pd.DataFrame()
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], errors="coerce", utc=True
    )
    ts = pd.Timestamp(moment)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Kolkata")
    ts = ts.tz_convert("UTC")
    frame = frame.loc[frame["timestamp"] <= ts].copy()
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"]).sort_values(
        "timestamp"
    )


def resolve_numeric_metric(
    value,
    *,
    names: tuple[str, ...] = (),
) -> float | None:
    """Resolve a numeric value from scalars, dicts, or object attributes."""
    candidates = [value]
    if isinstance(value, dict):
        candidates.extend(value.get(name) for name in names)
    elif value is not None:
        candidates.extend(getattr(value, name, None) for name in names)

    for candidate in candidates:
        if candidate is None or isinstance(candidate, bool):
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def evaluate_reset_override_quality(
    candles: pd.DataFrame | None,
    *,
    moment,
    direction: str,
    reset_classification: str,
    reset_rebreak_reason: str | None = None,
    break_level: float | None,
    candidate_score: float | None,
    opportunity_health: float | None,
    ema10_ok: bool | None = None,
    ema30_ok: bool | None = None,
    reversal_confirmed: bool | None = None,
) -> dict[str, object]:
    quality_override_entry = bool(
        reset_classification == "RESET_WINDOW_CONFIRMED"
        and (
            reset_rebreak_reason is None
            or str(reset_rebreak_reason)
            == "RESET_MOMENTUM_REEXPANSION"
        )
    )
    result = {
        "applicable": quality_override_entry,
        "passed": True,
        "criteria_count": 0,
        "body_ratio_pct": None,
        "move_beyond_break_pct": None,
        "relative_volume": None,
        "candidate_score_ok": False,
        "opportunity_health_ok": False,
        "body_quality_ok": False,
        "break_distance_ok": False,
        "relative_volume_ok": False,
        "criteria": "",
        "market_action_count": 0,
        "market_action_passed": False,
        "market_action_criteria": "",
        "moderate_market_action_passed": False,
        "market_action_tier": "NONE",
    }
    if not result["applicable"]:
        return result

    frame = _point_in_time_frame(candles, moment)
    if frame.empty:
        result["passed"] = False
        return result

    latest = frame.iloc[-1]
    candle_range = max(float(latest["high"]) - float(latest["low"]), 0.0)
    body_ratio_pct = (
        abs(float(latest["close"]) - float(latest["open"]))
        / candle_range
        * 100.0
        if candle_range > 0
        else 0.0
    )

    close_price = float(latest["close"])
    direction = str(direction or "").upper()
    if break_level is not None and float(break_level) != 0:
        if direction == "BULLISH":
            move_pct = (
                (close_price - float(break_level))
                / abs(float(break_level))
                * 100.0
            )
        else:
            move_pct = (
                (float(break_level) - close_price)
                / abs(float(break_level))
                * 100.0
            )
    else:
        move_pct = 0.0

    relative_volume = None
    if "volume" in frame.columns:
        volume = frame["volume"].fillna(0.0)
        recent_avg = float(volume.tail(20).mean()) if len(volume) else 0.0
        if recent_avg > 0:
            relative_volume = float(volume.iloc[-1]) / recent_avg

    checks = {
        "BODY_70": body_ratio_pct >= 70.0,
        "CANDIDATE_88": float(
            resolve_numeric_metric(candidate_score) or 0.0
        ) >= 88.0,
        "HEALTH_85": float(
            resolve_numeric_metric(opportunity_health) or 0.0
        ) >= 85.0,
        "BREAK_005": move_pct >= 0.05,
        "RVOL_12": (
            relative_volume is not None and relative_volume >= 1.20
        ),
    }
    count = sum(1 for value in checks.values() if value)
    market_action_checks = {
        name: checks[name]
        for name in ("BODY_70", "BREAK_005", "RVOL_12")
    }
    market_action_count = sum(
        1 for value in market_action_checks.values() if value
    )
    strong_market_action_passed = market_action_count >= 1
    moderate_market_action_passed = bool(
        body_ratio_pct >= 60.0
        and move_pct > 0.0
        and checks["CANDIDATE_88"]
        and checks["HEALTH_85"]
        and bool(ema10_ok)
        and bool(ema30_ok)
        and bool(reversal_confirmed)
    )
    market_action_passed = bool(
        strong_market_action_passed
        or moderate_market_action_passed
    )
    market_action_tier = (
        "STRONG"
        if strong_market_action_passed
        else "MODERATE"
        if moderate_market_action_passed
        else "NONE"
    )

    result.update(
        {
            "passed": count >= 2 and market_action_passed,
            "criteria_count": count,
            "body_ratio_pct": round(body_ratio_pct, 3),
            "move_beyond_break_pct": round(move_pct, 4),
            "relative_volume": (
                round(relative_volume, 3)
                if relative_volume is not None
                else None
            ),
            "candidate_score_ok": checks["CANDIDATE_88"],
            "opportunity_health_ok": checks["HEALTH_85"],
            "body_quality_ok": checks["BODY_70"],
            "break_distance_ok": checks["BREAK_005"],
            "relative_volume_ok": checks["RVOL_12"],
            "criteria": ",".join(
                name for name, passed in checks.items() if passed
            ),
            "market_action_count": market_action_count,
            "market_action_passed": market_action_passed,
            "moderate_market_action_passed": (
                moderate_market_action_passed
            ),
            "market_action_tier": market_action_tier,
            "market_action_criteria": ",".join(
                name for name, passed in market_action_checks.items()
                if passed
            ),
        }
    )
    return result


def derive_adaptive_initial_stop_pct(
    candles: pd.DataFrame,
    *,
    entry_moment,
    entry_price: float,
) -> float:
    frame = _point_in_time_frame(candles, entry_moment)
    if len(frame) < 3 or float(entry_price) <= 0:
        return 7.0

    work = frame.tail(14).copy()
    previous_close = work["close"].shift(1)
    true_range = pd.concat(
        [
            work["high"] - work["low"],
            (work["high"] - previous_close).abs(),
            (work["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.dropna().mean()) if not true_range.dropna().empty else 0.0
    raw_pct = (atr / float(entry_price)) * 100.0 * 1.5
    return round(min(12.0, max(5.0, raw_pct)), 3)


def simulate_adaptive_trailing_stop(
    candles: pd.DataFrame,
    *,
    entry_moment,
    entry_price: float,
    baseline_exit_price: float | None,
    base_config: TrailingStopConfig,
):
    adaptive_stop_pct = derive_adaptive_initial_stop_pct(
        candles,
        entry_moment=entry_moment,
        entry_price=entry_price,
    )
    config = replace(
        base_config,
        initial_stop_pct=adaptive_stop_pct,
    )
    result = simulate_trailing_stop(
        candles,
        entry_moment=entry_moment,
        entry_price=entry_price,
        baseline_exit_price=baseline_exit_price,
        config=config,
    )
    return adaptive_stop_pct, result
