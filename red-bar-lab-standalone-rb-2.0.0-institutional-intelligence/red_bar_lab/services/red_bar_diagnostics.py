from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


IST = "Asia/Kolkata"


def _sort_time(value):
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return datetime.min


def _to_ist(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=("timestamp", "open", "high", "low", "close", "volume")
        )
    result = frame.copy()
    ts = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.loc[ts.notna()].copy()
    result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
    return (
        result.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _completed_five_minute_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Build the same complete 5-minute buckets used by the signal scanner."""
    source = _to_ist(frame)
    if source.empty:
        return pd.DataFrame()

    bars = source.set_index("timestamp").resample(
        "5min",
        origin="start_day",
        offset="15min",
        label="left",
        closed="left",
    ).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_rows=("close", "count"),
    )
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    bars = bars[bars["source_rows"] >= 5]
    return bars.reset_index()


def build_red_bar_cross_trace(
    one_minute: pd.DataFrame,
    lifecycle: dict[str, object],
) -> list[dict[str, object]]:
    """Explain every completed 5-minute cross evaluation after Red Bar creation.

    This is diagnostic-only and mirrors the existing signal-engine crossing rule:
      bullish: previous close <= midpoint < current close
      bearish: previous close >= midpoint > current close

    No levels, signal attempts, decisions, or execution state are changed.
    """
    if not lifecycle.get("reference_persisted"):
        return []
    midpoint = lifecycle.get("midpoint")
    source_timestamp = lifecycle.get("source_timestamp")
    interval_minutes = lifecycle.get("interval_minutes")
    if midpoint is None or not source_timestamp or interval_minutes is None:
        return []

    try:
        midpoint_value = float(midpoint)
        available_from = pd.Timestamp(source_timestamp)
        if available_from.tzinfo is None:
            available_from = available_from.tz_localize(IST)
        else:
            available_from = available_from.tz_convert(IST)
        available_from += pd.Timedelta(minutes=int(interval_minutes))
    except Exception:
        return []

    bars = _completed_five_minute_bars(one_minute)
    if bars.empty or len(bars) < 2:
        return []

    rows: list[dict[str, object]] = []
    for index in range(1, len(bars)):
        previous = bars.iloc[index - 1]
        current = bars.iloc[index]
        timestamp = pd.Timestamp(current["timestamp"])
        if timestamp < available_from:
            continue

        previous_close = float(previous["close"])
        current_close = float(current["close"])
        bullish = previous_close <= midpoint_value < current_close
        bearish = previous_close >= midpoint_value > current_close

        if bullish:
            result = "BULLISH_CROSS"
            reason = (
                f"PASS: previous close {previous_close:.2f} <= midpoint "
                f"{midpoint_value:.2f} < current close {current_close:.2f}."
            )
        elif bearish:
            result = "BEARISH_CROSS"
            reason = (
                f"PASS: previous close {previous_close:.2f} >= midpoint "
                f"{midpoint_value:.2f} > current close {current_close:.2f}."
            )
        elif previous_close > midpoint_value and current_close > midpoint_value:
            result = "NO_CROSS"
            reason = "Both previous and current 5m closes are above the midpoint."
        elif previous_close < midpoint_value and current_close < midpoint_value:
            result = "NO_CROSS"
            reason = "Both previous and current 5m closes are below the midpoint."
        else:
            result = "NO_CROSS"
            reason = (
                "The two closes touch/straddle the midpoint but do not satisfy "
                "the engine's strict close-cross inequality."
            )

        rows.append(
            {
                "timestamp": timestamp.to_pydatetime(),
                "previous_timestamp": pd.Timestamp(previous["timestamp"]).to_pydatetime(),
                "previous_close": previous_close,
                "open": float(current["open"]),
                "high": float(current["high"]),
                "low": float(current["low"]),
                "close": current_close,
                "midpoint": midpoint_value,
                "bullish_condition": bullish,
                "bearish_condition": bearish,
                "evaluation": result,
                "reason": reason,
            }
        )
    return rows


def build_red_bar_lifecycle(
    reference_levels: list[dict[str, object]],
    signal_attempts: list[dict[str, object]],
) -> dict[str, object]:
    """Build a read-only lifecycle snapshot for NEXT_RED_CANDLE.

    This helper intentionally does not create or modify levels/signals. It only
    explains what the already-persisted live pipeline has produced.
    """
    refs = [
        row for row in reference_levels
        if str(row.get("level_type") or "") == "NEXT_RED_CANDLE"
    ]
    attempts = [
        row for row in signal_attempts
        if str(row.get("level_type") or "") == "NEXT_RED_CANDLE"
    ]
    attempts.sort(key=lambda row: _sort_time(row.get("cross_timestamp")))

    if not refs:
        return {
            "level_type": "NEXT_RED_CANDLE",
            "status": "WAITING_FOR_RED_CANDLE",
            "reference_persisted": False,
            "source_timestamp": None,
            "source_high": None,
            "source_low": None,
            "midpoint": None,
            "interval_minutes": None,
            "data_quality": None,
            "signal_attempts": 0,
            "latest_signal_state": None,
            "direction": None,
            "cross_timestamp": None,
            "confirmation_timestamp": None,
            "detail": (
                "No NEXT_RED_CANDLE reference is persisted for this session. "
                "Check live 1-minute data and level generation first."
            ),
        }

    reference = refs[0]
    latest = attempts[-1] if attempts else None

    if latest is None:
        status = "WAITING_FOR_5M_CROSS"
        detail = (
            "NEXT_RED_CANDLE is detected and persisted. No qualifying later "
            "5-minute midpoint cross has created a signal attempt yet."
        )
    else:
        state = str(latest.get("state") or "UNKNOWN")
        status = {
            "AWAITING_CONFIRMATION": "WAITING_FOR_1M_CONFIRMATION",
            "ACTIVE": "ACTIVE",
            "TIMEOUT": "TIMEOUT",
            "CONFIRMATION_FAILED": "CONFIRMATION_FAILED",
            "CLOSED": "CLOSED",
        }.get(state, state)
        if state == "AWAITING_CONFIRMATION":
            detail = "5-minute cross exists; waiting for the 1-minute confirmation rule."
        elif state == "ACTIVE":
            detail = "NEXT_RED_CANDLE signal is ACTIVE after 1-minute confirmation."
        elif state in {"TIMEOUT", "CONFIRMATION_FAILED"}:
            detail = "A setup was created, but the 1-minute confirmation window failed."
        else:
            detail = f"Latest persisted NEXT_RED_CANDLE signal state: {state}."

    return {
        "level_type": "NEXT_RED_CANDLE",
        "status": status,
        "reference_persisted": True,
        "source_timestamp": reference.get("source_timestamp"),
        "source_high": reference.get("source_high"),
        "source_low": reference.get("source_low"),
        "midpoint": reference.get("midpoint"),
        "interval_minutes": reference.get("interval_minutes"),
        "data_quality": reference.get("data_quality"),
        "signal_attempts": len(attempts),
        "latest_signal_state": latest.get("state") if latest else None,
        "direction": latest.get("direction") if latest else None,
        "cross_timestamp": latest.get("cross_timestamp") if latest else None,
        "confirmation_timestamp": latest.get("confirmation_timestamp") if latest else None,
        "detail": detail,
    }
