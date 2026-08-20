from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from red_bar_lab.execution.option_telemetry_lifecycle import (
    read_option_telemetry_lifecycle,
)


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


def _change(current: object, entry: object) -> float | None:
    if current in (None, "") or entry in (None, ""):
        return None
    try:
        return float(current) - float(entry)
    except (TypeError, ValueError):
        return None


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
    lifecycle: Mapping[str, Mapping[str, object] | None] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Build one read-only card from persisted order and lifecycle telemetry."""
    item = dict(order)
    latest_fallback = dict(telemetry or {})
    life = dict(lifecycle or {})
    entry = dict(life.get("entry") or {})
    latest = dict(life.get("latest") or latest_fallback)
    exit_snapshot = dict(life.get("exit") or {})
    status = str(item.get("status") or "OPEN").upper()
    displayed = exit_snapshot if status == "CLOSED" and exit_snapshot else latest
    option_type = str(item.get("option_type") or item.get("side") or "").upper()
    selected_oi = (
        displayed.get("put_oi_at_strike")
        if option_type in {"PE", "PUT"}
        else displayed.get("call_oi_at_strike")
    )
    freshness = _freshness(displayed.get("observed_timestamp"), now)
    current_action = (
        "CLOSED"
        if status == "CLOSED"
        else f"HOLD {option_type}" if option_type in {"CE", "PE"}
        else "MONITOR"
    )
    comparison_label = "Exit" if status == "CLOSED" else "Current"
    current_pcr = displayed.get("pcr_oi")
    current_delta = displayed.get("delta")
    entry_pcr = entry.get("pcr_oi")
    entry_delta = entry.get("delta")
    lifecycle_ready = bool(entry)
    note = (
        "Entry and current lifecycle snapshots are persisted."
        if lifecycle_ready
        else "Entry lifecycle snapshot is not available for this trade."
    )
    if status == "CLOSED":
        note = (
            "Entry and exit lifecycle snapshots are persisted."
            if lifecycle_ready and exit_snapshot
            else "Exact exit lifecycle telemetry is not available for this trade."
        )
    return {
        "order_id": str(item.get("order_id") or ""),
        "contract": str(item.get("tradingsymbol") or "Unknown contract"),
        "status": status,
        "strategy": str(item.get("execution_strategy_source") or item.get("strategy_source") or "RED_BAR_V2"),
        "option_type": option_type or _NOT_AVAILABLE,
        "strike": item.get("strike"),
        "expiry": item.get("expiry"),
        "quantity": item.get("quantity"),
        "entry_time": item.get("entry_timestamp"),
        "exit_time": item.get("exit_timestamp"),
        "entry_price": item.get("entry_price"),
        "current_price": item.get("exit_price") if status == "CLOSED" else item.get("current_price"),
        "unrealized_pnl": item.get("realized_pnl") if status == "CLOSED" else item.get("unrealized_pnl"),
        "entry_pcr": entry_pcr,
        "current_pcr": current_pcr,
        "pcr_change": _change(current_pcr, entry_pcr),
        "entry_delta": entry_delta,
        "current_delta": current_delta,
        "delta_change": _change(current_delta, entry_delta),
        "call_oi": displayed.get("call_oi_at_strike"),
        "put_oi": displayed.get("put_oi_at_strike"),
        "selected_oi": selected_oi,
        "iv": displayed.get("iv"),
        "spread_pct": displayed.get("spread_pct"),
        "best_bid": displayed.get("best_bid"),
        "best_ask": displayed.get("best_ask"),
        "telemetry_timestamp": displayed.get("observed_timestamp"),
        "pcr_source": displayed.get("snapshot_source") or latest_fallback.get("pcr_source") or "NOT_AVAILABLE",
        "freshness": freshness,
        "current_action": current_action,
        "comparison_label": comparison_label,
        "entry_snapshot_source": entry.get("snapshot_source") or "NOT_AVAILABLE",
        "exit_snapshot_source": exit_snapshot.get("snapshot_source") or "NOT_AVAILABLE",
        "exit_data_quality": exit_snapshot.get("data_quality") or "NOT_AVAILABLE",
        "authority": "OBSERVATIONAL ONLY",
        "lifecycle_note": note,
    }


def _trade_label(order: Mapping[str, object]) -> str:
    pnl = order.get("realized_pnl") if str(order.get("status") or "").upper() == "CLOSED" else order.get("unrealized_pnl")
    return " · ".join(
        part
        for part in (
            str(order.get("tradingsymbol") or "Unknown contract"),
            str(order.get("option_type") or ""),
            _money(pnl),
            str(order.get("entry_timestamp") or ""),
        )
        if part
    )


def render_active_trade_card(st: Any, card: Mapping[str, object]) -> None:
    st.markdown("### Selected Trade Full Card")
    st.caption(f"{card['contract']} · {card['status']} · Order {card['order_id']} · {card['authority']}")
    section = st.selectbox(
        "Full Card Section",
        ("Overview", "PCR & Delta", "Risk & Exit", "Audit"),
        key="active_trade_full_card_section",
    )

    if section == "Overview":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Action", card["current_action"])
        c2.metric("Current P&L", _money(card["unrealized_pnl"]))
        c3.metric(f"{card['comparison_label']} PCR", _num(card["current_pcr"], 2))
        c4.metric(f"{card['comparison_label']} Delta", _num(card["current_delta"], 3))
        st.write({
            "Strategy": card["strategy"],
            "Contract": card["contract"],
            "Side": card["option_type"],
            "Strike": card["strike"],
            "Expiry": card["expiry"],
            "Quantity": card["quantity"],
            "Entry price": card["entry_price"],
            f"{card['comparison_label']} price": card["current_price"],
            "Entry time": card["entry_time"],
            "Exit time": card["exit_time"],
        })
        st.caption(str(card["lifecycle_note"]))
        return

    if section == "PCR & Delta":
        st.dataframe(
            [
                {
                    "Metric": "Strike PCR",
                    "Entry": _num(card["entry_pcr"], 2),
                    card["comparison_label"]: _num(card["current_pcr"], 2),
                    "Change": _num(card["pcr_change"], 2),
                },
                {
                    "Metric": "Delta",
                    "Entry": _num(card["entry_delta"], 3),
                    card["comparison_label"]: _num(card["current_delta"], 3),
                    "Change": _num(card["delta_change"], 3),
                },
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
            "Snapshot source": card["pcr_source"],
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
        "Entry snapshot source": card["entry_snapshot_source"],
        "Exit snapshot source": card["exit_snapshot_source"],
        "Exit data quality": card["exit_data_quality"],
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
        order_id = str(selected.get("order_id") or "")
        telemetry = active_trade_views_module._safe_latest_telemetry(database, order_id)
        try:
            lifecycle = read_option_telemetry_lifecycle(database, order_id)
        except Exception:
            lifecycle = None
        render_active_trade_card(
            st,
            build_active_trade_card(selected, telemetry, lifecycle=lifecycle),
        )

    active_trade_views_module.render_current_trades = render_current_trades
    active_trade_views_module._full_trade_card_installed = True


__all__ = ["build_active_trade_card", "install", "render_active_trade_card"]
