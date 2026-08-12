from __future__ import annotations

from datetime import datetime


def _sort_time(value):
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return datetime.min


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
