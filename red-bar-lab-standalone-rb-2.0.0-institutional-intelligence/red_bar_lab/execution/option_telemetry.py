from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha1
from time import perf_counter
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"
RED_BAR_STRATEGY_SOURCES = frozenset({"RED_BAR", "RED_BAR_V2"})
SUPPORTED_TELEMETRY_SOURCES = frozenset(
    {RSI_STRATEGY_SOURCE, *RED_BAR_STRATEGY_SOURCES}
)
ACTIVE_ORDER_STATES = frozenset(
    {"OPEN", "ACTIVE", "FILLED", "PARTIALLY_FILLED"}
)
OBSERVATIONAL_AUTHORITY = "OBSERVATIONAL_ONLY"

# Paper orders persist a human-readable underlying name but older rows do not
# carry an Upstox underlying instrument key. Keep explicit keys authoritative
# and use this narrow compatibility map only when they are absent.
UNDERLYING_NAME_TO_INSTRUMENT_KEY = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "NIFTY 50": "NSE_INDEX|Nifty 50",
}

_STRIKE_OI_COLUMNS = {
    "call_oi_at_strike": "REAL",
    "put_oi_at_strike": "REAL",
}


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_level(depth: object, side: str) -> dict[str, object]:
    if not isinstance(depth, dict):
        return {}
    levels = depth.get(side) or []
    if not levels or not isinstance(levels[0], dict):
        return {}
    return levels[0]


def _strategy_source(order: Mapping[str, object]) -> str:
    return str(
        order.get("execution_strategy_source")
        or order.get("strategy_source")
        or order.get("strategy_id")
        or ""
    ).strip().upper()


def _is_active_order(order: Mapping[str, object]) -> bool:
    state = str(
        order.get("status") or order.get("state") or ""
    ).strip().upper()
    return not state or state in ACTIVE_ORDER_STATES


def _underlying_key(order: Mapping[str, object]) -> str:
    explicit_key = str(
        order.get("underlying_instrument_key")
        or order.get("underlying_key")
        or order.get("spot_instrument_key")
        or ""
    ).strip()
    if explicit_key:
        return explicit_key

    underlying_name = " ".join(
        str(order.get("underlying_name") or "").strip().upper().split()
    )
    return UNDERLYING_NAME_TO_INSTRUMENT_KEY.get(underlying_name, "")


def _database_path(database) -> str:
    value = getattr(database, "path", None)
    return str(value) if value else ""


def _ensure_strike_oi_columns(database) -> bool:
    """Add strike-level OI columns to an existing SQLite telemetry table.

    RedBarDatabase remains backward compatible because the migration is
    additive and guarded by PRAGMA inspection. Test doubles and alternative
    database adapters without a filesystem path are intentionally ignored.
    """

    path = _database_path(database)
    if not path:
        return False

    initialize = getattr(database, "initialize", None)
    if callable(initialize):
        initialize()

    with sqlite3.connect(path) as conn:
        existing = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(option_execution_telemetry)"
            )
        }
        if not existing:
            return False
        changed = False
        for name, definition in _STRIKE_OI_COLUMNS.items():
            if name not in existing:
                conn.execute(
                    "ALTER TABLE option_execution_telemetry "
                    f"ADD COLUMN {name} {definition}"
                )
                changed = True
        conn.commit()
    return changed


def _persist_strike_oi(
    database,
    *,
    telemetry_id: str,
    call_oi: object,
    put_oi: object,
) -> bool:
    """Persist exact selected-strike Call and Put OI after the base insert."""

    path = _database_path(database)
    if not path:
        return False

    _ensure_strike_oi_columns(database)
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            """
            UPDATE option_execution_telemetry
            SET call_oi_at_strike=?, put_oi_at_strike=?
            WHERE telemetry_id=?
            """,
            (_num(call_oi), _num(put_oi), telemetry_id),
        )
        conn.commit()
    return cursor.rowcount > 0


def _chain_rows(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, Mapping)]
    rows = payload.get("rows") or payload.get("option_chain") or []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _option_node(
    row: Mapping[str, object], side: str
) -> dict[str, object]:
    aliases = (
        ("call_options", "call", "ce")
        if side == "CE"
        else ("put_options", "put", "pe")
    )
    for name in aliases:
        node = row.get(name)
        if isinstance(node, Mapping):
            return dict(node)
    return {}


def _market_data(node: Mapping[str, object]) -> dict[str, object]:
    value = node.get("market_data") or node.get("marketData") or node
    return dict(value) if isinstance(value, Mapping) else {}


def _greeks(node: Mapping[str, object]) -> dict[str, object]:
    value = (
        node.get("option_greeks")
        or node.get("optionGreeks")
        or node.get("greeks")
        or {}
    )
    return dict(value) if isinstance(value, Mapping) else {}


def _strike_context(
    rows: Sequence[Mapping[str, object]],
    strike: object,
    option_type: object,
) -> dict[str, object]:
    target = _num(strike)
    if target is None:
        return {}

    matched: Mapping[str, object] | None = None
    for row in rows:
        candidate = _num(row.get("strike_price") or row.get("strike"))
        if candidate is not None and abs(candidate - target) < 0.001:
            matched = row
            break
    if matched is None:
        return {}

    call_node = _option_node(matched, "CE")
    put_node = _option_node(matched, "PE")
    call_market = _market_data(call_node)
    put_market = _market_data(put_node)
    call_oi = _num(call_market.get("oi") or call_node.get("oi"))
    put_oi = _num(put_market.get("oi") or put_node.get("oi"))
    pcr = _num(matched.get("pcr"))
    if pcr is None and call_oi not in (None, 0.0) and put_oi is not None:
        pcr = put_oi / call_oi

    side = str(option_type or "").upper()
    selected = call_node if side in {"CE", "CALL"} else put_node
    selected_greeks = _greeks(selected)
    selected_market = _market_data(selected)
    return {
        "call_oi": call_oi,
        "put_oi": put_oi,
        "pcr_oi": pcr,
        "pcr_source": (
            "OPTION_CHAIN_ROW" if pcr is not None else "NOT_AVAILABLE"
        ),
        "delta": _num(selected_greeks.get("delta")),
        "gamma": _num(selected_greeks.get("gamma")),
        "theta": _num(selected_greeks.get("theta")),
        "vega": _num(selected_greeks.get("vega")),
        "iv": _num(
            selected_greeks.get("iv") or selected_market.get("iv")
        ),
    }


def classify_option_support(
    *, premium_return_pct, oi_change, relative_volume, spread_pct
):
    available = [
        value
        for value in (
            premium_return_pct,
            oi_change,
            relative_volume,
            spread_pct,
        )
        if value is not None
    ]
    if not available:
        return "NOT_AVAILABLE", (
            "No usable premium/OI/volume/spread evidence."
        )

    reasons: list[str] = []
    supportive = 0
    conflicting = 0
    if premium_return_pct is not None:
        if premium_return_pct > 0:
            supportive += 1
            reasons.append("PREMIUM_POSITIVE")
        elif premium_return_pct < 0:
            conflicting += 1
            reasons.append("PREMIUM_NEGATIVE")
        else:
            reasons.append("PREMIUM_FLAT")
    if oi_change is not None:
        if oi_change > 0:
            supportive += 1
            reasons.append("OI_BUILDUP")
        elif oi_change < 0:
            reasons.append("OI_UNWINDING")
        else:
            reasons.append("OI_FLAT")
    if relative_volume is not None:
        if relative_volume >= 1.2:
            supportive += 1
            reasons.append("VOLUME_EXPANSION")
        elif relative_volume < 0.7:
            conflicting += 1
            reasons.append("VOLUME_WEAK")
        else:
            reasons.append("VOLUME_NORMAL")
    if spread_pct is not None:
        if spread_pct > 2.0:
            conflicting += 1
            reasons.append("SPREAD_WIDE")
        else:
            reasons.append("SPREAD_ACCEPTABLE")

    if supportive >= 2 and conflicting == 0:
        classification = "SUPPORTED"
    elif conflicting >= 2 and supportive == 0:
        classification = "CONFLICT"
    else:
        classification = "NEUTRAL"
    return classification, "|".join(reasons)


@dataclass(frozen=True)
class TelemetryCaptureResult:
    captured: int
    skipped: int
    errors: tuple[str, ...]
    option_chain_calls: int = 0
    option_chain_cache_hits: int = 0
    cycle_duration_ms: float = 0.0


class OptionExecutionTelemetryService:
    """Capture observational option telemetry without execution authority."""

    def __init__(
        self,
        database,
        *,
        account_id: str,
        chain_cache_seconds: int = 45,
    ):
        self.database = database
        self.account_id = str(account_id)
        self.chain_cache_seconds = max(5, int(chain_cache_seconds))
        self._chain_cache: dict[
            tuple[str, str],
            tuple[datetime, list[dict[str, object]]],
        ] = {}

    def _fetch_chain(
        self,
        market_data,
        *,
        underlying_key: str,
        expiry: str,
        observed: datetime,
    ):
        cache_key = (underlying_key, expiry)
        cached = self._chain_cache.get(cache_key)
        if (
            cached
            and observed - cached[0]
            <= timedelta(seconds=self.chain_cache_seconds)
        ):
            return cached[1], False, True

        method = getattr(market_data, "option_chain", None) or getattr(
            market_data, "get_option_chain", None
        )
        if not callable(method) or not underlying_key or not expiry:
            return [], False, False
        try:
            try:
                payload = method(underlying_key, expiry)
            except TypeError:
                payload = method(
                    instrument_key=underlying_key,
                    expiry_date=expiry,
                )
            rows = _chain_rows(payload)
            self._chain_cache[cache_key] = (observed, rows)
            return rows, True, False
        except Exception:
            return [], True, False

    def capture(
        self,
        *,
        market_data,
        now: datetime | None = None,
    ) -> TelemetryCaptureResult:
        started = perf_counter()
        observed = (now or datetime.now(IST)).astimezone(IST)
        captured = 0
        skipped = 0
        errors: list[str] = []
        chain_calls = 0
        chain_hits = 0

        try:
            _ensure_strike_oi_columns(self.database)
        except Exception as exc:
            errors.append(
                f"STRIKE_OI_SCHEMA:{type(exc).__name__}:{exc}"
            )

        orders = self.database.read_paper_execution_orders(self.account_id)
        active_orders = [
            dict(order)
            for order in orders
            if _strategy_source(order) in SUPPORTED_TELEMETRY_SOURCES
            and _is_active_order(order)
        ]
        if not active_orders:
            return TelemetryCaptureResult(
                0,
                0,
                tuple(errors),
                cycle_duration_ms=(perf_counter() - started) * 1000.0,
            )

        keys = list(
            dict.fromkeys(
                f"{order.get('exchange')}:{order.get('tradingsymbol')}"
                for order in active_orders
                if order.get("exchange") and order.get("tradingsymbol")
            )
        )
        try:
            quotes = market_data.quote(keys) if keys else {}
        except Exception as exc:
            return TelemetryCaptureResult(
                0,
                len(active_orders),
                tuple(errors)
                + (f"QUOTE_BATCH:{type(exc).__name__}:{exc}",),
                cycle_duration_ms=(perf_counter() - started) * 1000.0,
            )

        chain_by_group: dict[
            tuple[str, str], list[dict[str, object]]
        ] = {}
        for order in active_orders:
            group = (
                _underlying_key(order),
                str(order.get("expiry") or ""),
            )
            if not all(group) or group in chain_by_group:
                continue
            rows, called, cache_hit = self._fetch_chain(
                market_data,
                underlying_key=group[0],
                expiry=group[1],
                observed=observed,
            )
            chain_by_group[group] = rows
            chain_calls += int(called)
            chain_hits += int(cache_hit)

        for order in active_orders:
            try:
                order_id = str(order.get("order_id") or "")
                key = (
                    f"{order.get('exchange')}:"
                    f"{order.get('tradingsymbol')}"
                )
                quote = quotes.get(key) or {}
                if not order_id or not quote:
                    skipped += 1
                    continue

                latest = (
                    self.database.read_latest_option_execution_telemetry(
                        order_id
                    )
                )
                current_price = _num(
                    quote.get("last_price"),
                    _num(order.get("current_price")),
                )
                entry_price = _num(order.get("entry_price"))
                volume = _num(quote.get("volume"))
                oi = _num(quote.get("oi"))
                previous_volume = _num((latest or {}).get("volume"))
                previous_oi = _num((latest or {}).get("oi"))
                volume_change = (
                    volume - previous_volume
                    if volume is not None and previous_volume is not None
                    else None
                )
                oi_change = (
                    oi - previous_oi
                    if oi is not None and previous_oi is not None
                    else None
                )
                oi_change_pct = (
                    oi_change / previous_oi * 100.0
                    if oi_change is not None
                    and previous_oi not in (None, 0.0)
                    else None
                )
                premium_return_pct = (
                    (current_price - entry_price)
                    / entry_price
                    * 100.0
                    if current_price is not None
                    and entry_price not in (None, 0.0)
                    else None
                )
                depth = quote.get("depth") or {}
                bid = _first_level(depth, "buy")
                ask = _first_level(depth, "sell")
                best_bid = _num(bid.get("price"))
                best_ask = _num(ask.get("price"))
                spread_points = (
                    best_ask - best_bid
                    if best_ask is not None and best_bid is not None
                    else None
                )
                midpoint = (
                    (best_ask + best_bid) / 2.0
                    if best_ask is not None and best_bid is not None
                    else None
                )
                spread_pct = (
                    spread_points / midpoint * 100.0
                    if spread_points is not None
                    and midpoint not in (None, 0.0)
                    else None
                )
                relative_volume = (
                    volume / previous_volume
                    if volume is not None
                    and previous_volume not in (None, 0.0)
                    else None
                )
                classification, reason = classify_option_support(
                    premium_return_pct=premium_return_pct,
                    oi_change=oi_change,
                    relative_volume=relative_volume,
                    spread_pct=spread_pct,
                )
                group = (
                    _underlying_key(order),
                    str(order.get("expiry") or ""),
                )
                chain = _strike_context(
                    chain_by_group.get(group, []),
                    order.get("strike"),
                    order.get("option_type"),
                )
                strategy_source = _strategy_source(order)
                raw_id = (
                    f"{order_id}|{observed.isoformat()}|"
                    f"{quote.get('last_price')}|{quote.get('oi')}|"
                    f"{quote.get('volume')}"
                )
                telemetry_id = (
                    "OT-"
                    + sha1(raw_id.encode("utf-8")).hexdigest()[:20].upper()
                )
                self.database.insert_option_execution_telemetry(
                    {
                        "telemetry_id": telemetry_id,
                        "order_id": order_id,
                        "signal_id": order.get("signal_id"),
                        "execution_strategy_source": strategy_source,
                        "observed_timestamp": observed.isoformat(),
                        "exchange": order.get("exchange"),
                        "tradingsymbol": order.get("tradingsymbol"),
                        "instrument_token": order.get("instrument_token"),
                        "option_type": order.get("option_type"),
                        "strike": order.get("strike"),
                        "expiry": order.get("expiry"),
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "premium_return_pct": premium_return_pct,
                        "volume": volume,
                        "volume_change": volume_change,
                        "relative_volume": relative_volume,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_change_pct,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_points": spread_points,
                        "spread_pct": spread_pct,
                        "buy_quantity": _num(
                            quote.get("buy_quantity")
                        ),
                        "sell_quantity": _num(
                            quote.get("sell_quantity")
                        ),
                        "iv": (
                            chain.get("iv")
                            if chain.get("iv") is not None
                            else _num(quote.get("iv"))
                        ),
                        "delta": (
                            chain.get("delta")
                            if chain.get("delta") is not None
                            else _num(quote.get("delta"))
                        ),
                        "gamma": (
                            chain.get("gamma")
                            if chain.get("gamma") is not None
                            else _num(quote.get("gamma"))
                        ),
                        "theta": (
                            chain.get("theta")
                            if chain.get("theta") is not None
                            else _num(quote.get("theta"))
                        ),
                        "vega": (
                            chain.get("vega")
                            if chain.get("vega") is not None
                            else _num(quote.get("vega"))
                        ),
                        "pcr_oi": chain.get("pcr_oi"),
                        "pcr_source": (
                            chain.get("pcr_source") or "NOT_AVAILABLE"
                        ),
                        "call_oi_at_strike": chain.get("call_oi"),
                        "put_oi_at_strike": chain.get("put_oi"),
                        "support_classification": classification,
                        "support_reason": reason,
                        "authority": OBSERVATIONAL_AUTHORITY,
                        "created_at": observed.isoformat(),
                    }
                )
                _persist_strike_oi(
                    self.database,
                    telemetry_id=telemetry_id,
                    call_oi=chain.get("call_oi"),
                    put_oi=chain.get("put_oi"),
                )
                captured += 1
            except Exception as exc:
                errors.append(
                    f"{order.get('order_id')}:"
                    f"{type(exc).__name__}:{exc}"
                )

        return TelemetryCaptureResult(
            captured,
            skipped,
            tuple(errors),
            option_chain_calls=chain_calls,
            option_chain_cache_hits=chain_hits,
            cycle_duration_ms=(perf_counter() - started) * 1000.0,
        )
