from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from red_bar_lab.ui._shared import *  # noqa: F401,F403  (follows established ui/pages convention)
from red_bar_lab.ui.lifecycle_stepper import (
    LifecycleContext,
    LifecycleStep,
    make_step,
    render_lifecycle_all,
    safe_read,
    signal_selector,
)
from red_bar_lab.ui.live_cadence import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    detect_new_signal,
    init_live_session_state,
    read_orchestrator_cadence,
    read_paper_monitor_cadence,
    record_follow,
    record_poll_completed,
    render_poll_controls,
    render_upstream_cadence_panel,
    reset_step_timings,
)

STEPPER_KEY = "legacy_v2_lifecycle_stepper"
PAGE_KEY = "legacy_v2_lifecycle_page"
SIGNAL_KEY = "legacy_v2_lifecycle_signal"
DATE_KEY = "legacy_v2_lifecycle_date"
LIVE_MODE_KEY = "legacy_v2_lifecycle_live_mode"


def _render_banner(st: Any, context: LifecycleContext) -> None:
    st.title("Legacy V2 Lifecycle")
    st.warning(
        "LEGACY V2 — PAPER TRADING ENABLED. "
        "This is the live entry path. It places virtual paper orders via "
        "RedBarPaperExecutionEngine. No live broker API is ever called."
    )
    st.caption(
        "Read-only lifecycle view. Walking these 12 steps does not open, "
        "modify, or close any order. Order placement happens on the "
        "RedBarPaperAutomationService cycle, not on this page."
    )
    _render_live_mode_controls(st, context)
    if st.session_state.get(LIVE_MODE_KEY):
        _render_live_cadence_panel(st, context)
    _render_context_controls(st, context)


def _render_live_mode_controls(st: Any, context: LifecycleContext) -> None:
    init_live_session_state(st)
    cols = st.columns([1, 1, 1])
    with cols[0]:
        is_live = st.toggle(
            "Live Mode (poll upstream)",
            value=bool(st.session_state.get(LIVE_MODE_KEY, False)),
            key="legacy_v2_lifecycle_live_toggle",
            help=(
                "When enabled, the page polls the upstream paper monitor "
                "every N seconds and snaps to a new signal automatically."
            ),
        )
        st.session_state[LIVE_MODE_KEY] = is_live
    with cols[1]:
        if is_live:
            render_poll_controls(st)
    with cols[2]:
        if is_live and st.button(
            "Reset live state",
            key="legacy_v2_lifecycle_reset_live",
        ):
            reset_step_timings(st)
            st.session_state[LIVE_MODE_KEY] = False
            st.rerun()


def _render_live_cadence_panel(st: Any, context: LifecycleContext) -> None:
    paper = read_paper_monitor_cadence(context.database)
    orchestrator = read_orchestrator_cadence(
        context.database,
        instrument_key=context.instrument_key,
        trading_date=context.trading_date,
    )
    page_status = _build_page_self_cadence(st)
    try:
        st.session_state["step_evidence_database"] = context.database
        # Read the most-recent market_collector run so the 12 lifecycle
        # step evidence rows can share its run_id (best-effort).
        try:
            corr = context.database.read_process_run_correlation(
                process_name="market_collector"
            )
            if corr is not None:
                st.session_state["live_cadence_last_run_id"] = str(
                    corr.get("run_id") or ""
                )
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    render_upstream_cadence_panel(
        st,
        cadences=[paper, orchestrator, page_status],
        page_poll_interval_seconds=int(
            st.session_state.get("live_cadence_poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
        ),
        page_polls_since_start=int(st.session_state.get("live_cadence_polls_since_start", 0)),
        page_last_poll_at=st.session_state.get("live_cadence_last_poll_at"),
        page_started_at=st.session_state.get("live_cadence_page_started_at"),
        instrument_key=context.instrument_key,
        trading_date=context.trading_date,
        account_id="PAPER-STD",
    )
    _maybe_follow_new_signal(st, paper.last_signal_id, context)
    record_poll_completed(st)


def _build_page_self_cadence(st: Any):
    from red_bar_lab.ui.live_cadence import (
        POLL_INTERVAL_KEY,
        UpstreamCadenceStatus,
        _seconds_since,
    )

    polls = int(st.session_state.get("live_cadence_polls_since_start", 0))
    last_poll = st.session_state.get("live_cadence_last_poll_at")
    poll_interval = int(st.session_state.get(POLL_INTERVAL_KEY, 0))
    import time as _time

    seconds_since = (
        _seconds_since(last_poll, now_epoch=_time.time()) if last_poll else None
    )
    cadence_label = (
        f"User-configured · {poll_interval}s loop"
        if poll_interval
        else "User-configured"
    )
    if last_poll is None:
        return UpstreamCadenceStatus(
            name="Page Polling",
            cadence_label=cadence_label,
            last_heartbeat_at=None,
            seconds_since_heartbeat=None,
            is_stale=False,
            last_signal_id=None,
            last_decision="WAITING" if polls == 0 else "RUNNING",
            last_error=None,
            total_ms=None,
            stages={},
            dependency="downstream-of:paper-monitor,orchestrator",
            dependency_label="user-config · reads both upstreams",
        )
    return UpstreamCadenceStatus(
        name="Page Polling",
        cadence_label=cadence_label,
        last_heartbeat_at=str(last_poll),
        seconds_since_heartbeat=seconds_since,
        is_stale=False,
        last_signal_id=None,
        last_decision=f"RUNNING · {polls} polls",
        last_error=st.session_state.get("live_cadence_last_error"),
        total_ms=None,
        stages={},
        dependency="downstream-of:paper-monitor,orchestrator",
        dependency_label="user-config · reads both upstreams",
    )


def _maybe_follow_new_signal(
    st: Any, upstream_signal_id: str | None, context: LifecycleContext
) -> None:
    new_signal = detect_new_signal(st, current_signal_id=upstream_signal_id)
    if new_signal is None:
        return
    record_follow(st, new_signal)
    st.session_state[SIGNAL_KEY] = new_signal
    context.signal_id = new_signal
    st.toast(f"New signal detected: {new_signal}", icon="🟢")
    st.rerun()


def _render_context_controls(st: Any, context: LifecycleContext) -> None:
    cols = st.columns(2)
    with cols[0]:
        selected = st.date_input(
            "Trading date",
            value=date.fromisoformat(context.trading_date),
            key=DATE_KEY,
        )
        context.trading_date = selected.isoformat()
    with cols[1]:
        signal_id = signal_selector(
            st,
            context.database,
            instrument_key=context.instrument_key,
            trading_date=context.trading_date,
            selectbox_key=SIGNAL_KEY,
        )
        context.signal_id = signal_id


def _resolve_signal_row(context: LifecycleContext) -> dict[str, Any] | None:
    if not context.signal_id:
        return None
    rows = safe_read(
        lambda: context.database.read_signal_attempts(context.instrument_key, context.trading_date),
        default=[],
    )
    for row in rows:
        if str(row.get("signal_id") or "") == context.signal_id:
            return row
    return None


def _step_signal_discovery(st: Any, context: LifecycleContext) -> None:
    st.markdown("What triggered this candidate?")
    signal_row = _resolve_signal_row(context)
    if signal_row is None:
        st.info("No signal selected. Use the picker above to choose a signal.")
        return
    frame = pd.DataFrame(
        [
            ("Signal ID", signal_row.get("signal_id")),
            ("Strategy source", signal_row.get("execution_strategy_source") or "LEGACY_V1"),
            ("Direction", signal_row.get("direction")),
            ("Level type", signal_row.get("level_type")),
            ("Reference level", signal_row.get("reference_level")),
            ("Reference value", signal_row.get("reference_value")),
            ("Confirmation timestamp", signal_row.get("confirmation_timestamp")),
            ("Confirmation close", signal_row.get("confirmation_close")),
            ("Confirmation high", signal_row.get("confirmation_high")),
            ("Confirmation low", signal_row.get("confirmation_low")),
            ("Initial state", signal_row.get("state")),
        ],
        columns=["Field", "Value"],
    ).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)

    # Sub-block: the strategy engine's own per-step audit, when this
    # page is running in Live Mode. Shows what the Red Bar V2 engine
    # did this cycle: latest 1m candle, candidate scan, admission
    # decision.
    from red_bar_lab.ui.live_cadence import render_strategy_engine_audit

    render_strategy_engine_audit(
        st,
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )


def _step_lifecycle_eligibility(st: Any, context: LifecycleContext) -> None:
    st.markdown("Freshness, drift, and duplicate checks against `signal_attempts`.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="lifecycle_eligibility",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    signal_row = _resolve_signal_row(context)
    if signal_row is None:
        st.info("No signal selected.")
        return
    rows = safe_read(
        lambda: context.database.read_paper_signal_diagnostics(
            trading_date=context.trading_date, limit=200
        ),
        default=[],
    )
    relevant = [
        row
        for row in rows
        if str(row.get("signal_id") or "") == context.signal_id
    ]
    if not relevant:
        st.info("No diagnostic row is stored for this signal yet.")
        return
    frame = pd.DataFrame(relevant).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.caption(
        f"Age seconds: {relevant[0].get('signal_age_seconds')}. "
        f"Source status: {relevant[0].get('source_status')}. "
        f"Terminal condition: {relevant[0].get('terminal_condition')}."
    )


def _step_decision(st: Any, context: LifecycleContext) -> None:
    st.markdown("Admission outcome and committee decision.")
    if not context.signal_id:
        st.info("No signal selected.")
        return
    evaluations = safe_read(
        lambda: context.database.read_institutional_execution_evaluations(
            trading_date=context.trading_date, limit=200
        ),
        default=[],
    )
    relevant = [
        row for row in evaluations if str(row.get("signal_id") or "") == context.signal_id
    ]
    if not relevant:
        st.info("No committee evaluation row is stored for this signal yet.")
        return
    frame = pd.DataFrame(relevant).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _step_scoring_selection(st: Any, context: LifecycleContext) -> None:
    st.markdown("Opportunity, performance, and selection scores.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="scoring_selection",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    if not context.signal_id:
        st.info("No signal selected.")
        return
    opportunity_rows = safe_read(
        lambda: context.database.read_opportunity_evaluations(
            trading_date=context.trading_date, limit=200
        ),
        default=[],
    )
    selection_rows = safe_read(
        lambda: context.database.read_trade_selection_evaluations(
            trading_date=context.trading_date, limit=200
        ),
        default=[],
    )
    opportunity_relevant = [
        row for row in opportunity_rows if str(row.get("signal_id") or "") == context.signal_id
    ]
    selection_relevant = [
        row for row in selection_rows if str(row.get("signal_id") or "") == context.signal_id
    ]
    if not opportunity_relevant and not selection_relevant:
        st.info("No scoring rows are stored for this signal yet.")
        return
    if opportunity_relevant:
        st.markdown("##### Opportunity Evaluation")
        st.dataframe(pd.DataFrame(opportunity_relevant).astype("string"), hide_index=True, use_container_width=True)
    if selection_relevant:
        st.markdown("##### Trade Selection Evaluation")
        st.dataframe(pd.DataFrame(selection_relevant).astype("string"), hide_index=True, use_container_width=True)


def _step_risk_gates(st: Any, context: LifecycleContext) -> None:
    st.markdown("Order guard and risk envelope.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="risk_gates",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    candidates = safe_read(
        lambda: context.database.read_paper_candidate_decisions(
            trading_date=context.trading_date, limit=200
        ),
        default=[],
    )
    orders = safe_read(
        lambda: context.database.read_paper_execution_orders("PAPER-STD"),
        default=[],
    )
    open_orders = [row for row in orders if row.get("status") == "OPEN"]
    same_direction = [
        row
        for row in open_orders
        if str(row.get("side") or "").upper() != "BUY"
    ]
    metrics = [
        ("Total open orders", len(open_orders)),
        ("Maximum open trades (cap)", 5),
        ("Same-direction open orders", len(same_direction)),
        ("Same-direction cap", 3),
        ("Total paper candidates today", len(candidates)),
    ]
    frame = pd.DataFrame(metrics, columns=["Metric", "Value"]).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    if context.signal_id:
        per_signal = [
            row for row in orders if str(row.get("signal_id") or "") == context.signal_id
        ]
        st.metric("Entries placed for this signal", len(per_signal))
        st.caption("V2 cap is 2 entries per signal.")


def _step_queue(st: Any, context: LifecycleContext) -> None:
    st.markdown("Execution queue state.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="queue",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    if not context.signal_id:
        st.info("No signal selected.")
        return
    rows = safe_read(
        lambda: context.database.read_execution_queue(limit=200),
        default=[],
    )
    relevant = [row for row in rows if str(row.get("signal_id") or "") == context.signal_id]
    if not relevant:
        st.info("No execution_queue row for this signal.")
        return
    st.dataframe(pd.DataFrame(relevant).astype("string"), hide_index=True, use_container_width=True)


def _step_entry(st: Any, context: LifecycleContext) -> None:
    st.markdown("Paper order open and ENTRY mark.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="entry",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    if not context.signal_id:
        st.info("No signal selected.")
        return
    orders = safe_read(
        lambda: context.database.read_paper_execution_orders("PAPER-STD"),
        default=[],
    )
    relevant = [row for row in orders if str(row.get("signal_id") or "") == context.signal_id]
    if not relevant:
        st.info("No paper_execution_orders row for this signal.")
        return
    for order in relevant:
        st.markdown(f"##### Order `{order.get('order_id')}`")
        order_frame = pd.DataFrame(
            [
                ("Order ID", order.get("order_id")),
                ("Status", order.get("status")),
                ("Symbol", order.get("tradingsymbol")),
                ("Strike", order.get("strike")),
                ("Option type", order.get("option_type")),
                ("Quantity", order.get("quantity")),
                ("Entry timestamp", order.get("entry_timestamp")),
                ("Entry price", order.get("entry_price")),
                ("Entry reason", order.get("entry_reason")),
                ("Stop price", order.get("stop_price")),
                ("Target 1", order.get("target1_price")),
            ],
            columns=["Field", "Value"],
        ).astype("string")
        st.dataframe(order_frame, hide_index=True, use_container_width=True)
        marks = safe_read(
            lambda: context.database.read_paper_execution_marks(
                order_id=str(order.get("order_id"))
            ),
            default=[],
        )
        entry_marks = [row for row in marks if str(row.get("event_type") or "") == "ENTRY"]
        if entry_marks:
            st.dataframe(pd.DataFrame(entry_marks).astype("string"), hide_index=True, use_container_width=True)


def _step_mark_monitor(st: Any, context: LifecycleContext) -> None:
    st.markdown("Mark log (MARK events) and live MFE/MAE tracking.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="mark_monitor",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    if not context.signal_id:
        st.info("No signal selected.")
        return
    orders = safe_read(
        lambda: context.database.read_paper_execution_orders("PAPER-STD"),
        default=[],
    )
    relevant = [row for row in orders if str(row.get("signal_id") or "") == context.signal_id]
    if not relevant:
        st.info("No open or closed orders for this signal.")
        return
    for order in relevant:
        order_id = str(order.get("order_id"))
        marks = safe_read(
            lambda: context.database.read_paper_execution_marks(order_id=order_id),
            default=[],
        )
        monitor_marks = [row for row in marks if str(row.get("event_type") or "") == "MARK"]
        if not monitor_marks:
            st.info(f"Order {order_id}: no MARK events yet.")
            continue
        st.markdown(f"##### Order `{order_id}` mark log")
        st.dataframe(pd.DataFrame(monitor_marks).astype("string"), hide_index=True, use_container_width=True)
        mfe = order.get("mfe_points")
        mae = order.get("mae_points")
        cols = st.columns(3)
        cols[0].metric("MFE points", "—" if mfe is None else f"{float(mfe):.2f}")
        cols[1].metric("MAE points", "—" if mae is None else f"{float(mae):.2f}")
        cols[2].metric("Unrealized PnL", f"{float(order.get('unrealized_pnl') or 0.0):.2f}")


def _step_exit_health(st: Any, context: LifecycleContext) -> None:
    st.markdown("PaperExitEngine health and the most recent action.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="close",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    if not context.signal_id:
        st.info("No signal selected.")
        return
    events = safe_read(
        lambda: context.database.read_execution_state_events(
            trading_date=context.trading_date, limit=500
        ),
        default=[],
    )
    relevant = [
        row
        for row in events
        if str(row.get("signal_id") or "") == context.signal_id
        and "EXIT" in str(row.get("state") or "")
    ]
    if not relevant:
        st.info("No EXIT health events recorded for this signal yet.")
        return
    frame = pd.DataFrame(relevant).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _step_close(st: Any, context: LifecycleContext) -> None:
    st.markdown("EXIT mark and realized PnL.")
    if not context.signal_id:
        st.info("No signal selected.")
        return
    orders = safe_read(
        lambda: context.database.read_paper_execution_orders("PAPER-STD"),
        default=[],
    )
    relevant = [row for row in orders if str(row.get("signal_id") or "") == context.signal_id]
    closed = [row for row in relevant if row.get("status") == "CLOSED"]
    if not closed:
        st.info("No CLOSED orders yet for this signal.")
        return
    for order in closed:
        order_id = str(order.get("order_id"))
        st.markdown(f"##### Closed order `{order_id}`")
        close_frame = pd.DataFrame(
            [
                ("Exit timestamp", order.get("exit_timestamp")),
                ("Exit price", order.get("exit_price")),
                ("Exit reason", order.get("exit_reason")),
                ("Realized PnL", order.get("realized_pnl")),
                ("Final MFE", order.get("mfe_points")),
                ("Final MAE", order.get("mae_points")),
            ],
            columns=["Field", "Value"],
        ).astype("string")
        st.dataframe(close_frame, hide_index=True, use_container_width=True)
        marks = safe_read(
            lambda: context.database.read_paper_execution_marks(order_id=order_id),
            default=[],
        )
        exit_marks = [row for row in marks if str(row.get("event_type") or "") == "EXIT"]
        if exit_marks:
            st.dataframe(pd.DataFrame(exit_marks).astype("string"), hide_index=True, use_container_width=True)


def _step_attribution(st: Any, context: LifecycleContext) -> None:
    st.markdown("Strategy attribution and committee traces for this signal.")
    if not context.signal_id:
        st.info("No signal selected.")
        return
    evaluations = safe_read(
        lambda: context.database.read_institutional_execution_evaluations(
            trading_date=context.trading_date, limit=200
        ),
        default=[],
    )
    relevant = [
        row for row in evaluations if str(row.get("signal_id") or "") == context.signal_id
    ]
    if not relevant:
        st.info("No committee evaluation row for this signal.")
        return
    st.dataframe(pd.DataFrame(relevant).astype("string"), hide_index=True, use_container_width=True)


def _step_persistence_audit(st: Any, context: LifecycleContext) -> None:
    st.markdown("Full execution_state_events audit trail for the selected signal.")
    if not context.signal_id:
        st.info("No signal selected.")
        return
    rows = safe_read(
        lambda: context.database.read_execution_state_events_for_signals(
            signal_ids=[context.signal_id]
        ),
        default=[],
    )
    if not rows:
        st.info("No execution_state_events for this signal.")
        return
    ordered = sorted(rows, key=lambda row: str(row.get("evaluated_at") or ""))
    st.dataframe(pd.DataFrame(ordered).astype("string"), hide_index=True, use_container_width=True)


def _build_steps() -> list[LifecycleStep]:
    return [
        make_step(
            step_id="signal_discovery",
            title="Signal Discovery",
            description="What triggered the candidate (level, direction, confirmation).",
            renderer=_step_signal_discovery,
        ),
        make_step(
            step_id="lifecycle_eligibility",
            title="Lifecycle Eligibility",
            description="Freshness, drift, and duplicate checks via paper_signal_diagnostics.",
            renderer=_step_lifecycle_eligibility,
        ),
        make_step(
            step_id="decision",
            title="Decision",
            description="InstitutionalExecutionCommittee admission outcome and module votes.",
            renderer=_step_decision,
        ),
        make_step(
            step_id="scoring_selection",
            title="Scoring & Selection",
            description="Opportunity evaluation and trade selection score breakdown.",
            renderer=_step_scoring_selection,
        ),
        make_step(
            step_id="risk_gates",
            title="Risk Gates",
            description="Open order envelope: total open, same-direction, per-signal caps.",
            renderer=_step_risk_gates,
        ),
        make_step(
            step_id="queue",
            title="Queue",
            description="Execution queue row for this signal.",
            renderer=_step_queue,
        ),
        make_step(
            step_id="entry",
            title="Entry",
            description="paper_execution_orders row + ENTRY mark log.",
            renderer=_step_entry,
        ),
        make_step(
            step_id="mark_monitor",
            title="Mark / Monitor",
            description="Refreshed quotes, MFE/MAE, unrealized PnL.",
            renderer=_step_mark_monitor,
        ),
        make_step(
            step_id="exit_health",
            title="Exit Health",
            description="PaperExitEngine exit-health events on the timeline.",
            renderer=_step_exit_health,
        ),
        make_step(
            step_id="close",
            title="Close",
            description="EXIT mark and realized PnL for closed orders.",
            renderer=_step_close,
        ),
        make_step(
            step_id="attribution",
            title="Attribution",
            description="Strategy attribution and committee traces.",
            renderer=_step_attribution,
        ),
        make_step(
            step_id="persistence_audit",
            title="Persistence & Audit",
            description="Full execution_state_events audit trail for the selected signal.",
            renderer=_step_persistence_audit,
        ),
    ]


def render_page(
    settings: Any,
    layout: Any,
    database: Any,
    token: str,
    underlying_name: str,
    instrument_key: str,
    interval: int,
) -> None:
    init_live_session_state(st)
    context = LifecycleContext(
        settings=settings,
        layout=layout,
        database=database,
        token=token,
        underlying_name=underlying_name,
        instrument_key=instrument_key,
        interval=interval,
        trading_date=date.today().isoformat(),
        signal_id=None,
    )
    render_lifecycle_all(
        steps=_build_steps(),
        context=context,
        page_key=PAGE_KEY,
        banner_renderer=_render_banner,
        show_timings=True,
        process_name="v2_lifecycle_legacy_render",
        database=database,
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    _maybe_schedule_live_rerun(st)


def _maybe_schedule_live_rerun(st: Any) -> None:
    """Sleep for the configured poll interval, then rerun.

    Only triggered when Live Mode is on. We do this at the very end of
    the render so the user sees the current state before the page
    refreshes.
    """
    if not st.session_state.get(LIVE_MODE_KEY):
        return
    import time

    poll_interval = int(
        st.session_state.get("live_cadence_poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    )
    time.sleep(max(1, poll_interval))
    st.rerun()
