from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Mapping, Sequence


SOURCE_VERSION = "ACCOUNT-CONTEXT-SOURCE-V1"
_OPEN_STATES = {"OPEN", "ACTIVE", "FILLED", "ENTRY_FILLED", "PARTIALLY_FILLED"}
_CLOSED_STATES = {"CLOSED", "COMPLETED", "EXITED", "FILLED_EXIT", "CLOSED_PROFIT", "CLOSED_LOSS"}
_PENDING_STATES = {"PENDING", "QUEUED", "ADMITTED", "APPROVED", "RESERVED", "SUBMITTED"}


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ready", "active", "connected"}:
        return True
    if text in {"0", "false", "no", "off", "inactive", "disconnected", "not_ready"}:
        return False
    return None


def _first(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _status(row: Mapping[str, object]) -> str:
    return str(_first(row, "position_status", "trade_status", "order_status", "status") or "").upper()


def _safe_call(database, methods: Sequence[str], *args) -> tuple[object | None, str | None, str | None]:
    if database is None:
        return None, None, "DATABASE_UNAVAILABLE"
    for method in methods:
        reader = getattr(database, method, None)
        if reader is None:
            continue
        try:
            return reader(*args), method, None
        except TypeError:
            try:
                return reader(), method, None
            except Exception as exc:
                return None, method, f"{method}:{type(exc).__name__}"
        except Exception as exc:
            return None, method, f"{method}:{type(exc).__name__}"
    return None, None, "NO_SUPPORTED_READER"


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, Mapping):
                return dict(item)
    return {}


def _rows(value: object) -> list[dict[str, object]]:
    if isinstance(value, Mapping):
        for key in ("rows", "orders", "positions", "items", "records"):
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                return [dict(row) for row in nested if isinstance(row, Mapping)]
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _quantity(row: Mapping[str, object]) -> float | None:
    direct = _number(_first(row, "quantity", "filled_quantity", "qty"))
    if direct is not None:
        return abs(direct)
    lots = _number(_first(row, "lots", "lot_count", "proposed_lots"))
    lot_size = _number(_first(row, "lot_size", "contract_lot_size"))
    return abs(lots * lot_size) if lots is not None and lot_size is not None else None


def _price(row: Mapping[str, object], *names: str) -> float | None:
    return _number(_first(row, *names))


def _exposure(row: Mapping[str, object]) -> float | None:
    quantity = _quantity(row)
    price = _price(row, "current_price", "ltp", "last_price", "entry_price", "average_entry_price")
    return quantity * price if quantity is not None and price is not None else None


def _realized_pnl(row: Mapping[str, object]) -> float | None:
    direct = _number(_first(row, "realized_pnl", "net_pnl", "pnl", "profit_loss"))
    if direct is not None:
        return direct
    quantity = _quantity(row)
    entry = _price(row, "entry_price", "average_entry_price", "filled_entry_price")
    exit_price = _price(row, "exit_price", "average_exit_price", "filled_exit_price")
    return (exit_price - entry) * quantity if None not in (quantity, entry, exit_price) else None


def _unrealized_pnl(row: Mapping[str, object]) -> float | None:
    direct = _number(_first(row, "unrealized_pnl", "mtm", "mark_to_market"))
    if direct is not None:
        return direct
    quantity = _quantity(row)
    entry = _price(row, "entry_price", "average_entry_price", "filled_entry_price")
    current = _price(row, "current_price", "ltp", "last_price")
    return (current - entry) * quantity if None not in (quantity, entry, current) else None


def _contract_key(row: Mapping[str, object]) -> str:
    exchange = str(_first(row, "exchange", "exchange_segment") or "").upper()
    token = str(_first(row, "instrument_token", "instrument_key", "security_id") or "")
    if exchange and token:
        return f"{exchange}|{token}"
    symbol = str(_first(row, "trading_symbol", "tradingsymbol", "symbol") or "")
    return symbol


def _active_position(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "strategy_id": _first(row, "strategy_id", "source_strategy_id", "strategy"),
        "bundle_id": _first(row, "bundle_id", "source_bundle_id"),
        "candidate_id": _first(row, "candidate_id", "source_candidate_id"),
        "identity_key": _first(row, "identity_key", "candidate_identity_key"),
        "exchange": _first(row, "exchange", "exchange_segment"),
        "instrument_token": _first(row, "instrument_token", "security_id"),
        "instrument_key": _first(row, "instrument_key"),
        "trading_symbol": _first(row, "trading_symbol", "tradingsymbol", "symbol"),
        "contract_side": _first(row, "contract_side", "option_side", "side"),
        "expiry": _first(row, "expiry", "expiry_date"),
        "strike": _number(_first(row, "strike", "strike_price")),
        "quantity": _quantity(row),
        "exposure": _exposure(row),
        "unrealized_pnl": _unrealized_pnl(row),
        "contract_exposure_key": _contract_key(row),
        "source_read_only": True,
    }


def build_account_context_from_rows(
    orders: Sequence[Mapping[str, object]] | None,
    *,
    account_snapshot: Mapping[str, object] | None = None,
    risk_settings: Mapping[str, object] | None = None,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Normalize paper account state without mutating the source rows."""
    rows = [dict(row) for row in (orders or [])]
    snapshot = dict(account_snapshot or {})
    settings = dict(risk_settings or {})
    open_rows = [row for row in rows if _status(row) in _OPEN_STATES]
    closed_rows = [row for row in rows if _status(row) in _CLOSED_STATES]
    pending_rows = [row for row in rows if _status(row) in _PENDING_STATES]
    active_positions = [_active_position(row) for row in open_rows]

    realized_values = [_realized_pnl(row) for row in closed_rows]
    unrealized_values = [_unrealized_pnl(row) for row in open_rows]
    exposures = [_exposure(row) for row in open_rows]
    pending_exposures = [_exposure(row) for row in pending_rows]

    fields: dict[str, dict[str, object]] = {}

    def put(name: str, value: object, source: str, authoritative: bool) -> None:
        fields[name] = {
            "value": value,
            "source": source,
            "authoritative": authoritative,
            "evaluated_at": evaluated_at,
        }

    available_cash = _number(_first(snapshot, "available_cash", "cash_available", "available_balance", "free_cash"))
    put("available_cash", available_cash, "ACCOUNT_SNAPSHOT" if available_cash is not None else "UNAVAILABLE", available_cash is not None)

    daily_realized = _number(_first(snapshot, "daily_realized_pnl", "realized_pnl_today"))
    if daily_realized is None and any(value is not None for value in realized_values):
        daily_realized = sum(value or 0.0 for value in realized_values)
        realized_source = "PAPER_EXECUTION_ORDERS_DERIVED"
    else:
        realized_source = "ACCOUNT_SNAPSHOT" if daily_realized is not None else "UNAVAILABLE"
    put("daily_realized_pnl", daily_realized, realized_source, daily_realized is not None)

    daily_unrealized = _number(_first(snapshot, "daily_unrealized_pnl", "unrealized_pnl", "mtm"))
    if daily_unrealized is None and any(value is not None for value in unrealized_values):
        daily_unrealized = sum(value or 0.0 for value in unrealized_values)
        unrealized_source = "PAPER_EXECUTION_ORDERS_DERIVED"
    else:
        unrealized_source = "ACCOUNT_SNAPSHOT" if daily_unrealized is not None else "UNAVAILABLE"
    put("daily_unrealized_pnl", daily_unrealized, unrealized_source, daily_unrealized is not None)

    portfolio_exposure = _number(_first(snapshot, "portfolio_exposure", "gross_exposure"))
    if portfolio_exposure is None and any(value is not None for value in exposures):
        portfolio_exposure = sum(value or 0.0 for value in exposures)
        exposure_source = "PAPER_EXECUTION_ORDERS_DERIVED"
    else:
        exposure_source = "ACCOUNT_SNAPSHOT" if portfolio_exposure is not None else "UNAVAILABLE"
    put("portfolio_exposure", portfolio_exposure, exposure_source, portfolio_exposure is not None)

    reserved_capital = _number(_first(snapshot, "reserved_capital", "blocked_capital"))
    if reserved_capital is None and any(value is not None for value in pending_exposures):
        reserved_capital = sum(value or 0.0 for value in pending_exposures)
        reserved_source = "PAPER_EXECUTION_ORDERS_DERIVED"
    else:
        reserved_source = "ACCOUNT_SNAPSHOT" if reserved_capital is not None else "UNAVAILABLE"
    put("reserved_capital", reserved_capital, reserved_source, reserved_capital is not None)

    values = {
        "available_cash": available_cash,
        "daily_realized_pnl": daily_realized,
        "daily_unrealized_pnl": daily_unrealized,
        "portfolio_exposure": portfolio_exposure,
        "reserved_capital": reserved_capital,
        "open_positions": len(open_rows),
        "active_positions": active_positions,
        "open_position_identity_keys": [
            str(row.get("identity_key")) for row in active_positions
            if row.get("identity_key") not in (None, "")
        ],
        "open_contract_exposure_keys": [
            str(row.get("contract_exposure_key")) for row in active_positions
            if row.get("contract_exposure_key") not in (None, "")
        ],
    }
    put("open_positions", len(open_rows), "PAPER_EXECUTION_ORDERS", True)
    put("active_positions", active_positions, "PAPER_EXECUTION_ORDERS", True)

    aliases = {
        "daily_loss_limit": ("daily_loss_limit", "maximum_daily_loss"),
        "maximum_portfolio_exposure": ("maximum_portfolio_exposure", "max_portfolio_exposure"),
        "maximum_open_positions": ("maximum_open_positions", "max_open_positions"),
        "maximum_risk_per_trade": ("maximum_risk_per_trade", "max_risk_per_trade"),
        "proposed_lots": ("proposed_lots", "default_lots"),
        "broker_ready": ("broker_ready", "broker_connected"),
        "account_ready": ("account_ready", "trading_enabled"),
        "emergency_stop": ("emergency_stop", "kill_switch", "trading_halted"),
        "global_cooldown_active": ("global_cooldown_active", "cooldown_active"),
    }
    for target, names in aliases.items():
        raw = _first(snapshot, *names)
        source = "ACCOUNT_SNAPSHOT"
        if raw in (None, ""):
            raw = _first(settings, *names)
            source = "RISK_SETTINGS"
        value = _bool(raw) if target in {"broker_ready", "account_ready", "emergency_stop", "global_cooldown_active"} else _number(raw)
        values[target] = value
        put(target, value, source if value is not None else "UNAVAILABLE", value is not None)

    strategy_risk = settings.get("strategy_risk") if isinstance(settings.get("strategy_risk"), Mapping) else {}
    strategy_cooldowns = settings.get("strategy_cooldowns") if isinstance(settings.get("strategy_cooldowns"), Mapping) else {}
    values["strategy_risk"] = dict(strategy_risk)
    values["strategy_cooldowns"] = dict(strategy_cooldowns)
    put("strategy_risk", dict(strategy_risk), "RISK_SETTINGS" if strategy_risk else "UNAVAILABLE", bool(strategy_risk))
    put("strategy_cooldowns", dict(strategy_cooldowns), "RISK_SETTINGS" if strategy_cooldowns else "UNAVAILABLE", bool(strategy_cooldowns))

    required = ("available_cash", "daily_loss_limit", "maximum_portfolio_exposure", "maximum_open_positions")
    present = sum(values.get(name) is not None for name in required)
    status = "READY" if present == len(required) else "PARTIAL" if present or open_rows or closed_rows else "UNAVAILABLE"
    return {
        **values,
        "context_status": status,
        "context_source_version": SOURCE_VERSION,
        "context_evaluated_at": evaluated_at,
        "field_provenance": fields,
        "raw_order_count": len(rows),
        "source_read_only": True,
        "execution_allowed": False,
    }


def load_account_risk_context(database, *, account_id: str = "PAPER-STD") -> dict[str, object]:
    """Load the best available paper account state through read-only database APIs."""
    evaluated_at = datetime.now(timezone.utc).isoformat()
    raw_orders, orders_reader, orders_error = _safe_call(database, ("read_paper_execution_orders",), account_id)
    snapshot_raw, snapshot_reader, snapshot_error = _safe_call(
        database,
        ("read_paper_account_state", "read_paper_account", "read_account_snapshot", "read_trading_account_state"),
        account_id,
    )
    settings_raw, settings_reader, settings_error = _safe_call(
        database,
        ("read_risk_settings", "read_account_risk_settings", "read_paper_risk_settings"),
        account_id,
    )
    result = build_account_context_from_rows(
        _rows(raw_orders),
        account_snapshot=_mapping(snapshot_raw),
        risk_settings=_mapping(settings_raw),
        evaluated_at=evaluated_at,
    )
    result["source_readers"] = {
        "orders": orders_reader,
        "account_snapshot": snapshot_reader,
        "risk_settings": settings_reader,
    }
    result["source_errors"] = [
        error for error in (orders_error, snapshot_error, settings_error)
        if error and error != "NO_SUPPORTED_READER"
    ]
    return result


def merge_account_context(
    discovered: Mapping[str, object] | None,
    explicit: Mapping[str, object] | None,
) -> dict[str, object]:
    """Overlay deliberate caller values while retaining adapter provenance."""
    result = dict(discovered or {})
    overrides = dict(explicit or {})
    provenance = dict(result.get("field_provenance") or {})
    for key, value in overrides.items():
        result[key] = value
        provenance[key] = {
            "value": value,
            "source": "EXPLICIT_CALLER_OVERRIDE",
            "authoritative": True,
            "evaluated_at": result.get("context_evaluated_at"),
        }
    result["field_provenance"] = provenance
    result["explicit_override_count"] = len(overrides)
    return result
