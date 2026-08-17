from __future__ import annotations

import math
from typing import Mapping, Sequence

from red_bar_lab.ui.strategy_history_coverage import build_history_coverage


_SOURCE_VERSION = "PAPER-EXECUTION-HISTORY-ADAPTER-V1"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _first(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _side(value: object) -> str:
    text = str(value or "").upper().replace("BUY", "").strip()
    if text in {"CE", "CALL", "BULLISH"}:
        return "CE"
    if text in {"PE", "PUT", "BEARISH"}:
        return "PE"
    return text


def _status(row: Mapping[str, object]) -> str:
    return str(_first(row, "trade_status", "position_status", "order_status", "status") or "").upper()


def _net_points(row: Mapping[str, object]) -> float | None:
    direct = _number(_first(row, "net_points", "pnl_points", "realized_points", "option_points"))
    if direct is not None:
        return direct
    entry = _number(_first(row, "entry_price", "average_entry_price", "filled_entry_price"))
    exit_price = _number(_first(row, "exit_price", "average_exit_price", "filled_exit_price"))
    if entry is None or exit_price is None:
        return None
    return exit_price - entry


def normalize_completed_trade(row: Mapping[str, object]) -> dict[str, object] | None:
    """Normalize one stored paper trade without changing the source record."""
    source = dict(row)
    points = _net_points(source)
    status = _status(source)
    if status not in {"CLOSED", "COMPLETED", "EXITED", "FILLED_EXIT", "CLOSED_PROFIT", "CLOSED_LOSS"}:
        return None
    if points is None:
        return None
    return {
        "strategy_id": str(_first(source, "strategy_id", "source_strategy_id", "strategy") or ""),
        "strategy_version": _first(source, "strategy_version", "signal_version", "policy_strategy_version"),
        "side": _side(_first(source, "contract_side", "option_side", "side", "direction")),
        "status": "CLOSED",
        "net_points": points,
        "estimated_costs": _number(_first(source, "estimated_costs", "charges_points", "cost_points")) or 0.0,
        "mfe_points": _number(_first(source, "mfe_points", "maximum_favourable_excursion", "max_favourable_points")),
        "mae_points": _number(_first(source, "mae_points", "maximum_adverse_excursion", "max_adverse_points")),
        "setup_type": _first(source, "setup_type", "primary_setup_type", "signal_type"),
        "role": _first(source, "role", "contract_role", "entry_role"),
        "moneyness": _first(source, "moneyness", "moneyness_bucket"),
        "time_of_day_bucket": _first(source, "time_of_day_bucket", "session_bucket"),
        "days_to_expiry_bucket": _first(source, "days_to_expiry_bucket", "dte_bucket"),
        "exit_policy_version": _first(source, "exit_policy_version", "trailing_policy_version"),
        "trade_id": _first(source, "trade_id", "position_id", "order_id", "id"),
        "source_adapter_version": _SOURCE_VERSION,
        "source_read_only": True,
        "execution_allowed": False,
    }


def normalize_completed_trades(rows: Sequence[Mapping[str, object]] | None) -> list[dict[str, object]]:
    normalized = []
    for row in rows or []:
        item = normalize_completed_trade(row)
        if item is not None:
            normalized.append(item)
    return normalized


def _unavailable(reason: str) -> dict[str, object]:
    records: list[dict[str, object]] = []
    return {
        "source_status": "UNAVAILABLE",
        "source_reason": reason,
        "source_adapter_version": _SOURCE_VERSION,
        "records": records,
        "coverage": build_history_coverage(records),
        "source_read_only": True,
    }


def load_completed_trade_history(database, *, account_id: str = "PAPER-STD") -> dict[str, object]:
    """Read completed paper trades through the database's established read API."""
    reader = getattr(database, "read_paper_execution_orders", None) if database is not None else None
    if reader is None:
        return _unavailable("READ_PAPER_EXECUTION_ORDERS_UNAVAILABLE")
    try:
        raw = reader(account_id)
    except TypeError:
        try:
            raw = reader()
        except Exception as exc:
            return _unavailable(f"HISTORY_READ_FAILED:{type(exc).__name__}")
    except Exception as exc:
        return _unavailable(f"HISTORY_READ_FAILED:{type(exc).__name__}")
    raw_rows = [dict(row) for row in (raw or []) if isinstance(row, Mapping)]
    records = normalize_completed_trades(raw_rows)
    return {
        "source_status": "READY" if records else "EMPTY",
        "source_reason": "COMPLETED_TRADES_NORMALIZED" if records else "NO_NORMALIZABLE_COMPLETED_TRADES",
        "source_adapter_version": _SOURCE_VERSION,
        "raw_row_count": len(raw_rows),
        "normalized_row_count": len(records),
        "records": records,
        "coverage": build_history_coverage(records),
        "source_read_only": True,
    }
