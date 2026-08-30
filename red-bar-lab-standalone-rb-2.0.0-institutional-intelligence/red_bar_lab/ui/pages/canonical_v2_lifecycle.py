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

STEPPER_KEY = "canonical_v2_lifecycle_stepper"
PAGE_KEY = "canonical_v2_lifecycle_page"
BUNDLE_KEY = "canonical_v2_lifecycle_bundle"
LIVE_MODE_KEY = "canonical_v2_lifecycle_live_mode"


def _render_banner(st: Any, context: LifecycleContext) -> None:
    st.title("Canonical V2 Lifecycle")
    st.error(
        "CANONICAL V2 — PAPER TRADING IS NOT YET ENABLED. "
        "This is an observational, read-only view. No paper or live orders "
        "are placed from this page."
    )
    st.error(
        "Canonical paper execution remains in OBSERVE_ONLY mode by default. "
        "To enable, set RED_BAR_V2_CANONICAL_PAPER_EXECUTION_ENABLED=true "
        "and RED_BAR_V2_CANONICAL_PAPER_EXECUTION_MODE=PAPER_ONLY. "
        "That change is not made from this page."
    )
    st.warning(
        "Walking these 12 steps does not initialize schema, start the "
        "shadow worker, place a paper order, or modify the canonical state."
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
            key="canonical_v2_lifecycle_live_toggle",
            help=(
                "When enabled, the page polls the upstream paper monitor "
                "every N seconds and snaps to a new canonical bundle "
                "automatically when one is published."
            ),
        )
        st.session_state[LIVE_MODE_KEY] = is_live
    with cols[1]:
        if is_live:
            render_poll_controls(st)
    with cols[2]:
        if is_live and st.button(
            "Reset live state",
            key="canonical_v2_lifecycle_reset_live",
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
    # Stash the database handle so the per-step evidence panel can read
    # ``process_evidence`` without us having to thread it through.
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
    _maybe_follow_new_bundle(st, paper.last_signal_id, context)
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
    if last_poll is None:
        return UpstreamCadenceStatus(
            name="Page Polling",
            cadence_label=(
                f"User-configured · {poll_interval}s loop"
                if poll_interval
                else "User-configured"
            ),
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
        cadence_label=(
            f"User-configured · {poll_interval}s loop"
            if poll_interval
            else "User-configured"
        ),
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


def _maybe_follow_new_bundle(
    st: Any, upstream_signal_id: str | None, context: LifecycleContext
) -> None:
    new_signal = detect_new_signal(st, current_signal_id=upstream_signal_id)
    if new_signal is None:
        return
    record_follow(st, new_signal)
    st.session_state[BUNDLE_KEY] = new_signal
    context.signal_id = new_signal
    st.toast(f"New canonical observation: {new_signal}", icon="🟢")
    st.rerun()


def _load_observability_view(context: LifecycleContext) -> Any | None:
    from red_bar_lab.services.red_bar_v2_canonical.observability_repository import (
        SQLiteRedBarV2CanonicalObservabilityRepository,
    )
    from red_bar_lab.services.red_bar_v2_canonical.observability_service import (
        RedBarV2CanonicalObservabilityService,
    )

    repository = SQLiteRedBarV2CanonicalObservabilityRepository(
        context.settings.database_path
    )
    return safe_read(
        lambda: RedBarV2CanonicalObservabilityService(
            repository, database_path=context.settings.database_path
        ).load(
            instrument_key=context.instrument_key,
            feature_enabled=context.settings.red_bar_v2_canonical_shadow_enabled,
            limit=25,
        ),
        default=None,
    )


def _load_reservation(context: LifecycleContext, bundle_id: str | None) -> Any:
    from red_bar_lab.services.red_bar_v2_canonical.reservation_observability import (
        SQLiteReservationObservabilityRepository,
    )

    if not bundle_id:
        return None
    return safe_read(
        lambda: SQLiteReservationObservabilityRepository(
            context.settings.database_path
        ).latest_for_bundle(bundle_id=bundle_id, event_limit=25),
        default=None,
    )


def _load_canary_observation(context: LifecycleContext) -> Any:
    from red_bar_lab.services.red_bar_v2_canonical.paper_canary_observability import (
        PaperCanaryRuntimeObservabilityService,
    )

    return safe_read(
        lambda: PaperCanaryRuntimeObservabilityService(
            context.settings.paper_canary_state_path
        ).load(
            worker_enabled=context.settings.red_bar_v2_paper_canary_worker_enabled,
            mode=context.settings.red_bar_v2_canonical_paper_execution_mode,
        ),
        default=None,
    )


def _load_paper_execution_observation(
    context: LifecycleContext, bundle_id: str | None
) -> Any:
    from red_bar_lab.services.red_bar_v2_canonical.paper_execution_observability import (
        SQLiteCanonicalPaperExecutionObservabilityRepository,
    )

    if not bundle_id:
        return None
    return safe_read(
        lambda: SQLiteCanonicalPaperExecutionObservabilityRepository(
            context.settings.database_path
        ).latest_for_bundle(bundle_id=bundle_id, event_limit=25),
        default=None,
    )


def _render_context_controls(st: Any, context: LifecycleContext) -> None:
    cols = st.columns(2)
    with cols[0]:
        selected = st.date_input(
            "Trading date",
            value=date.fromisoformat(context.trading_date),
            key="canonical_v2_lifecycle_date",
        )
        context.trading_date = selected.isoformat()
    with cols[1]:
        view = _load_observability_view(context)
        bundle_id: str | None = None
        if view is not None and getattr(view, "section_3", None) is not None:
            bundle_id = view.section_3.bundle_id
        st.text_input(
            "Selected bundle ID",
            value=bundle_id or "",
            key=BUNDLE_KEY,
            disabled=True,
            help="The most recent canonical bundle for this instrument.",
        )
        context.signal_id = bundle_id


def _step_signal_discovery(st: Any, context: LifecycleContext) -> None:
    st.markdown("Reference readiness and shared market context (Section 1).")
    view = _load_observability_view(context)
    if view is None or getattr(view, "section_1", None) is None:
        st.info(
            "No canonical observation is available yet. "
            "Shadow observations are written by the canonical V2 worker when "
            "the RED_BAR_V2_CANONICAL_SHADOW_ENABLED feature flag is on."
        )
        return
    s1 = view.section_1
    frame = pd.DataFrame(
        [
            ("Underlying instrument", s1.underlying_instrument),
            ("Futures instrument", s1.futures_instrument),
            ("Trading date", s1.trading_date),
            ("Reference status", s1.reference_status),
            ("Reference high", s1.reference_high),
            ("Reference low", s1.reference_low),
            ("Reference midpoint", s1.reference_midpoint),
            ("Index timestamp", s1.latest_index_timestamp),
            ("Futures timestamp", s1.latest_futures_timestamp),
            ("Context status", s1.context_status),
            ("Section 1 outcome", s1.outcome),
            ("Reason code", s1.reason_code),
        ],
        columns=["Field", "Value"],
    ).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.info(s1.explanation)

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
    st.markdown("Canonical state machine and decision (Section 2).")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="lifecycle_eligibility",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    view = _load_observability_view(context)
    if view is None or getattr(view, "section_2", None) is None:
        st.info("No Section 2 evidence yet.")
        return
    s2 = view.section_2
    cols = st.columns(4)
    cols[0].metric("Admission", s2.admission_outcome)
    cols[1].metric("Direction", s2.direction or "—")
    cols[2].metric("Option side", s2.option_side or "—")
    cols[3].metric("Entry type", s2.entry_type or "—")
    st.caption(
        f"State: {s2.previous_state} → {s2.current_state} · "
        f"Timeframe: {s2.evaluation_timeframe} · "
        f"Trend strength: {s2.trend_strength or '—'}"
    )
    st.write(f"**{s2.admission_code}:** {s2.admission_reason}")
    if s2.evidence:
        evidence_frame = pd.DataFrame([row.__dict__ for row in s2.evidence]).astype("string")
        st.dataframe(evidence_frame, hide_index=True, use_container_width=True)
    with st.expander("How this decision was reached"):
        st.write(s2.explanation)


def _step_decision(st: Any, context: LifecycleContext) -> None:
    st.markdown("Canonical bundle created (Section 3).")
    view = _load_observability_view(context)
    if view is None or getattr(view, "section_3", None) is None:
        st.info("No Section 3 evidence yet.")
        return
    s3 = view.section_3
    if not s3.bundle_available:
        st.info(s3.explanation)
        return
    frame = pd.DataFrame(
        [
            ("Bundle ID", s3.bundle_id),
            ("Signal ID", s3.signal_id),
            ("Idempotency key", s3.idempotency_key),
            ("Underlying instrument", s3.underlying_instrument),
            ("Trading date", s3.trading_date),
            ("Direction", s3.direction),
            ("Option side", s3.option_side),
            ("Entry type", s3.entry_type),
            ("Evaluation timeframe", s3.evaluation_timeframe),
            ("Created at", s3.created_at),
            ("Bundle lifecycle status", s3.lifecycle_status),
        ],
        columns=["Field", "Value"],
    ).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    if s3.event_history:
        event_frame = pd.DataFrame([row.__dict__ for row in s3.event_history]).astype("string")
        st.dataframe(event_frame, hide_index=True, use_container_width=True)
    st.info(s3.explanation)


def _step_scoring_selection(st: Any, context: LifecycleContext) -> None:
    st.markdown("Architecture parity between legacy and canonical (Section 4).")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="scoring_selection",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    view = _load_observability_view(context)
    if view is None or getattr(view, "parity", None) is None:
        st.info("No Section 4 evidence yet.")
        return
    parity = view.parity
    st.metric("Overall parity", parity.overall)
    if parity.rows:
        parity_frame = pd.DataFrame([row.__dict__ for row in parity.rows]).astype("string")
        st.dataframe(parity_frame, hide_index=True, use_container_width=True)
    if parity.mismatches:
        st.warning("Mismatch fields: " + ", ".join(parity.mismatches))
    st.caption(parity.explanation)


def _step_risk_gates(st: Any, context: LifecycleContext) -> None:
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="risk_gates",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    st.markdown("Persistence integrity (Section 5).")
    view = _load_observability_view(context)
    if view is None or getattr(view, "persistence", None) is None:
        st.info("No Section 5 evidence yet.")
        return
    persistence = view.persistence
    frame = pd.DataFrame(
        [
            ("Resolution ID", persistence.resolution_id),
            ("Correlation ID", persistence.source_replay_id),
            ("Resolution schema", persistence.schema_version),
            ("Bundle schema", persistence.bundle_schema_version),
            ("Payload integrity", persistence.payload_integrity),
            ("Persisted timestamp", persistence.persisted_at),
            ("Market-event timestamp", persistence.event_timestamp),
            ("Persistence delay seconds", persistence.persistence_delay_seconds),
            ("Lifecycle event count", persistence.event_count),
            ("Persistence state", persistence.persistence_outcome),
        ],
        columns=["Field", "Value"],
    ).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.success(persistence.explanation)


def _step_queue(st: Any, context: LifecycleContext) -> None:
    st.markdown("Recent canonical observations (Section 6).")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="queue",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    view = _load_observability_view(context)
    if view is None:
        st.info("No observations yet.")
        return
    history = view.history
    if not history:
        st.info("No recent observations are available.")
        return
    frame = pd.DataFrame([row.__dict__ for row in history]).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _step_entry(st: Any, context: LifecycleContext) -> None:
    st.markdown("Opportunity availability (Section 8).")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="entry",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    bundle_id = _current_bundle_id(context)
    st.caption(
        "This stage is read-only. It does not reserve a bundle or create a "
        "paper order. Canonical execution remains observation-only."
    )
    if not bundle_id:
        st.info("WAITING: no canonical bundle is available for opportunity processing.")
        return
    st.success(
        f"AVAILABLE: canonical bundle {bundle_id} can be observed by the "
        "downstream reservation boundary."
    )


def _step_mark_monitor(st: Any, context: LifecycleContext) -> None:
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="mark_monitor",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    st.markdown("Reservation boundary (Section 9).")
    bundle_id = _current_bundle_id(context)
    st.caption(
        "Read-only. No capital, order, or position is created. This section "
        "cannot acquire, renew, release, reject, or expire a reservation."
    )
    if not context.settings.red_bar_v2_canonical_reservation_enabled:
        st.info("Reservation boundary implemented; automatic reservation is disabled.")
        return
    if bundle_id is None:
        st.info("No canonical bundle is available for reservation observation.")
        return
    result = _load_reservation(context, bundle_id)
    if result is None:
        st.info("Reservation storage is currently unavailable.")
        return
    if result.status == "NO_RESERVATION":
        st.info("No persisted reservation exists for the selected canonical bundle.")
        return
    if result.status == "RESERVATION_DATA_CORRUPT":
        st.error(
            "Persisted reservation evidence failed integrity or lifecycle "
            "validation. No reservation evidence is trusted."
        )
        return
    if result.status == "RESERVATION_DATABASE_UNAVAILABLE":
        st.info("Reservation storage is currently unavailable.")
        return
    reservation = getattr(result, "reservation", None)
    if reservation is None:
        st.error("Reservation observability failed.")
        return
    frame = pd.DataFrame(
        [
            ("Reservation feature", "ENABLED"),
            ("Reservation state", reservation.state.value),
            ("Reservation ID", reservation.reservation_id),
            ("Bundle ID", reservation.bundle_id),
            ("Owner ID", reservation.owner_id),
            ("Reserved timestamp", reservation.reserved_at.isoformat()),
            ("Lease expiry", reservation.lease_expires_at.isoformat()),
            ("Released timestamp", reservation.released_at.isoformat() if reservation.released_at else None),
            ("Reason code", reservation.release_reason),
        ],
        columns=["Field", "Value"],
    ).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    if getattr(result, "events", None):
        event_frame = pd.DataFrame(
            [
                {
                    "Event type": item.event_type,
                    "Event timestamp": item.event_timestamp.isoformat(),
                    "Owner ID": item.owner_id,
                    "Reason code": item.reason_code,
                }
                for item in result.events
            ]
        ).astype("string")
        st.dataframe(event_frame, hide_index=True, use_container_width=True)


def _step_exit_health(st: Any, context: LifecycleContext) -> None:
    st.markdown("Canonical paper execution observation.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="entry",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    bundle_id = _current_bundle_id(context)
    observation = _load_paper_execution_observation(context, bundle_id)
    if observation is None:
        st.info(
            "No canonical paper execution observation is available. "
            "The canonical subsystem has not been enabled to record commands yet."
        )
        return
    if observation.status == "NO_CANONICAL_EXECUTION":
        st.info("NO_CANONICAL_EXECUTION — no canonical paper command exists for this bundle.")
        return
    if observation.command is not None:
        st.dataframe(
            pd.DataFrame([observation.command.__dict__]).astype("string"),
            hide_index=True,
            use_container_width=True,
        )
    if observation.events:
        st.dataframe(
            pd.DataFrame([event.__dict__ for event in observation.events]).astype("string"),
            hide_index=True,
            use_container_width=True,
        )


def _step_close(st: Any, context: LifecycleContext) -> None:
    st.markdown("Canonical paper canary runtime observation.")
    from red_bar_lab.ui.live_cadence import render_pipeline_sub_status

    render_pipeline_sub_status(
        st,
        section_id="close",
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    observation = _load_canary_observation(context)
    if observation is None:
        st.info("Paper canary runtime is not yet available.")
        return
    status = observation.status
    cols = st.columns(4)
    cols[0].metric("Worker enabled", "YES" if context.settings.red_bar_v2_paper_canary_worker_enabled else "NO")
    cols[1].metric("Mode", context.settings.red_bar_v2_canonical_paper_execution_mode)
    cols[2].metric("Runtime status", status)
    cols[3].metric("Daily action count", observation.daily_action_count)
    st.caption(
        f"Cycle limit: {context.settings.red_bar_v2_paper_canary_max_actions_per_day} actions/day. "
        f"Bundle freshness: ≤ {context.settings.red_bar_v2_paper_canary_max_bundle_age_seconds:g} seconds. "
        f"Failure threshold: {context.settings.red_bar_v2_paper_canary_failure_threshold}."
    )


def _step_attribution(st: Any, context: LifecycleContext) -> None:
    st.markdown("Process explanation and status header.")
    view = _load_observability_view(context)
    if view is None:
        st.info("No canonical observation yet.")
        return
    status = view.status
    cols = st.columns(4)
    cols[0].metric("Feature configured", "ENABLED" if status.feature_enabled else "DISABLED")
    cols[1].metric("Persistence", status.availability)
    cols[2].metric("Freshness", status.freshness)
    cols[3].metric("Execution authority", status.authority)
    st.caption(
        f"Canonical authority: {status.canonical_authority} · "
        f"Database: {status.database_display} · "
        f"Runtime telemetry: {status.runtime_telemetry}"
    )
    if status.latest_event_timestamp is not None:
        st.caption(
            f"Latest canonical observation: {status.latest_event_timestamp.isoformat()}"
        )
    with st.expander("Process explanation"):
        st.markdown(
            "1. Legacy Red Bar V2 completed its authoritative evaluation.\n"
            "2. The newest admission event was copied into an immutable compact snapshot.\n"
            "3. The canonical state machine interpreted the same event-time evidence.\n"
            "4. Legacy and canonical outcomes were compared.\n"
            "5. The canonical resolution was stored as observational evidence.\n"
            "6. No order, position or exit was changed by this process."
        )


def _step_persistence_audit(st: Any, context: LifecycleContext) -> None:
    st.markdown("Promotion readiness gates.")
    st.caption(
        "This is a static view of the 10 promotion gates from "
        "docs/strategy/red_bar_v2_promotion_readiness.md. Live gate progress "
        "is not computed on this page."
    )
    gates = [
        ("G1", "Specification frozen", "Spec", "DONE"),
        ("G2", "Shared RSI/VWAP context implemented and tested", "Code", "DONE"),
        ("G3", "V2 reference, direction, reversal, admission engines implemented", "Code", "DONE"),
        ("G4", "Historical replay completed", "Replay", "PARTIAL"),
        ("G5", "Legacy paper test completed", "Test", "PARTIAL"),
        ("G6", "Legacy-versus-worker parity validated", "Parity", "IN PROGRESS"),
        ("G7", "Restart / stale / duplicate / missed-candle tests passed", "Test", "DONE"),
        ("G8", "Candidate persistence promoted to the independent worker", "Migration", "PENDING"),
        ("G9", "Execution remains behind existing committee / risk / portfolio gates", "Policy", "PENDING"),
        ("G10", "No live broker trading authorized", "Policy", "DONE"),
    ]
    frame = pd.DataFrame(gates, columns=["Gate", "Description", "Type", "Status"]).astype("string")
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _current_bundle_id(context: LifecycleContext) -> str | None:
    view = _load_observability_view(context)
    if view is None or getattr(view, "section_3", None) is None:
        return None
    if not view.section_3.bundle_available:
        return None
    return view.section_3.bundle_id


def _build_steps() -> list[LifecycleStep]:
    return [
        make_step(
            step_id="signal_discovery",
            title="Reference Readiness",
            description="Canonical reference and shared market context (Section 1).",
            renderer=_step_signal_discovery,
        ),
        make_step(
            step_id="lifecycle_eligibility",
            title="Decision",
            description="Canonical state machine admission (Section 2).",
            renderer=_step_lifecycle_eligibility,
        ),
        make_step(
            step_id="decision",
            title="Signal Bundle",
            description="Immutable canonical bundle creation (Section 3).",
            renderer=_step_decision,
        ),
        make_step(
            step_id="scoring_selection",
            title="Architecture Parity",
            description="Legacy vs canonical field-by-field comparison (Section 4).",
            renderer=_step_scoring_selection,
        ),
        make_step(
            step_id="risk_gates",
            title="Persistence & Integrity",
            description="Resolution payload integrity and persistence delay (Section 5).",
            renderer=_step_risk_gates,
        ),
        make_step(
            step_id="queue",
            title="Recent Observations",
            description="Recent canonical shadow history (Section 6).",
            renderer=_step_queue,
        ),
        make_step(
            step_id="entry",
            title="Opportunity Queue",
            description="Read-only opportunity availability (Section 8).",
            renderer=_step_entry,
        ),
        make_step(
            step_id="mark_monitor",
            title="Reservation Boundary",
            description="Read-only reservation state, lease, and events (Section 9).",
            renderer=_step_mark_monitor,
        ),
        make_step(
            step_id="exit_health",
            title="Paper Execution",
            description="Canonical paper command observation (no orders opened).",
            renderer=_step_exit_health,
        ),
        make_step(
            step_id="close",
            title="Paper Canary",
            description="Canary runtime status, mode, and action budget.",
            renderer=_step_close,
        ),
        make_step(
            step_id="attribution",
            title="Process & Status",
            description="Canonical authority, persistence, and freshness header.",
            renderer=_step_attribution,
        ),
        make_step(
            step_id="persistence_audit",
            title="Promotion Gates",
            description="Static view of the 10-gate promotion-readiness matrix.",
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
        process_name="v2_lifecycle_canonical_render",
        database=database,
        run_id=st.session_state.get("live_cadence_last_run_id"),
    )
    _maybe_schedule_live_rerun(st)


def _maybe_schedule_live_rerun(st: Any) -> None:
    """Sleep for the configured poll interval, then rerun."""
    if not st.session_state.get(LIVE_MODE_KEY):
        return
    import time

    poll_interval = int(
        st.session_state.get("live_cadence_poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    )
    time.sleep(max(1, poll_interval))
    st.rerun()
