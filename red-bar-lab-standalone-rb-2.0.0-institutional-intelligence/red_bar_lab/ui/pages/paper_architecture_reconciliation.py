from __future__ import annotations

from typing import Mapping, Sequence

import streamlit as st

from red_bar_lab.ui.paper_architecture_comparison import (
    build_paper_architecture_comparison,
)
from red_bar_lab.ui.strategy_attribution import (
    build_strategy_attribution,
    build_strategy_performance_summary,
)
from red_bar_lab.ui.strategy_performance_ledger import (
    build_strategy_performance_ledger,
    render_strategy_performance_ledger,
)
from red_bar_lab.ui.strategy_shadow_evidence_registry import read_shadow_evidence


SECTION_10_STAGES = (
    {
        "section": "10A",
        "name": "Strategy Attribution and Provenance",
        "status": "COMPLETED",
        "authority": "READ_ONLY",
    },
    {
        "section": "10B",
        "name": "Strategy-Level Performance Ledger",
        "status": "COMPLETED",
        "authority": "READ_ONLY",
    },
    {
        "section": "10C",
        "name": "Legacy RB093 vs New Sections 4–9F Comparison",
        "status": "COMPLETED",
        "authority": "READ_ONLY",
    },
    {
        "section": "10D",
        "name": "Unified Shadow Execution Router",
        "status": "NEXT",
        "authority": "SHADOW_ONLY",
    },
    {
        "section": "10E",
        "name": "Controlled Paper-Only Activation",
        "status": "PENDING",
        "authority": "DISABLED",
    },
    {
        "section": "10F",
        "name": "Legacy Migration Decision",
        "status": "PENDING",
        "authority": "NOT_EVALUATED",
    },
)


def _read_orders(database) -> list[dict[str, object]]:
    try:
        return [
            dict(row)
            for row in (database.read_paper_execution_orders("PAPER-STD") or [])
        ]
    except Exception:
        return []


def _safe_checkpoint(database, order: Mapping[str, object]):
    order_id = str(order.get("order_id") or "")
    try:
        horizon = int(order.get("evaluation_horizon_minutes") or 0)
    except (TypeError, ValueError):
        horizon = 0
    if not order_id or horizon <= 0:
        return None
    try:
        return database.read_paper_trade_checkpoint(
            order_id=order_id,
            horizon_minutes=horizon,
        )
    except Exception:
        return None


def _safe_telemetry(database, order: Mapping[str, object]):
    order_id = str(order.get("order_id") or "")
    if not order_id:
        return None
    try:
        return database.read_latest_option_execution_telemetry(order_id)
    except Exception:
        return None


def build_reconciliation_snapshot(
    orders: Sequence[Mapping[str, object]],
    shadow_evidence: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build the read-only Section 10 summary without mutating source rows."""
    copied = [dict(row) for row in orders]
    evidence = [dict(row) for row in (shadow_evidence or [])]
    open_count = sum(
        str(row.get("status") or "").upper() == "OPEN" for row in copied
    )
    closed_count = sum(
        str(row.get("status") or "").upper() == "CLOSED" for row in copied
    )
    return {
        "stages": [dict(row) for row in SECTION_10_STAGES],
        "orders": copied,
        "shadow_evidence": evidence,
        "order_count": len(copied),
        "open_order_count": open_count,
        "closed_order_count": closed_count,
        "attribution_summary": build_strategy_performance_summary(copied),
        "performance_ledger": build_strategy_performance_ledger(copied),
        "comparison": build_paper_architecture_comparison(copied, evidence),
        "source_read_only": True,
        "persisted": False,
        "execution_allowed": False,
        "paper_order_created": False,
        "queue_state_changed": False,
        "capital_reserved": False,
    }


def _render_stage_status(snapshot: Mapping[str, object]) -> None:
    st.markdown("### Section 10 Delivery Status")
    st.dataframe(
        [
            {
                "Section": row.get("section"),
                "Capability": row.get("name"),
                "Status": row.get("status"),
                "Authority": row.get("authority"),
            }
            for row in snapshot.get("stages") or []
        ],
        width="stretch",
        hide_index=True,
    )


def _render_attribution(database, snapshot: Mapping[str, object]) -> None:
    st.markdown("### 10A. Strategy Attribution and Provenance")
    st.caption(
        "Identifies the primary strategy that owns each paper trade while keeping "
        "supporting intelligence and the legacy RB093 queue executor separate."
    )
    orders = [dict(row) for row in snapshot.get("orders") or []]
    if not orders:
        st.info("No paper trades are available for attribution.")
        return

    st.dataframe(
        [
            {
                "Strategy": row.get("strategy"),
                "Open": row.get("open_trades"),
                "Closed": row.get("closed_trades"),
                "Open P&L": round(float(row.get("open_pnl") or 0.0), 2),
                "Closed P&L": round(float(row.get("closed_pnl") or 0.0), 2),
                "Total": row.get("total_trades"),
            }
            for row in snapshot.get("attribution_summary") or []
        ],
        width="stretch",
        hide_index=True,
    )

    orders.sort(
        key=lambda row: str(
            row.get("entry_timestamp") or row.get("exit_timestamp") or ""
        ),
        reverse=True,
    )
    for order in orders[:30]:
        item = build_strategy_attribution(
            order,
            _safe_checkpoint(database, order),
            _safe_telemetry(database, order),
        )
        title = (
            f"{item.get('strategy')} · "
            f"{item.get('contract') or 'Unknown contract'} · "
            f"{item.get('order_id') or 'Unknown order'}"
        )
        with st.expander(title, expanded=False):
            st.write(
                {
                    "Primary strategy": item.get("strategy"),
                    "Strategy source": item.get("strategy_source"),
                    "Attribution confidence": item.get("attribution_confidence"),
                    "Signal ID": item.get("signal_id"),
                    "Bundle ID": item.get("bundle_id"),
                    "Candidate ID": item.get("candidate_id"),
                    "Entry role": item.get("entry_role"),
                    "Entry mode": item.get("entry_mode"),
                    "Queue source": item.get("queue_source"),
                    "Opened by": item.get("opened_by"),
                    "Supporting intelligence": item.get("supporting_intelligence_text"),
                    "Candidate rank": item.get("candidate_rank"),
                    "Candidate score": item.get("candidate_score"),
                    "Selection score": item.get("selection_score"),
                    "Execution probability %": item.get("execution_probability_pct"),
                    "Expected value %": item.get("expected_value_pct"),
                    "Exit-policy owner": item.get("exit_policy_owner"),
                    "Exit policy": item.get("exit_policy"),
                    "Exit mode": item.get("exit_mode"),
                    "Checkpoint": item.get("checkpoint_detail"),
                    "Option/OI telemetry": item.get("telemetry_detail"),
                    "Telemetry authority": item.get("telemetry_authority"),
                }
            )


def _render_comparison(snapshot: Mapping[str, object]) -> None:
    result = dict(snapshot.get("comparison") or {})
    counts = dict(result.get("counts") or {})
    st.markdown("### 10C. Legacy RB093 vs New Sections 4–9F Comparison")
    st.caption(
        "Matches only equivalent strategy/signal/candidate evidence evaluated at or "
        "before the legacy decision time. Current or later data is never substituted."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Shadow evidence", int(result.get("shadow_evidence_count") or 0))
    c2.metric("Comparable", int(result.get("comparable_count") or 0))
    c3.metric("Agree execute", int(counts.get("AGREE_EXECUTE") or 0))
    c4.metric("Legacy only", int(counts.get("LEGACY_ONLY_EXECUTE") or 0))
    c5.metric("Not comparable", int(counts.get("NOT_COMPARABLE") or 0))

    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info("No legacy orders or captured Section 4–9F evidence are available.")
        return
    st.dataframe(
        [
            {
                "Category": row.get("comparison_category"),
                "Order": row.get("order_id"),
                "Legacy Strategy": row.get("legacy_strategy"),
                "Legacy Signal": row.get("legacy_signal_id"),
                "Legacy Contract": row.get("legacy_contract"),
                "Legacy Time": row.get("legacy_decision_timestamp"),
                "New Decision": row.get("new_chain_decision"),
                "New Signal": row.get("new_signal_id"),
                "New Candidate": row.get("new_candidate_id"),
                "New Time": row.get("new_evaluation_timestamp"),
                "Reason": row.get("comparison_reason"),
            }
            for row in rows[:500]
        ],
        width="stretch",
        hide_index=True,
    )
    if int(counts.get("NOT_COMPARABLE") or 0):
        st.info(
            "Historical trades without captured, time-safe Sections 4–9F evidence remain "
            "NOT_COMPARABLE. Open each strategy page during future shadow operation so "
            "Section 9E evidence is captured before any later legacy execution."
        )
    st.write(
        "**Boundary:** comparison is process-local and read-only; it does not replay with "
        "future data, persist evidence, mutate RB093, or create paper orders."
    )


def _render_pending_architecture() -> None:
    st.markdown("### Reconciliation Roadmap")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 10D. Unified Shadow Execution Router")
        st.info(
            "Next: accept independently owned Red Bar, DRI and RSI candidates through "
            "one disabled, idempotent shadow-routing boundary."
        )
    with c2:
        st.markdown("#### 10E. Controlled Paper-Only Activation")
        st.caption(
            "Pending. Requires explicit feature flags, durable idempotency, atomic paper "
            "reservation and restart recovery."
        )
        st.markdown("#### 10F. Legacy Migration Decision")
        st.caption(
            "Pending. KEEP_LEGACY, HYBRID, NEW_ROUTER_PRIMARY or RETIRE_LEGACY will be "
            "selected only from comparison evidence."
        )


def render_page(
    settings,
    layout,
    database,
    token,
    underlying_name,
    instrument_key,
    interval,
) -> None:
    del settings, layout, token, underlying_name, instrument_key, interval

    orders = _read_orders(database)
    shadow_evidence = read_shadow_evidence()
    snapshot = build_reconciliation_snapshot(orders, shadow_evidence)

    st.subheader("Section 10 — Paper Architecture Reconciliation")
    st.caption(
        "Read-only bridge between the active legacy RB093 paper executor and the new "
        "institutional Sections 4–9F chain. This page cannot open, close, reserve, "
        "consume or submit anything."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Paper trades", snapshot["order_count"])
    c2.metric("Open", snapshot["open_order_count"])
    c3.metric("Closed", snapshot["closed_order_count"])
    c4.metric("Execution authority", "READ ONLY")

    st.warning(
        "Active paper orders continue to be opened by the legacy RB093 paper automation. "
        "Sections 9A–9F and this reconciliation page do not execute orders."
    )

    _render_stage_status(snapshot)
    _render_attribution(database, snapshot)
    render_strategy_performance_ledger(snapshot["performance_ledger"])
    _render_comparison(snapshot)
    _render_pending_architecture()

    st.write(
        "**Safety boundary:** no persistence, queue mutation, capital reservation, bundle "
        "consumption, position creation or broker submission is available here."
    )


__all__ = [
    "SECTION_10_STAGES",
    "build_reconciliation_snapshot",
    "render_page",
]
