from __future__ import annotations

from typing import Mapping

from red_bar_lab.execution.bundles import RED_BAR
from red_bar_lab.ui.strategy_bundle_lifecycle import strategy_owned


def _latest(rows, fields):
    values = [dict(row) for row in rows]
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
    direction = str(direction or "").upper()
    bias = str(option_bias or "").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        return "NOT APPLICABLE"
    if bias in {"UNAVAILABLE", "NEUTRAL", ""}:
        return "NEUTRAL"
    if direction in bias:
        return "SUPPORTING"
    if (direction == "BULLISH" and "BEARISH" in bias) or (
        direction == "BEARISH" and "BULLISH" in bias
    ):
        return "CONFLICTING"
    return "MIXED"


def build_red_bar_owned_setup_state(
    database,
    instrument_key: str,
    trading_date: str,
    *,
    reference: Mapping[str, object] | None,
    option_bias: object,
) -> dict[str, object]:
    attempts = list(database.read_signal_attempts(instrument_key, trading_date) or [])
    owned = [row for row in attempts if strategy_owned(row, RED_BAR)]
    latest = _latest(owned, ("confirmation_timestamp", "cross_timestamp"))
    reference = dict(reference or {})

    confirmed = bool(latest.get("confirmation_timestamp") and latest.get("direction"))
    crossed = bool(latest.get("cross_timestamp"))
    if confirmed:
        status = "CONFIRMED"
        waiting = "Red Bar bundle normalization and downstream contract selection"
        blocker = "None at strategy-detection layer"
    elif crossed:
        status = "CROSS DETECTED"
        waiting = "Confirmation candle acceptance"
        blocker = "No confirmed Red Bar-owned direction is persisted yet"
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
            "observed": str(midpoint) if midpoint not in (None, "") else "Unavailable",
        },
        {
            "condition": "Red Bar-owned midpoint cross",
            "status": "PASS" if crossed else "WAIT",
            "observed": latest.get("cross_timestamp") or "Not detected",
        },
        {
            "condition": "Red Bar-owned confirmation",
            "status": "PASS" if confirmed else "WAIT",
            "observed": latest.get("confirmation_timestamp") or "Not confirmed",
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
