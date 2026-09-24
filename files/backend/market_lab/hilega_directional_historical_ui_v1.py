from __future__ import annotations

"""Read-only directional historical dashboard projection for Hilega-Milega.

This module does not replay strategy logic, call a broker, mutate historical
evidence, or infer missing option prices. It combines already-recorded evidence:

* accepted directional trades:
  data/historical-evidence/hilega-directional-replay-v1/<date>/directional-trades.csv
* bullish CE lifecycle:
  data/historical-evidence/hilega-milega-replay-v1/<date>/step-audit.jsonl
  projected through the same bullish dashboard projector used by live shadow
* bearish PE lifecycle:
  data/historical-evidence/hilega-directional-pe-shadow-v1/<date>/
  pe-shadow-trades.csv + pe-shadow-legs.csv

The response intentionally follows the live directional dashboard trade shape so
the replay and live UIs can present the same trade cards.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from .hilega_milega_trade_dashboard_v1 import project_shadow_dashboard
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

router = APIRouter(
    prefix="/api/live-shadow/hilega-historical",
    tags=["hilega-historical-directional"],
)

ROOT = Path("data/historical-evidence")
DIRECTIONAL_ROOT = ROOT / "hilega-directional-replay-v1"
BULLISH_ROOT = ROOT / "hilega-milega-replay-v1"
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


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() in {"1", "TRUE", "YES", "Y"}


def _hhmm(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    # Already HH:MM
    if len(text) >= 5 and text[2:3] == ":":
        return text[:5]
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST)
        return dt.strftime("%H:%M")
    except ValueError:
        return None


def _accepted_directional_trades(session_date: str) -> list[dict[str, str]]:
    return _csv_rows(DIRECTIONAL_ROOT / session_date / "directional-trades.csv")


def _accepted_entry_times(rows: list[dict[str, str]], direction: str) -> set[str]:
    return {
        str(r.get("entry_time") or "")[:5]
        for r in rows
        if str(r.get("direction") or "").upper() == direction and r.get("entry_time")
    }


def _bullish_trade_entry_hhmm(trade: dict[str, Any]) -> str | None:
    for key in ("signal_boundary", "entry_timestamp", "signal_bar"):
        v = _hhmm(trade.get(key))
        if v:
            return v
    for leg in trade.get("legs") or []:
        v = _hhmm(leg.get("entry_timestamp"))
        if v:
            return v
    return None


def _bullish_trades(session_date: str, accepted_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    audit = BULLISH_ROOT / session_date / "step-audit.jsonl"
    if not audit.is_file():
        return []

    store = ShadowStepAuditStoreV1(audit)
    try:
        rows = store.read_all()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            422, f"Bullish historical audit unreadable for {session_date}: {type(exc).__name__}"
        ) from exc

    projected = project_shadow_dashboard(rows)
    accepted_times = _accepted_entry_times(accepted_rows, "BULLISH")

    out: list[dict[str, Any]] = []
    for trade in projected.get("trades") or []:
        hhmm = _bullish_trade_entry_hhmm(trade)
        if accepted_times and hhmm not in accepted_times:
            continue
        item = dict(trade)
        item["direction"] = "BULLISH"
        item["option_side"] = "CE"
        item["historical_source"] = "BULLISH_CANONICAL_REPLAY"
        out.append(item)
    return out


def _pe_leg_trade_index(row: dict[str, str]) -> int | None:
    for key in ("trade_index", "trade_number", "trade_id"):
        v = _int(row.get(key))
        if v is not None:
            return v
    return None


def _pe_leg(row: dict[str, str], session_date: str) -> dict[str, Any]:
    def ts(key: str, fallback_hhmm: str | None = None) -> str | None:
        value = row.get(key)
        if value:
            return value
        if fallback_hhmm:
            return f"{session_date}T{fallback_hhmm}:00+05:30"
        return None

    relation = _int(row.get("relation_to_atm"))
    return {
        "relation_to_atm": relation,
        "strike": _num(row.get("strike")),
        "side": "PE",
        "instrument_key": row.get("instrument_key") or "",
        "entry_timestamp": ts("entry_timestamp", row.get("entry_time")),
        "entry_open": _num(row.get("entry_open")),
        "latest_completed_minute": ts("latest_completed_minute"),
        "latest_close": _num(row.get("latest_close")),
        "current_points": _num(row.get("current_points")),
        "current_return_pct": _num(row.get("current_return_pct")),
        "mfe_points": _num(row.get("mfe_points")),
        "mfe_pct": _num(row.get("mfe_pct")),
        "mae_points": _num(row.get("mae_points")),
        "mae_pct": _num(row.get("mae_pct")),
        "exit_timestamp": ts("exit_timestamp", row.get("exit_time")),
        "exit_open": _num(row.get("exit_open")),
        "realized_points": _num(row.get("realized_points")),
        "realized_return_pct": _num(row.get("realized_return_pct")),
    }


def _bearish_trades(session_date: str, accepted_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    folder = PE_ROOT / session_date
    summaries = _csv_rows(folder / "pe-shadow-trades.csv")
    leg_rows = _csv_rows(folder / "pe-shadow-legs.csv")
    if not summaries:
        return []

    accepted_times = _accepted_entry_times(accepted_rows, "BEARISH")
    by_index: dict[int, list[dict[str, str]]] = {}
    for row in leg_rows:
        idx = _pe_leg_trade_index(row)
        if idx is not None:
            by_index.setdefault(idx, []).append(row)

    # Some older leg files may omit the linking column. In that case, preserve
    # causal ordering and consume exactly five rows per complete trade. This is
    # not a strike/price fallback; it is only a row-grouping compatibility path.
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

        legs = [_pe_leg(x, session_date) for x in raw_legs]
        legs.sort(key=lambda x: 99 if x["relation_to_atm"] is None else x["relation_to_atm"])

        status = str(summary.get("status") or "INCOMPLETE")
        complete_legs = _int(summary.get("complete_legs")) or 0
        issue = summary.get("issue") or None

        entry_event = summary.get("entry_event") or None
        exit_event = summary.get("exit_event") or None

        out.append({
            "direction": "BEARISH",
            "option_side": "PE",
            "signal_bar": f"{session_date}T{entry_time}:00+05:30" if entry_time else None,
            "signal_boundary": legs[0].get("entry_timestamp") if legs else None,
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
            "historical_source": "DIRECTIONAL_PE_HISTORICAL_SHADOW",
        })
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
    bullish = _bullish_trades(session_date, accepted)
    bearish = _bearish_trades(session_date, accepted)
    trades = bullish + bearish

    def sort_key(t: dict[str, Any]) -> str:
        return str(t.get("signal_bar") or t.get("signal_boundary") or "")

    trades.sort(key=sort_key)

    active = [t for t in trades if str(t.get("status") or "").upper() == "ACTIVE"]
    complete = [t for t in trades if bool(t.get("complete"))]
    pending = [
        t for t in trades
        if str(t.get("status") or "").upper() == "PENDING_EXACT_EXIT"
    ]
    incomplete = [
        t for t in trades
        if str(t.get("status") or "").upper() != "ACTIVE" and not bool(t.get("complete"))
    ]

    accepted_bullish = sum(
        1 for r in accepted if str(r.get("direction") or "").upper() == "BULLISH"
    )
    accepted_bearish = sum(
        1 for r in accepted if str(r.get("direction") or "").upper() == "BEARISH"
    )

    return {
        "model": "HILEGA_DIRECTIONAL_HISTORICAL_DASHBOARD_V1",
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
            "Bullish CE uses canonical recorded replay lifecycle; bearish PE uses "
            "the recorded directional PE historical shadow. Missing evidence is "
            "left unavailable and is never synthesized."
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
