from __future__ import annotations

from datetime import date
import json
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from red_bar_lab.operations.red_bar_v2_ui_snapshot import read_red_bar_v2_ui_snapshot
from red_bar_lab.services.red_bar_v2_canonical.observability_repository import (
    SQLiteRedBarV2CanonicalObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.observability_service import (
    RedBarV2CanonicalObservabilityService,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_observability import (
    SQLiteCanonicalPaperExecutionObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_market_data_evidence import (
    read_market_data_evidence,
    read_stage_latency,
)
from red_bar_lab.services.red_bar_v2_contract_selection_evidence import (
    read_contract_selection_evidence,
)
from red_bar_lab.services.red_bar_v2_trade_lifecycle import (
    build_position_snapshot,
    build_trade_lifecycle,
)
from red_bar_lab.services.red_bar_v2_comparison_analytics import (
    build_canonical_performance,
    build_legacy_performance,
)
from red_bar_lab.ui.red_bar_v2_live_runtime import resolve_red_bar_v2_live_state
from red_bar_lab.ui.red_bar_v2_stage_catalog import RED_BAR_V2_STAGES


def _value(value: object, fallback: str = "Not available") -> str:
    return fallback if value in (None, "") else str(value)


def _diagnostic(diagnostics: Any, name: str) -> object:
    if isinstance(diagnostics, Mapping):
        return diagnostics.get(name)
    return getattr(diagnostics, name, None)


def _safe_read(callable_value, fallback):
    try:
        return callable_value()
    except Exception:
        return fallback


def _latency_evidence(settings) -> dict[str, object]:
    path = settings.artifacts_root / "paper_monitor_latency.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _legacy_stage_rows(database, settings, instrument_key: str, trading_date: str):
    file_snapshot = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
    snapshot, diagnostics = resolve_red_bar_v2_live_state(
        database,
        file_snapshot,
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    signal_id = _diagnostic(diagnostics, "signal_id")
    queues = _safe_read(lambda: database.read_execution_queue(trading_date=trading_date, limit=500), [])
    queue_rows = [row for row in queues if str(row.get("signal_id") or "") == str(signal_id or "")]
    orders = _safe_read(lambda: database.read_paper_execution_orders("PAPER-STD"), [])
    signal_orders = [row for row in orders if str(row.get("signal_id") or "") == str(signal_id or "")]
    monitor = _safe_read(lambda: database.read_paper_monitor_status(), None) or {}

    readiness_ok = bool(
        _diagnostic(diagnostics, "market_context_ready")
        and _diagnostic(diagnostics, "reference_found")
    )
    admission = getattr(snapshot, "admission_allowed", None) if snapshot else None
    return {
        "INPUT_READINESS": ("READY" if readiness_ok else "WAITING", _value(_diagnostic(diagnostics, "alignment_blocking_reasons"), "Required candle/reference evidence is ready"), {
            "Market context ready": _diagnostic(diagnostics, "market_context_ready"),
            "Reference found": _diagnostic(diagnostics, "reference_found"),
            "Reference quality": _diagnostic(diagnostics, "reference_data_quality"),
            "Index timestamp": getattr(snapshot, "index_timestamp", None) if snapshot else None,
            "Futures timestamp": getattr(snapshot, "futures_timestamp", None) if snapshot else None,
            "Last evaluation": getattr(snapshot, "last_evaluation_timestamp", None) if snapshot else None,
        }),
        "STRATEGY_DECISION": ("PASSED" if admission else "WAITING", _value(getattr(snapshot, "admission_reason", None) if snapshot else None, "No admitted legacy decision"), {
            "Direction": getattr(snapshot, "direction", None) if snapshot else None,
            "Option side": getattr(snapshot, "option_side", None) if snapshot else None,
            "RSI": getattr(snapshot, "index_rsi", None) if snapshot else None,
            "Futures close": getattr(snapshot, "futures_close", None) if snapshot else None,
            "Futures VWAP": getattr(snapshot, "futures_vwap", None) if snapshot else None,
            "Midpoint confirmation": getattr(snapshot, "midpoint_confirmation", None) if snapshot else None,
        }),
        "SIGNAL_BUNDLE": ("READY" if signal_id else "WAITING", _value(_diagnostic(diagnostics, "terminal_condition"), "Waiting for a confirmed legacy signal"), {
            "Legacy artifact": "SIGNAL_ATTEMPT",
            "Correlation ID": getattr(snapshot, "correlation_id", None) if snapshot else None,
            "Signal ID": signal_id,
            "Confirmation time": _diagnostic(diagnostics, "confirmation_timestamp"),
            "Signal age seconds": _diagnostic(diagnostics, "signal_age_seconds"),
        }),
        "ARCHITECTURE_PARITY": ("OBSERVATIONAL", "Canonical parity owns the cross-architecture comparison", {"Legacy submitted signal": signal_id}),
        "PERSISTENCE_INTEGRITY": ("READY" if signal_id else "WAITING", "Legacy signal and lifecycle records are read from durable storage", {"Signal ID": signal_id, "Source status": _diagnostic(diagnostics, "source_status")}),
        "RECENT_OBSERVATIONS": ("READY" if diagnostics else "WAITING", "Current-day legacy runtime trace", {"Pipeline updated": _diagnostic(diagnostics, "pipeline_updated_at")}),
        "PROCESS_EXPLANATION": ("COMPLETED", "Input evidence is evaluated, published, scored, queued and paper-executed", {"Current terminal condition": _diagnostic(diagnostics, "terminal_condition")}),
        "OPPORTUNITY_QUEUE": ("READY" if queue_rows else "WAITING", "Queue evidence for the selected signal", {"Queue records": len(queue_rows), "Latest state": queue_rows[-1].get("status") if queue_rows else None, "Latest reason": queue_rows[-1].get("reason") if queue_rows else "Waiting for an approved candidate"}),
        "RESERVATION_BOUNDARY": ("PASSED" if len(signal_orders) < 2 else "BLOCKED", "Legacy duplicate and two-entry capacity boundary", {"Persisted entries": len(signal_orders), "Maximum entries": 2}),
        "PAPER_EXECUTION": ("COMPLETED" if signal_orders else "WAITING", "Legacy V2 is the active paper authority", {"Paper orders": len(signal_orders), "Order IDs": ", ".join(str(row.get("order_id")) for row in signal_orders) or None}),
        "RUNTIME_HEALTH": (_value(monitor.get("status"), "WAITING"), _value(monitor.get("last_reason"), "Paper monitor status unavailable"), {"State": monitor.get("current_state"), "Heartbeat": monitor.get("heartbeat_at"), "Last scan": monitor.get("last_scan_at")}),
        "PROVIDER_READINESS": ("READY" if readiness_ok else "WAITING", "Provider evidence consumed by the legacy evaluator", {"Index timestamp": getattr(snapshot, "index_timestamp", None) if snapshot else None, "Futures timestamp": getattr(snapshot, "futures_timestamp", None) if snapshot else None}),
    }


def _canonical_stage_rows(settings, instrument_key: str):
    view = RedBarV2CanonicalObservabilityService(
        SQLiteRedBarV2CanonicalObservabilityRepository(settings.database_path),
        database_path=settings.database_path,
    ).load(
        instrument_key=instrument_key,
        feature_enabled=settings.red_bar_v2_canonical_shadow_enabled,
        limit=25,
    )
    unavailable = (view.status.availability, "No trusted canonical observation is available", {})
    if not all((view.section_1, view.section_2, view.section_3, view.parity, view.persistence)):
        return {stage.stage_id: unavailable for stage in RED_BAR_V2_STAGES}
    s1, s2, s3 = view.section_1, view.section_2, view.section_3
    return {
        "INPUT_READINESS": (s1.outcome, s1.explanation, {"Reason code": s1.reason_code, "Index timestamp": s1.latest_index_timestamp, "Futures timestamp": s1.latest_futures_timestamp}),
        "STRATEGY_DECISION": (s2.admission_outcome, s2.admission_reason, {"Direction": s2.direction, "Option side": s2.option_side, "Entry type": s2.entry_type, "State": s2.current_state}),
        "SIGNAL_BUNDLE": ("READY" if s3.bundle_available else "WAITING", s3.explanation, {"Artifact": "CANONICAL_BUNDLE", "Bundle ID": s3.bundle_id, "Signal ID": s3.signal_id, "Created at": s3.created_at}),
        "ARCHITECTURE_PARITY": (view.parity.overall, view.parity.explanation, {"Mismatches": ", ".join(view.parity.mismatches) or "None"}),
        "PERSISTENCE_INTEGRITY": (view.persistence.payload_integrity, view.persistence.explanation, {"Correlation ID": view.persistence.source_replay_id, "Resolution ID": view.persistence.resolution_id, "Persisted at": view.persistence.persisted_at, "Delay seconds": view.persistence.persistence_delay_seconds}),
        "RECENT_OBSERVATIONS": ("READY" if view.history else "WAITING", f"{len(view.history)} recent canonical observations", {}),
        "PROCESS_EXPLANATION": ("COMPLETED", "Canonical evidence was resolved, compared and persisted without execution authority", {}),
        "OPPORTUNITY_QUEUE": ("OBSERVATIONAL", "Canonical opportunity evidence is read-only during shadow comparison", {"Bundle ID": s3.bundle_id}),
        "RESERVATION_BOUNDARY": ("OBSERVATIONAL", "Canonical reservation is displayed on the canonical page", {"Bundle ID": s3.bundle_id}),
        "PAPER_EXECUTION": ("SHADOW", "Canonical paper execution remains canary/shadow while legacy owns execution", {"Execution authority": view.status.authority}),
        "RUNTIME_HEALTH": (view.status.runtime_telemetry, "Canonical shadow runtime telemetry", {"Latest event": view.status.latest_event_timestamp}),
        "PROVIDER_READINESS": (view.status.freshness, "Canonical provider readiness is displayed in Section 12", {"Availability": view.status.availability}),
    }


def _render_bounded_analytics(settings, database, instrument_key: str, trading_date: str) -> None:
    st.markdown("### Bounded Historical and Live Performance")
    st.caption(
        "Read-only persisted evidence: at most 500 legacy records for the "
        "selected date and 100 canonical shadow observations."
    )
    signals = _safe_read(
        lambda: database.read_signal_attempts(instrument_key, trading_date), []
    )
    signals = [
        row for row in signals
        if str(row.get("level_type") or "") == "RED_BAR_V2"
    ][:500]
    orders = _safe_read(
        lambda: database.read_paper_execution_orders("PAPER-STD"), []
    )[:500]
    canonical_view = _safe_read(
        lambda: RedBarV2CanonicalObservabilityService(
            SQLiteRedBarV2CanonicalObservabilityRepository(settings.database_path),
            database_path=settings.database_path,
        ).load(
            instrument_key=instrument_key,
            feature_enabled=settings.red_bar_v2_canonical_shadow_enabled,
            limit=100,
        ),
        None,
    )
    canonical_history = canonical_view.history if canonical_view is not None else ()
    legacy_metrics = build_legacy_performance(
        signals=signals, orders=orders, maximum_records=500
    )
    canonical_metrics = build_canonical_performance(
        canonical_history, maximum_records=100
    )
    columns = st.columns(2)
    for column, heading, metrics in (
        (columns[0], "Legacy V2 paper performance", legacy_metrics),
        (columns[1], "Canonical V2 shadow performance", canonical_metrics),
    ):
        with column:
            st.markdown(f"**{heading}**")
            st.dataframe(
                pd.DataFrame(
                    [{"Metric": key, "Value": _value(value)} for key, value in metrics.items()],
                    dtype="string",
                ),
                hide_index=True,
                use_container_width=True,
            )

    with st.expander("Legacy signal-to-trade history"):
        orders_by_signal: dict[str, list[dict[str, object]]] = {}
        for order in orders:
            orders_by_signal.setdefault(
                str(order.get("signal_id") or ""), []
            ).append(order)
        rows = []
        for signal in signals[:100]:
            signal_id = str(signal.get("signal_id") or "")
            signal_orders = orders_by_signal.get(signal_id, [])
            closed = [row for row in signal_orders if row.get("status") == "CLOSED"]
            rows.append({
                "Signal ID": signal_id,
                "Correlation ID": signal.get("run_id"),
                "Direction": signal.get("direction"),
                "Confirmed": signal.get("confirmation_timestamp"),
                "Entries": len(signal_orders),
                "First entry": min(
                    (str(row.get("entry_timestamp")) for row in signal_orders),
                    default="Not entered",
                ),
                "Closed": len(closed),
                "Realized P&L": round(
                    sum(float(row.get("realized_pnl") or 0.0) for row in closed), 2
                ),
                "Latest exit reason": closed[0].get("exit_reason") if closed else None,
            })
        if rows:
            st.dataframe(
                pd.DataFrame(rows, dtype="string"),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No persisted legacy V2 signals exist for the selected date.")

    with st.expander("Canonical shadow observation history"):
        rows = [{
            "Event time": row.event_time,
            "Trading date": row.trading_date,
            "Input readiness": row.section_1_outcome,
            "Admission": row.admission_outcome,
            "Direction": row.direction,
            "Option side": row.option_side,
            "Entry type": row.entry_type,
            "Parity": row.parity,
            "Bundle": row.bundle_available,
            "Freshness": row.freshness,
        } for row in canonical_history[:100]]
        if rows:
            st.dataframe(
                pd.DataFrame(rows, dtype="string"),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No canonical shadow observations are available.")


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Red Bar V2 Dual-Path Comparison")
    st.caption("Read-only evidence comparison. Legacy V2 remains paper-execution authority; canonical V2 remains shadow/canary. This page performs no market-data download, strategy calculation, queue mutation or order action.")
    trading_date = st.date_input("Trading date", value=date.today(), key="red_bar_v2_comparison_date").isoformat()
    legacy = _legacy_stage_rows(database, settings, instrument_key, trading_date)
    canonical = _safe_read(lambda: _canonical_stage_rows(settings, instrument_key), {stage.stage_id: ("UNAVAILABLE", "Canonical evidence read failed", {}) for stage in RED_BAR_V2_STAGES})
    market_data = read_market_data_evidence(settings.artifacts_root)
    contract_selection = read_contract_selection_evidence(settings.artifacts_root)
    legacy_latency = read_stage_latency(settings.artifacts_root, "legacy")
    canonical_latency = read_stage_latency(settings.artifacts_root, "canonical")
    datasets = market_data.get("datasets") if isinstance(market_data.get("datasets"), list) else []
    legacy_correlation = legacy["SIGNAL_BUNDLE"][2].get("Correlation ID")
    legacy_signal_id = str(
        legacy["SIGNAL_BUNDLE"][2].get("Signal ID") or ""
    )
    canonical_correlation = canonical["PERSISTENCE_INTEGRITY"][2].get("Correlation ID")
    canonical_bundle_id = canonical["SIGNAL_BUNDLE"][2].get("Bundle ID")
    canonical_execution = (
        _safe_read(
            lambda: SQLiteCanonicalPaperExecutionObservabilityRepository(
                settings.database_path
            ).latest_for_bundle(bundle_id=str(canonical_bundle_id)),
            None,
        )
        if canonical_bundle_id
        else None
    )
    identity_status = (
        "MATCH"
        if legacy_correlation and canonical_correlation and legacy_correlation == canonical_correlation
        else "WAITING"
        if not legacy_correlation or not canonical_correlation
        else "MISMATCH"
    )
    legacy_latency_matches = bool(
        legacy_correlation
        and legacy_latency.get("correlation_id") == legacy_correlation
    )
    canonical_latency_matches = bool(
        canonical_correlation
        and canonical_latency.get("correlation_id") == canonical_correlation
    )
    legacy_timing_by_stage = {
        row.get("stage_id"): row
        for row in legacy_latency.get("stages", [])
        if isinstance(row, dict)
    }
    canonical_timing_by_stage = {
        row.get("stage_id"): row
        for row in canonical_latency.get("stages", [])
        if isinstance(row, dict)
    }
    matching_selections = [
        row
        for row in contract_selection.get("selections", [])
        if isinstance(row, dict)
        and legacy_correlation
        and row.get("correlation_id") == legacy_correlation
    ]
    lifecycle_events = _safe_read(
        lambda: database.read_execution_state_events(
            signal_id=legacy_signal_id,
            limit=500,
        ),
        [],
    ) if legacy_signal_id else []
    lifecycle_queue = _safe_read(
        lambda: database.read_execution_queue(
            signal_id=legacy_signal_id,
            limit=100,
        ),
        [],
    ) if legacy_signal_id else []
    lifecycle_orders = _safe_read(
        lambda: database.read_paper_execution_orders("PAPER-STD"),
        [],
    ) if legacy_signal_id else []
    lifecycle = build_trade_lifecycle(
        signal_id=legacy_signal_id,
        state_events=lifecycle_events,
        queue_rows=lifecycle_queue,
        orders=lifecycle_orders,
    ) if legacy_signal_id else ()
    positions = build_position_snapshot(
        lifecycle_orders,
        signal_id=legacy_signal_id,
    ) if legacy_signal_id else ()
    identity_columns = st.columns(3)
    identity_columns[0].metric("Correlation parity", identity_status)
    identity_columns[1].metric("Legacy correlation", _value(legacy_correlation))
    identity_columns[2].metric("Canonical correlation", _value(canonical_correlation))
    if identity_status == "MISMATCH":
        st.error(
            "The two paths did not evaluate the same correlated market event; "
            "stage comparison must not be treated as parity evidence."
        )
    latency = _latency_evidence(settings)
    timings = latency.get("timings_ms") if isinstance(latency.get("timings_ms"), dict) else {}
    if timings:
        metrics = st.columns(4)
        metrics[0].metric("Last monitor cycle", f"{float(timings.get('total') or 0.0):,.1f} ms")
        metrics[1].metric("V2 evaluation", f"{float(timings.get('v2_evaluation') or 0.0):,.1f} ms")
        metrics[2].metric("Entry automation", f"{float(timings.get('automation') or 0.0):,.1f} ms")
        metrics[3].metric("Slowest stage", _value(latency.get("slowest_stage")))
        st.caption(
            f"Cycle: {_value(latency.get('cycle_started_at'))} to "
            f"{_value(latency.get('cycle_completed_at'))}. Timing is written "
            "after execution processing and cannot block a trade."
        )
    else:
        st.info("Waiting for the next paper-monitor cycle to publish stage latency evidence.")

    rows = []
    for stage in RED_BAR_V2_STAGES:
        legacy_status, legacy_reason, _ = legacy[stage.stage_id]
        canonical_status, canonical_reason, _ = canonical[stage.stage_id]
        parity = "MATCH" if legacy_status == canonical_status else "DIFFERENT"
        legacy_timing = legacy_timing_by_stage.get(stage.stage_id, {}) if legacy_latency_matches else {}
        canonical_timing = canonical_timing_by_stage.get(stage.stage_id, {}) if canonical_latency_matches else {}
        rows.append({
            "Section": stage.number,
            "Stage": stage.label,
            "Legacy V2": legacy_status,
            "Legacy latency (ms)": _value(legacy_timing.get("duration_ms")),
            "Canonical V2": canonical_status,
            "Canonical latency (ms)": _value(canonical_timing.get("duration_ms")),
            "Comparison": parity,
            "Legacy reason": legacy_reason,
            "Canonical reason": canonical_reason,
        })
    st.dataframe(pd.DataFrame(rows, dtype="string"), hide_index=True, use_container_width=True)

    for stage in RED_BAR_V2_STAGES:
        with st.expander(stage.display_name):
            legacy_status, legacy_reason, legacy_evidence = legacy[stage.stage_id]
            canonical_status, canonical_reason, canonical_evidence = canonical[stage.stage_id]
            legacy_timing = legacy_timing_by_stage.get(stage.stage_id, {}) if legacy_latency_matches else {}
            canonical_timing = canonical_timing_by_stage.get(stage.stage_id, {}) if canonical_latency_matches else {}
            st.markdown(f"**Legacy V2 — {legacy_status}:** {legacy_reason}")
            st.dataframe(pd.DataFrame([{"Evidence": key, "Value": _value(value)} for key, value in legacy_evidence.items()], dtype="string"), hide_index=True, use_container_width=True)
            st.caption(
                f"Legacy timing: {_value(legacy_timing.get('duration_ms'))} ms; "
                f"status: {_value(legacy_timing.get('status'), 'Waiting')}; "
                f"{_value(legacy_timing.get('detail'), 'No correlated timing evidence yet')}"
            )
            if stage.stage_id == "INPUT_READINESS":
                st.markdown("**Candle download evidence**")
                if datasets:
                    columns = (
                        "dataset", "instrument_key", "provider", "status", "reason",
                        "requested_at", "received_at", "duration_ms", "row_count",
                        "first_timestamp", "latest_timestamp",
                        "latest_completed_timestamp", "expected_completed_timestamp",
                        "freshness_seconds", "duplicate_timestamps",
                        "missing_intervals", "source_mode", "retry_count",
                    )
                    st.dataframe(
                        pd.DataFrame(
                            [{name: row.get(name) for name in columns} for row in datasets],
                            dtype="string",
                        ),
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        f"Evidence correlation: {_value(market_data.get('correlation_id'))}; "
                        f"recorded after execution processing at {_value(market_data.get('recorded_at'))}."
                    )
                else:
                    st.info(
                        "WAITING: the next paper-monitor cycle has not yet published "
                        "candle download evidence."
                    )
            if stage.stage_id == "OPPORTUNITY_QUEUE":
                st.markdown("**CE/PE contract-selection evidence**")
                if matching_selections:
                    latest_selection = matching_selections[-1]
                    signal_id = str(latest_selection.get("signal_id") or "")
                    evaluations = _safe_read(
                        lambda: database.read_trade_selection_evaluations(
                            signal_id=signal_id,
                            limit=100,
                        ),
                        [],
                    )
                    queue_evaluations = _safe_read(
                        lambda: database.read_execution_queue(
                            trading_date=trading_date,
                            limit=500,
                        ),
                        [],
                    )
                    decision_by_token = {
                        str(row.get("instrument_token")): row
                        for row in evaluations
                    }
                    queue_by_token = {
                        str(row.get("instrument_token")): row
                        for row in queue_evaluations
                        if str(row.get("signal_id") or "") == signal_id
                    }
                    candidate_rows = []
                    for candidate in latest_selection.get("candidates", []):
                        if not isinstance(candidate, dict):
                            continue
                        decision = decision_by_token.get(
                            str(candidate.get("instrument_token")), {}
                        )
                        queue = queue_by_token.get(
                            str(candidate.get("instrument_token")), {}
                        )
                        candidate_rows.append({
                            "Rank": candidate.get("rank"),
                            "Contract": candidate.get("symbol"),
                            "Side": candidate.get("option_type"),
                            "Strike": candidate.get("strike"),
                            "Expiry": candidate.get("expiry"),
                            "LTP": candidate.get("ltp"),
                            "Bid": candidate.get("best_bid"),
                            "Ask": candidate.get("best_ask"),
                            "Candidate score": candidate.get("total_score"),
                            "Minimum score": candidate.get("minimum_score"),
                            "Score eligible": candidate.get("score_eligible"),
                            "Final selection": decision.get("decision", "WAITING"),
                            "Final eligible": decision.get("eligible"),
                            "Final reason": decision.get("reason", "Downstream evaluation pending"),
                            "Queue status": queue.get("status", "NOT_QUEUED"),
                            "Queue reason": queue.get("reason", "Candidate did not reach the queue"),
                        })
                    st.dataframe(
                        pd.DataFrame(candidate_rows, dtype="string"),
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        f"Signal: {signal_id}; correlation: "
                        f"{_value(latest_selection.get('correlation_id'))}; "
                        f"selection latency: {_value(latest_selection.get('duration_ms'))} ms; "
                        f"evaluated at: {_value(latest_selection.get('evaluated_at'))}."
                    )
                    with st.expander("Contract score components"):
                        score_columns = (
                            "rank", "symbol", "spread_score", "liquidity_score",
                            "volume_score", "oi_score", "vwap_score", "ema_score",
                            "momentum_score", "momentum_pct", "candle_count",
                            "evidence_detail",
                        )
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {name: candidate.get(name) for name in score_columns}
                                    for candidate in latest_selection.get("candidates", [])
                                    if isinstance(candidate, dict)
                                ],
                                dtype="string",
                            ),
                            hide_index=True,
                            use_container_width=True,
                        )
                else:
                    st.info(
                        "WAITING: no contract-selection evidence is available for "
                        "the currently correlated legacy signal."
                    )
                st.caption(
                    "Canonical V2 remains shadow-only and therefore does not "
                    "independently select or reserve option contracts."
                )
            if stage.stage_id == "RESERVATION_BOUNDARY":
                st.markdown("**Reservation and queue lifecycle**")
                reservation_rows = [
                    row
                    for row in lifecycle
                    if row.get("stage") == "RESERVATION_BOUNDARY"
                ]
                if reservation_rows:
                    st.dataframe(
                        pd.DataFrame(reservation_rows, dtype="string"),
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "WAITING: the correlated signal has not created a "
                        "reservation or execution-queue record."
                    )
                if canonical_execution is not None:
                    st.caption(
                        "Canonical reservation verification: "
                        f"{canonical_execution.status}."
                    )
            if stage.stage_id == "PAPER_EXECUTION":
                st.markdown("**Correlated paper-trade lifecycle**")
                if lifecycle:
                    st.dataframe(
                        pd.DataFrame(lifecycle, dtype="string"),
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "WAITING: no entry or execution-state evidence exists "
                        "for the correlated signal."
                    )
                st.markdown("**Position protection and exit evidence**")
                if positions:
                    st.dataframe(
                        pd.DataFrame(positions, dtype="string"),
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        "Exact exit reason is read from the persisted paper order. "
                        "Protection values show the latest persisted breakeven, "
                        "protected-stop and trailing state."
                    )
                else:
                    st.info(
                        "WAITING: the correlated signal has not opened a paper position."
                    )
                st.markdown("**Canonical paper-canary lifecycle**")
                canonical_evidence = (
                    canonical_execution.evidence
                    if canonical_execution is not None
                    else None
                )
                if canonical_evidence is not None:
                    command = canonical_evidence.command
                    st.dataframe(
                        pd.DataFrame([{
                            "Bundle ID": command.bundle_id,
                            "Reservation ID": command.reservation_id,
                            "Execution ID": command.execution_id,
                            "Contract": command.contract.tradingsymbol,
                            "Quantity": command.quantity,
                            "State": canonical_evidence.state.value,
                            "Paper order ID": canonical_evidence.paper_order_id,
                            "Reason": canonical_evidence.reason_code,
                            "Created": command.created_at.isoformat(),
                        }], dtype="string"),
                        hide_index=True,
                        use_container_width=True,
                    )
                    canonical_events = [
                        {
                            "Event": event_type.value,
                            "Timestamp": timestamp.isoformat(),
                            "Reason": reason,
                            "Paper order ID": order_id,
                        }
                        for event_type, timestamp, reason, order_id
                        in canonical_evidence.events
                    ]
                    if canonical_events:
                        st.dataframe(
                            pd.DataFrame(canonical_events, dtype="string"),
                            hide_index=True,
                            use_container_width=True,
                        )
                else:
                    status = (
                        canonical_execution.status
                        if canonical_execution is not None
                        else "NO_CANONICAL_EXECUTION"
                    )
                    st.info(
                        f"{status}: no verified canonical paper-canary lifecycle "
                        "is available for the correlated bundle."
                    )
            st.markdown(f"**Canonical V2 — {canonical_status}:** {canonical_reason}")
            st.dataframe(pd.DataFrame([{"Evidence": key, "Value": _value(value)} for key, value in canonical_evidence.items()], dtype="string"), hide_index=True, use_container_width=True)
            st.caption(
                f"Canonical timing: {_value(canonical_timing.get('duration_ms'))} ms; "
                f"status: {_value(canonical_timing.get('status'), 'Waiting')}; "
                f"{_value(canonical_timing.get('detail'), 'No correlated timing evidence yet')}"
            )

    _render_bounded_analytics(settings, database, instrument_key, trading_date)


__all__ = ["render_page"]
