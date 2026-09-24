from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(
    prefix="/api/live-shadow/hilega-historical",
    tags=["hilega-historical-directional"],
)

ROOT = Path("data/historical-evidence")
DIRECTIONAL_ROOT = ROOT / "hilega-directional-replay-v1"
CE_ROOT = ROOT / "hilega-directional-ce-shadow-v1"
PE_ROOT = ROOT / "hilega-directional-pe-shadow-v1"
IST = ZoneInfo("Asia/Kolkata")


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _accepted_directional_trades(session_date: str) -> list[dict[str, str]]:
    return _csv_rows(DIRECTIONAL_ROOT / session_date / "directional-trades.csv")


def _accepted_entry_times(rows: list[dict[str, str]], direction: str) -> set[str]:
    return {
        str(row.get("entry_time") or "")[:5]
        for row in rows
        if str(row.get("direction") or "").upper() == direction
        and row.get("entry_time")
    }


def _leg_trade_index(row: dict[str, str]) -> int | None:
    for key in ("trade_index", "trade_number", "trade_id"):
        value = _int(row.get(key))
        if value is not None:
            return value
    return None


def _option_leg(
    row: dict[str, str],
    *,
    side: str,
    session_date: str,
    fallback_entry: str | None,
    fallback_exit: str | None,
) -> dict[str, Any]:
    def stamp(key: str, fallback: str | None) -> str | None:
        if row.get(key):
            return row[key]
        return f"{session_date}T{fallback}:00+05:30" if fallback else None

    return {
        "relation_to_atm": _int(row.get("relation_to_atm")),
        "strike": _num(row.get("strike")),
        "side": side,
        "instrument_key": row.get("instrument_key") or "",
        "entry_timestamp": stamp("entry_timestamp", fallback_entry),
        "entry_open": _num(row.get("entry_open")),
        "latest_completed_minute": row.get("latest_completed_minute") or None,
        "latest_close": _num(row.get("latest_close")),
        "current_points": _num(row.get("current_points")),
        "current_return_pct": _num(row.get("current_return_pct")),
        "mfe_points": _num(row.get("mfe_points")),
        "mfe_pct": _num(row.get("mfe_pct")),
        "mae_points": _num(row.get("mae_points")),
        "mae_pct": _num(row.get("mae_pct")),
        "exit_timestamp": stamp("exit_timestamp", fallback_exit),
        "exit_open": _num(row.get("exit_open")),
        "realized_points": _num(row.get("realized_points")),
        "realized_return_pct": _num(row.get("realized_return_pct")),
    }


def _shadow_trades(
    *,
    session_date: str,
    accepted_rows: list[dict[str, str]],
    direction: str,
    side: str,
    root: Path,
    trade_file: str,
    legs_file: str,
    historical_source: str,
) -> list[dict[str, Any]]:
    folder = root / session_date
    summaries = _csv_rows(folder / trade_file)
    leg_rows = _csv_rows(folder / legs_file)
    if not summaries:
        return []

    accepted_times = _accepted_entry_times(accepted_rows, direction)

    by_index: dict[int, list[dict[str, str]]] = {}
    for row in leg_rows:
        idx = _leg_trade_index(row)
        if idx is not None:
            by_index.setdefault(idx, []).append(row)

    sequential_groups: list[list[dict[str, str]]] = []
    if leg_rows and not by_index and len(leg_rows) % 5 == 0:
        sequential_groups = [leg_rows[i:i + 5] for i in range(0, len(leg_rows), 5)]

    out: list[dict[str, Any]] = []
    for pos, summary in enumerate(summaries):
        entry_time = str(summary.get("entry_time") or "")[:5]
        if accepted_times and entry_time not in accepted_times:
            continue

        idx = _int(summary.get("trade_index"))
        raw_legs = by_index.get(idx or -1, [])
        if not raw_legs and pos < len(sequential_groups):
            raw_legs = sequential_groups[pos]

        legs = [
            _option_leg(
                row,
                side=side,
                session_date=session_date,
                fallback_entry=None,
                fallback_exit=None,
            )
            for row in raw_legs
        ]
        legs.sort(
            key=lambda x: 99 if x["relation_to_atm"] is None else x["relation_to_atm"]
        )

        status = str(summary.get("status") or "INCOMPLETE")
        complete_legs = _int(summary.get("complete_legs")) or 0
        issue = summary.get("issue") or None
        entry_event = summary.get("entry_event") or None
        exit_event = summary.get("exit_event") or None

        signal_bar = (
            f"{session_date}T{entry_time}:00+05:30" if entry_time else None
        )
        signal_boundary = (
            legs[0].get("entry_timestamp") if legs else None
        )

        out.append(
            {
                "direction": direction,
                "option_side": side,
                "signal_bar": signal_bar,
                "signal_boundary": signal_boundary,
                "signal_spot": _num(summary.get("signal_spot")),
                "source": entry_event,
                "expiry": summary.get("expiry") or None,
                "atm": _num(summary.get("atm")),
                "status": status,
                "complete": status == "CLOSED" and complete_legs == 5 and not issue,
                "issue": issue,
                "exit_reason": exit_event,
                "pending_exit_boundary": None,
                "legs": legs,
                "trade_index": idx,
                "historical_source": historical_source,
            }
        )
    return out


def build_directional_historical_dashboard(session_date: str) -> dict[str, Any]:
    try:
        datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "session_date must be YYYY-MM-DD") from exc

    directional_file = DIRECTIONAL_ROOT / session_date / "directional-trades.csv"
    if not directional_file.is_file():
        raise HTTPException(
            404,
            f"No directional replay evidence for {session_date}. "
            "Historical UI will not synthesize directional trades.",
        )

    accepted = _accepted_directional_trades(session_date)
    bullish = _shadow_trades(
        session_date=session_date,
        accepted_rows=accepted,
        direction="BULLISH",
        side="CE",
        root=CE_ROOT,
        trade_file="ce-shadow-trades.csv",
        legs_file="ce-shadow-legs.csv",
        historical_source="DIRECTIONAL_CE_HISTORICAL_SHADOW",
    )
    bearish = _shadow_trades(
        session_date=session_date,
        accepted_rows=accepted,
        direction="BEARISH",
        side="PE",
        root=PE_ROOT,
        trade_file="pe-shadow-trades.csv",
        legs_file="pe-shadow-legs.csv",
        historical_source="DIRECTIONAL_PE_HISTORICAL_SHADOW",
    )
    trades = bullish + bearish
    trades.sort(key=lambda t: str(t.get("signal_bar") or ""))

    active = [t for t in trades if str(t.get("status") or "").upper() == "ACTIVE"]
    complete = [t for t in trades if bool(t.get("complete"))]
    pending = [
        t for t in trades
        if str(t.get("status") or "").upper() == "PENDING_EXACT_EXIT"
    ]
    incomplete = [
        t for t in trades
        if str(t.get("status") or "").upper() != "ACTIVE"
        and not bool(t.get("complete"))
    ]

    accepted_bullish = sum(
        1 for row in accepted
        if str(row.get("direction") or "").upper() == "BULLISH"
    )
    accepted_bearish = sum(
        1 for row in accepted
        if str(row.get("direction") or "").upper() == "BEARISH"
    )

    return {
        "model": "HILEGA_DIRECTIONAL_HISTORICAL_DASHBOARD_V2",
        "session_date": session_date,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "quantity": None,
        "account_pnl_rupees": None,
        "measurement": "INDEPENDENT_SHADOW_PREMIUM_POINTS_PER_1_OPTION_UNIT",
        "warning": (
            "NOT EXECUTED P&L: historical CE/PE ATM±2 legs are independent "
            "shadow observations; no quantity, portfolio aggregation, spreads, "
            "slippage or fees."
        ),
        "coverage_note": (
            "Trades are restricted to entries accepted by the directional replay. "
            "Bullish CE and bearish PE both use recorded exact historical shadow "
            "evidence. Missing evidence remains unavailable and is never synthesized."
        ),
        "directional_trade_count": len(accepted),
        "accepted_bullish_trades": accepted_bullish,
        "accepted_bearish_trades": accepted_bearish,
        "trade_count": len(trades),
        "active_count": len(active),
        "complete_closed_count": len(complete),
        "pending_exit_count": len(pending),
        "incomplete_count": len(incomplete),
        "by_direction": {
            "BULLISH": {
                "accepted_trade_count": accepted_bullish,
                "projected_trade_count": len(bullish),
            },
            "BEARISH": {
                "accepted_trade_count": accepted_bearish,
                "projected_trade_count": len(bearish),
            },
        },
        "trades": trades,
    }


@router.get("/directional-dashboard")
def directional_dashboard(
    session_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    return build_directional_historical_dashboard(session_date)
