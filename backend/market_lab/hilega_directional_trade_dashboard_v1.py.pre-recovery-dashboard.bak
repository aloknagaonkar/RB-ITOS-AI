from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

MODEL = "HILEGA_DIRECTIONAL_SHADOW_DASHBOARD_V1"
ROLES = (-2, -1, 0, 1, 2)
DIRECTIONS = ("BULLISH", "BEARISH")


def _stage_info(stage: str | None) -> tuple[str | None, str | None]:
    if not stage:
        return None, None
    for direction in DIRECTIONS:
        prefix = f"{direction}_OPTION_SHADOW_"
        if stage.startswith(prefix):
            return direction, stage[len(prefix):]
    return None, None


def project_directional_shadow_dashboard(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Project CE/PE directional audit into one read-only combined trade ledger.

    Bootstrap can legitimately emit UPDATE without a START because the active
    lifecycle was reconstructed silently. In that case the first ACTIVE update
    is accepted as the audited lifecycle identity; nothing is synthesized.
    """
    records = list(rows)
    by_trade: dict[tuple[str, str], list[tuple[int, str, str | None, dict[str, Any]]]] = {}

    for index, row in enumerate(records):
        direction, kind = _stage_info(row.get("stage"))
        if direction is None or kind not in {"START", "ENTRY_RETRY", "UPDATE", "EXIT", "EXIT_RETRY"}:
            continue
        payload = row.get("payload") or {}
        signal_bar = payload.get("signal_bar")
        if not signal_bar:
            continue
        by_trade.setdefault((direction, signal_bar), []).append(
            (index, kind, row.get("status"), payload)
        )

    trades: list[dict[str, Any]] = []
    for (direction, signal_bar), events in sorted(by_trade.items(), key=lambda x: x[0][1]):
        active_events = [
            e for e in events
            if e[3].get("status") == "ACTIVE" and e[1] in {"START", "ENTRY_RETRY", "UPDATE"}
        ]
        closed_events = [
            e for e in events
            if e[3].get("status") == "CLOSED" and e[1] in {"EXIT", "EXIT_RETRY"}
        ]
        pending_events = [
            e for e in events
            if e[3].get("status") == "PENDING_EXACT_EXIT" and e[1] in {"EXIT", "EXIT_RETRY"}
        ]
        failure_events = [
            e for e in events
            if e[3].get("status") not in {"ACTIVE", "CLOSED", "PENDING_EXACT_EXIT"}
        ]

        entry = active_events[0][3] if active_events else None
        if entry is None:
            # Preserve explicit failed/incomplete lifecycle attempts.
            payload = failure_events[-1][3] if failure_events else {}
            trades.append({
                "direction": direction,
                "option_side": "CE" if direction == "BULLISH" else "PE",
                "signal_bar": signal_bar,
                "signal_boundary": payload.get("signal_boundary"),
                "signal_spot": payload.get("signal_spot"),
                "source": payload.get("source"),
                "expiry": payload.get("expiry"),
                "atm": payload.get("atm"),
                "status": payload.get("status") or "NO_EXACT_ENTRY",
                "complete": False,
                "issue": payload.get("issue") or "EXACT_ENTRY_NOT_AVAILABLE",
                "exit_reason": payload.get("exit_reason"),
                "pending_exit_boundary": payload.get("pending_exit_boundary"),
                "legs": [],
            })
            continue

        latest = (
            closed_events[-1][3] if closed_events
            else pending_events[-1][3] if pending_events
            else active_events[-1][3]
        )

        entry_legs = {x.get("instrument_key"): x for x in entry.get("legs", [])}
        latest_legs = {x.get("instrument_key"): x for x in latest.get("legs", [])}
        legs: list[dict[str, Any]] = []
        for instrument, original in sorted(
            entry_legs.items(),
            key=lambda item: (item[1].get("relation_to_atm", 99), str(item[0])),
        ):
            current = latest_legs.get(instrument, original)
            legs.append({
                "relation_to_atm": original.get("relation_to_atm"),
                "strike": original.get("strike"),
                "side": original.get("side") or ("CE" if direction == "BULLISH" else "PE"),
                "instrument_key": instrument,
                "entry_timestamp": original.get("entry_timestamp"),
                "entry_open": original.get("entry_open"),
                "latest_completed_minute": current.get("latest_completed_minute"),
                "latest_close": current.get("latest_close"),
                "current_points": current.get("current_points"),
                "current_return_pct": current.get("current_return_pct"),
                "mfe_points": current.get("mfe_points"),
                "mfe_pct": current.get("mfe_pct"),
                "mae_points": current.get("mae_points"),
                "mae_pct": current.get("mae_pct"),
                "exit_timestamp": current.get("exit_timestamp"),
                "exit_open": current.get("exit_open"),
                "realized_points": current.get("realized_points"),
                "realized_return_pct": current.get("realized_return_pct"),
            })

        complete_exit = bool(closed_events) and len(legs) == 5 and all(
            x.get("relation_to_atm") in ROLES
            and x.get("entry_open") is not None
            and x.get("exit_open") is not None
            and x.get("realized_points") is not None
            for x in legs
        ) and sorted(x["relation_to_atm"] for x in legs) == list(ROLES)

        if complete_exit:
            status = "CLOSED"
        elif pending_events:
            status = "PENDING_EXACT_EXIT"
        elif latest.get("status") == "ACTIVE":
            status = "ACTIVE"
        else:
            status = latest.get("status") or "INCOMPLETE"

        trades.append({
            "direction": direction,
            "option_side": "CE" if direction == "BULLISH" else "PE",
            "signal_bar": signal_bar,
            "signal_boundary": entry.get("signal_boundary"),
            "signal_spot": entry.get("signal_spot"),
            "source": entry.get("source"),
            "expiry": entry.get("expiry"),
            "atm": entry.get("atm"),
            "status": status,
            "complete": complete_exit,
            "issue": latest.get("issue"),
            "exit_reason": latest.get("exit_reason"),
            "pending_exit_boundary": latest.get("pending_exit_boundary"),
            "legs": legs,
        })

    by_direction = {}
    for direction in DIRECTIONS:
        subset = [t for t in trades if t["direction"] == direction]
        by_direction[direction] = {
            "trade_count": len(subset),
            "active_count": sum(t["status"] == "ACTIVE" for t in subset),
            "closed_count": sum(t["status"] == "CLOSED" for t in subset),
            "incomplete_count": sum(t["status"] not in {"ACTIVE", "CLOSED"} for t in subset),
        }

    return {
        "model": MODEL,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "quantity": None,
        "account_pnl_rupees": None,
        "measurement": "INDEPENDENT_SHADOW_PREMIUM_POINTS_PER_1_OPTION_UNIT",
        "warning": (
            "NOT EXECUTED P&L: CE/PE ATM±2 legs are independent hypothetical "
            "observations; no quantity, portfolio aggregation, spreads, slippage or fees."
        ),
        "coverage_note": (
            "Ledger contains lifecycle records present in the directional live audit. "
            "Mid-session bootstrap reconstructs the currently active lifecycle but does "
            "not invent earlier exited option lifecycles."
        ),
        "trade_count": len(trades),
        "active_count": sum(t["status"] == "ACTIVE" for t in trades),
        "complete_closed_count": sum(bool(t["complete"]) for t in trades),
        "pending_exit_count": sum(t["status"] == "PENDING_EXACT_EXIT" for t in trades),
        "incomplete_count": sum(t["status"] not in {"ACTIVE", "CLOSED", "PENDING_EXACT_EXIT"} for t in trades),
        "by_direction": by_direction,
        "trades": list(reversed(trades)),
    }
