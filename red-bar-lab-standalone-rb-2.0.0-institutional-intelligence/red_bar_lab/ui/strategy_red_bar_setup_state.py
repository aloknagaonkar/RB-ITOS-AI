from __future__ import annotations

from typing import Mapping

from red_bar_lab.execution.bundles import RED_BAR
from red_bar_lab.ui.strategy_bundle_lifecycle import strategy_owned


def _latest(rows, fields):
    values = [dict(row) for row in (rows or [])]
    if not values:
        return {}
    return max(
        values,
        key=lambda row: next(
            (str(row.get(field) or "") for field in fields if row.get(field)),
            "",
        ),
    )


def _option_alignment(direction: object, option_bias: object) -> str:
    normalized_direction = str(direction or "").upper()
    bias = str(option_bias or "").upper()
    if normalized_direction not in {"BULLISH", "BEARISH"}:
        return "NOT APPLICABLE"
    if bias in {"UNAVAILABLE", "NEUTRAL", ""}:
        return "NEUTRAL"
    if normalized_direction in bias:
        return "SUPPORTING"
    if (
        normalized_direction == "BULLISH" and "BEARISH" in bias
    ) or (
        normalized_direction == "BEARISH" and "BULLISH" in bias
    ):
        return "CONFLICTING"
    return "MIXED"


def build_red_bar_setup_state(
    database,
    instrument_key: str,
    trading_date: str,
    *,
    reference: Mapping[str, object] | None,
    option_bias: object,
) -> dict[str, object]:
    """Build Section 2 using only explicitly Red Bar-owned signal attempts."""
    attempts = list(
        database.read_signal_attempts(instrument_key, trading_date) or []
    )
    red_bar_attempts = [
        row for row in attempts if strategy_owned(row, RED_BAR)
    ]
    latest = _latest(
        red_bar_attempts,
        ("confirmation_timestamp", "cross_timestamp"),
    )
    reference = dict(reference or {})

    confirmed = bool(
        latest.get("confirmation_timestamp") and latest.get("direction")
    )
    crossed = bool(latest.get("cross_timestamp"))
    if confirmed:
        status = "CONFIRMED"
        waiting = "Contract selection and downstream execution gates"
        blocker = "None at strategy-detection layer"
    elif crossed:
        status = "CROSS DETECTED"
        waiting = "Confirmation candle acceptance"
        blocker = "No confirmed Red Bar direction is persisted yet"
    elif reference:
        status = "REFERENCE READY"
        waiting = "Completed price cross of the Red Bar midpoint"
        blocker = "No Red Bar-owned midpoint cross has been detected"
    else:
        status = "WAITING FOR REFERENCE"
        waiting = "NEXT_RED_CANDLE reference creation"
        blocker = "No persisted Red Bar reference"

    direction = latest.get("direction") if confirmed else "WAIT"
    midpoint = reference.get("midpoint") or reference.get("level_value")
    rows = [
        {
            "condition": "NEXT_RED_CANDLE reference",
            "status": "PASS" if reference else "WAIT",
            "observed": reference.get("source_timestamp") or "Not persisted",
        },
        {
            "condition": "Midpoint available",
            "status": "PASS" if midpoint not in (None, "") else "WAIT",
            "observed": (
                str(midpoint)
                if midpoint not in (None, "")
                else "Unavailable"
            ),
        },
        {
            "condition": "Red Bar-owned midpoint cross",
            "status": "PASS" if crossed else "WAIT",
            "observed": latest.get("cross_timestamp") or "Not detected",
        },
        {
            "condition": "Red Bar-owned confirmation candle",
            "status": "PASS" if confirmed else "WAIT",
            "observed": (
                latest.get("confirmation_timestamp") or "Not confirmed"
            ),
        },
        {
            "condition": "Strategy ownership",
            "status": "PASS" if latest else "WAIT",
            "observed": (
                "RED_BAR"
                if latest
                else "No explicitly Red Bar-owned signal attempt"
            ),
        },
    ]
    return {
        "status": status,
        "direction": direction,
        "setup_id": latest.get("signal_id") or "Not created",
        "waiting_for": waiting,
        "blocker": blocker,
        "option_alignment": _option_alignment(direction, option_bias),
        "rows": rows,
    }
