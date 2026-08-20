from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
_NOT_AVAILABLE = "—"


def _num(value: object, digits: int = 2) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _money(value: object) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"INR {float(value):+,.2f}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _integer(value: object) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _freshness(timestamp: object, now: datetime | None = None) -> dict[str, object]:
    if not timestamp:
        return {"status": "UNAVAILABLE", "age_seconds": None, "text": "No telemetry snapshot"}
    try:
        observed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=IST)
        current = (now or datetime.now(IST)).astimezone(IST)
        age = max(0, int((current - observed.astimezone(IST)).total_seconds()))
    except (TypeError, ValueError):
        return {"status": "UNAVAILABLE", "age_seconds": None, "text": "Invalid telemetry timestamp"}
    status = "FRESH" if age <= 60 else "STALE"
    text = f"{age}s old" if age < 120 else f"{age // 60}m {age % 60}s old"
    return {"status": status, "age_seconds": age, "text": text}


def build_active_trade_card(
    order: Mapping[str, object],
    telemetry: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Build a read-only selected-trade card from persisted order and telemetry data."""
    item = dict(order)
    snapshot = dict(telemetry or {})
    option_type = str(item.get("option_type") or item.get("side") or "").upper()
    current_pcr = snapshot.get("pcr_oi")
    current_delta = snapshot.get("delta")
    selected_oi = (
        snapshot.get("put_oi_at_strike")
        if option_type in {"PE", "PUT"}
        else snapshot.get("call_oi_at_strike")
    )
    freshness = _freshness(snapshot.get("observed_timestamp"), now)
    action = f"HOLD {option_type}" if option_type in {"CE", "PE"} else "MONITOR"
    return {
        "order_id": str(item.get("order_id") or ""),
        "contract": str(item.get("tradingsymbol") or "Unknown contract"),
        "status": str(item.get("status") or "OPEN").upper(),
        "strategy": str(item.get("execution_strategy_source") or item.get("strategy_source") or "RED_BAR_V2"),
        "option_type": option_type or _NOT_AVAILABLE,
        "strike": item.get("strike"),
        "expiry": item.get("expiry"),
        "quantity": item.get("quantity"),
        "entry_time": item.get("entry_timestamp"),
        "entry_price": item.get("entry_price"),
        "current_price": item.get("current_price"),
        "unrealized_pnl": item.get("unrealized_pnl"),
        "current_pcr": current_pcr,
        "current_delta": current_delta,
        "entry_pcr": None,
        "entry_delta": None,
        "call_oi": snapshot.get("call_oi_at_strike"),
        "put_oi": snapshot.get("put_oi_at_strike"),
        "selected_oi": selected_oi,
        "iv": snapshot.get("iv"),
        "spread_pct": snapshot.get("spread_pct"),
        "best_bid": snapshot.get("best_bid"),
        "best_ask": snapshot.get("best_ask"),
        "telemetry_timestamp": snapshot.get("observed_timestamp"),
        "pcr_source": snapshot.get("pcr_source") or "NOT_AVAILABLE",
        "freshness": freshness,
        "current_action": action,
        "authority": "OBSERVATIONAL ONLY",
        "lifecycle_note": "Entry/exit PCR and Delta will appear after explicit lifecycle snapshots are enabled.",
    }


def _trade_label(order: Mapping[str, object]) -> str:
    return " · ".join(
        part
        for part in (
            str(order.get("tradingsymbol") or "Unknown contract"),
            str(order.get("option_type") or ""),
            _money(order.get("unrealized_pnl")),
            str(order.get("entry_timestamp") or ""),
        )
        if part
    )


def render_active_trade_card(st: Any, card: Mapping[str, object]) -> None:
    st.markdown("### Selected Trade Full Card")
    st.caption(
        f"{card['contract']} · {card['status']} · Order {card['order_id']} · {card['authority']}"
    )
    section = st.selectbox(
        "Full Card Section",
        ("Overview", "PCR & Delta", "Risk & Exit", "Audit"),
        key="active_trade_full_card_section",
    )

    if section == "Overview":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Action", card["current_action"])
        c2.metric("Current P&L", _money(card["unrealized_pnl"]))
        c3.metric("Current PCR", _num(card["current_pcr"], 2))
        c4.metric("Current Delta", _num(card["current_delta"], 3))
        st.write({
            "Strategy": card["strategy"],
            "Contract": card["contract"],
            "Side": card["option_type"],
            "Strike": card["strike"],
            "Expiry": card["expiry"],
            "Quantity": card["quantity"],
            "Entry price": card["entry_price"],
            "Current price": card["current_price"],
            "Entry time": card["entry_time"],
        })
        st.caption(str(card["lifecycle_note"]))
        return

    if section == "PCR & Delta":
        st.dataframe(
            [
                {"Metric": "Strike PCR", "Entry": _NOT_AVAILABLE, "Current": _num(card["current_pcr"], 2), "Change": _NOT_AVAILABLE},
                {"Metric": "Delta", "Entry": _NOT_AVAILABLE, "Current": _num(card["current_delta"], 3), "Change": _NOT_AVAILABLE},
            ],
            width="stretch",
            hide_index=True,
        )
        st.write({
            "Call OI": _integer(card["call_oi"]),
            "Put OI": _integer(card["put_oi"]),
            "Selected OI": _integer(card["selected_oi"]),
            "IV": _num(card["iv"], 2),
            "Spread %": _num(card["spread_pct"], 2),
            "Best bid": _num(card["best_bid"], 2),
            "Best ask": _num(card["best_ask"], 2),
            "PCR source": card["pcr_source"],
            "Freshness": f"{card['freshness']['status']} · {card['freshness']['text']}",
        })
        return

    if section == "Risk & Exit":
        st.info("Existing paper exit protection remains the sole exit authority. This card is read-only.")
        st.write({
            "Initial stop": card.get("initial_stop") or _NOT_AVAILABLE,
            "Effective stop": card.get("effective_stop") or _NOT_AVAILABLE,
            "Trailing status": card.get("trailing_status") or _NOT_AVAILABLE,
            "Exit authority": "PAPER ENGINE",
        })
        return

    st.write({
        "Order ID": card["order_id"],
        "Telemetry timestamp": card["telemetry_timestamp"] or _NOT_AVAILABLE,
        "Telemetry status": card["freshness"]["status"],
        "PCR source": card["pcr_source"],
        "Authority": card["authority"],
    })


def install(active_trade_views_module: Any) -> None:
    """Add one selected active-trade card below the existing compact table."""
    if getattr(active_trade_views_module, "_full_trade_card_installed", False):
        return

    original_render = active_trade_views_module.render_current_trades

    def render_current_trades(database) -> None:
        original_render(database)
        try:
            orders = [dict(row) for row in (database.read_paper_execution_orders("PAPER-STD") or [])]
        except Exception:
            return
        open_rows = [row for row in orders if str(row.get("status") or "").upper() == "OPEN"]
        if not open_rows:
            return
        st = active_trade_views_module.st
        labels = {_trade_label(row): row for row in open_rows}
        selected_label = st.selectbox(
            "View full trade details",
            tuple(labels),
            key="active_trade_full_card_order",
        )
        selected = labels[selected_label]
        telemetry = active_trade_views_module._safe_latest_telemetry(
            database,
            str(selected.get("order_id") or ""),
        )
        render_active_trade_card(st, build_active_trade_card(selected, telemetry))

    active_trade_views_module.render_current_trades = render_current_trades
    active_trade_views_module._full_trade_card_installed = True


__all__ = ["build_active_trade_card", "install", "render_active_trade_card"]
