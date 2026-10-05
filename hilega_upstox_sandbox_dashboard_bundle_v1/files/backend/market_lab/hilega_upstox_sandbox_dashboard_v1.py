"""Read-only Hilega Upstox Sandbox dashboard projection."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from .hilega_upstox_sandbox_execution_v1 import SandboxConfig, UpstoxTransport
from .hilega_upstox_sandbox_live_worker_v1 import (
    DEFAULT_CONTROL,
    DEFAULT_DISPATCH,
    DEFAULT_PID,
    DispatchStore,
    JsonControl,
)

router = APIRouter(
    prefix="/api/live-shadow/hilega-upstox-sandbox", tags=["hilega-upstox-sandbox"]
)
IST = ZoneInfo("Asia/Kolkata")


def _pid_running(path: Path = DEFAULT_PID) -> bool:
    try:
        pid = int(path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _terminal_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [row for row in rows if row.get("terminal") is True]


def _price_index(config: SandboxConfig) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in _terminal_rows(config.journal_path):
        value = row.get("observed_option_price")
        if row.get("event_id") and value is not None:
            result[str(row["event_id"])] = float(value)
    return result


def _current_quote(config: SandboxConfig, instrument_key: str | None) -> tuple[float | None, str | None]:
    if not instrument_key or not config.analytics_token:
        return None, None
    try:
        value = UpstoxTransport(config.analytics_token, config.sandbox_token).instrument_ltp(
            instrument_key
        )
        return value, datetime.now(IST).isoformat()
    except Exception:
        return None, None


def build_dashboard(
    control_path: Path = DEFAULT_CONTROL,
    dispatch_path: Path = DEFAULT_DISPATCH,
    env_path: Path = Path(".env"),
    pid_path: Path = DEFAULT_PID,
) -> dict[str, Any]:
    control = JsonControl(control_path).read()
    store = DispatchStore(dispatch_path)
    day = str(control.get("session_date") or datetime.now(IST).date().isoformat())
    rows = store.accepted_orders(day)
    prices = _price_index(SandboxConfig.from_env(env_path))
    by_trade: dict[str, dict[str, Any]] = {}
    blocked = [
        row for row in store.rows()
        if row.get("session_date") == day and row.get("status") not in {"ACCEPTED"}
    ]
    for row in rows:
        trade = by_trade.setdefault(str(row["trade_id"]), {"entry": None, "exit": None})
        trade[str(row["event_type"]).lower()] = row

    config = SandboxConfig.from_env(env_path)
    trades = []
    for trade_id, pair in by_trade.items():
        entry, exit_row = pair["entry"], pair["exit"]
        if not entry:
            continue
        entry_price = prices.get(str(entry.get("event_id")))
        exit_price = prices.get(str((exit_row or {}).get("event_id")))
        current_price, quote_at = (None, None)
        if not exit_row:
            current_price, quote_at = _current_quote(config, entry.get("instrument_key"))
        mark = exit_price if exit_row else current_price
        quantity = int(entry.get("quantity") or 0)
        points = mark - entry_price if mark is not None and entry_price is not None else None
        pnl = points * quantity if points is not None else None
        trades.append({
            "trade_id": trade_id,
            "strategy_id": entry.get("strategy_id") or control.get("strategy_id"),
            "status": "CLOSED" if exit_row else "OPEN",
            "direction": entry.get("direction"),
            "option_type": entry.get("option_type"),
            "instrument_key": entry.get("instrument_key"),
            "strike": entry.get("strike"),
            "expiry": entry.get("expiry"),
            "quantity": quantity,
            "entry_signal_time": entry.get("event_timestamp"),
            "exit_signal_time": (exit_row or {}).get("event_timestamp"),
            "entry_time": entry.get("timestamp"),
            "exit_time": (exit_row or {}).get("timestamp"),
            "entry_order_id": entry.get("broker_order_id"),
            "exit_order_id": (exit_row or {}).get("broker_order_id"),
            "entry_reference_price": entry_price,
            "exit_reference_price": exit_price,
            "current_option_ltp": current_price,
            "quote_timestamp": quote_at,
            "estimated_points": points,
            "estimated_pnl_rupees": pnl,
            "estimate_only": True,
        })

    closed = [x for x in trades if x["status"] == "CLOSED" and x["estimated_pnl_rupees"] is not None]
    opened = [x for x in trades if x["status"] == "OPEN"]
    closed_pnl = sum(x["estimated_pnl_rupees"] for x in closed)
    open_pnl = sum(x["estimated_pnl_rupees"] for x in opened if x["estimated_pnl_rupees"] is not None)
    gross_profit = sum(max(0.0, x["estimated_pnl_rupees"]) for x in closed)
    gross_loss = abs(sum(min(0.0, x["estimated_pnl_rupees"]) for x in closed))
    wins = sum(x["estimated_pnl_rupees"] > 0 for x in closed)
    losses = sum(x["estimated_pnl_rupees"] < 0 for x in closed)
    active_strategy = os.getenv("LIVE_SHADOW_STRATEGY", "HILEGA_DIRECTIONAL_SHADOW_V1")
    armed_strategy = str(control.get("strategy_id") or active_strategy)
    return {
        "model": "HILEGA_UPSTOX_SANDBOX_DASHBOARD_V1",
        "strategy": {
            "active_strategy_id": active_strategy,
            "armed_strategy_id": armed_strategy,
            "strategy_match": active_strategy == armed_strategy,
            "mode": "LIVE_SHADOW_UPSTOX_SANDBOX",
        },
        "worker": {
            **control,
            "running": _pid_running(pid_path),
            "accepted_orders": len(rows),
            "orders_remaining": max(0, int(control.get("max_orders") or 0) - len(rows)),
        },
        "pnl": {
            "closed_estimated_rupees": closed_pnl,
            "open_estimated_rupees": open_pnl,
            "total_estimated_rupees": closed_pnl + open_pnl,
            "gross_profit_rupees": gross_profit,
            "gross_loss_rupees": gross_loss,
            "gain_loss_ratio": gross_profit / gross_loss if gross_loss else None,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": wins * 100 / (wins + losses) if wins + losses else None,
        },
        "active_trade": opened[0] if opened else None,
        "completed_trades": sorted(closed, key=lambda x: str(x["exit_time"]), reverse=True),
        "blocked_events": blocked[-50:][::-1],
        "last_refresh": datetime.now(IST).isoformat(),
        "safety": {"sandbox_only": True, "live_execution_enabled": False},
        "warning": "P&L uses observed option quotes, not confirmed broker fills.",
    }


@router.get("/dashboard")
def dashboard():
    return build_dashboard()
