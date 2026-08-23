from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.red_bar_v2_canonical.observability_repository import SQLiteRedBarV2CanonicalObservabilityRepository
from red_bar_lab.services.red_bar_v2_canonical.observability_service import RedBarV2CanonicalObservabilityService
from red_bar_lab.services.red_bar_v2_canonical.reservation_observability import SQLiteReservationObservabilityRepository
from red_bar_lab.ui.canonical_paper_canary_panel import render_canonical_paper_canary_panel
from red_bar_lab.ui.canonical_paper_execution_panel import render_canonical_paper_execution_panel
from red_bar_lab.ui.historical_red_bar_v2_windows import _render_window_panel
from red_bar_lab.ui.red_bar_v2_promotion_panel import render_red_bar_v2_promotion_panel


def _text(value: object | None) -> str:
    return "—" if value is None else str(value)


def _render_reservation_boundary(settings: RedBarSettings, bundle_id: str | None) -> None:
    st.markdown("### 8. Bundle reservation boundary")
    st.warning("RESERVED does not mean ordered or executed. No capital, order or position was created.")
    st.caption("Execution authority remains legacy-only. This section is read-only and cannot acquire, renew, release, reject or expire a reservation.")
    if not settings.red_bar_v2_canonical_reservation_enabled:
        st.info("Reservation boundary implemented; automatic reservation is disabled.")
        return
    if bundle_id is None:
        st.info("No canonical bundle is available for reservation observation.")
        return
    result = SQLiteReservationObservabilityRepository(settings.database_path).latest_for_bundle(
        bundle_id=bundle_id,
        event_limit=25,
    )
    if result.status == "NO_RESERVATION":
        st.info("No persisted reservation exists for the selected canonical bundle.")
        return
    if result.status == "RESERVATION_DATA_CORRUPT":
        st.error("Persisted reservation evidence failed integrity or lifecycle validation. No reservation evidence is trusted. Legacy execution is unaffected.")
        return
    if result.status == "RESERVATION_DATABASE_UNAVAILABLE":
        st.info("Reservation storage is currently unavailable. Legacy execution is unaffected.")
        return
    reservation = result.reservation
    if result.status != "RESERVATION_DATA_AVAILABLE" or reservation is None:
        st.error("Reservation observability failed. No reservation evidence is trusted, and legacy execution is unaffected.")
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
            ("Released timestamp", _text(reservation.released_at.isoformat() if reservation.released_at else None)),
            ("Reason code", _text(reservation.release_reason)),
        ],
        columns=["Field", "Persisted value"],
        dtype="string",
    )
    st.dataframe(frame, hide_index=True, use_container_width=True)
    if result.events:
        event_frame = pd.DataFrame(
            [
                {
                    "Event type": item.event_type,
                    "Event timestamp": item.event_timestamp.isoformat(),
                    "Owner ID": item.owner_id,
                    "Reason code": item.reason_code,
                }
                for item in result.events
            ],
            dtype="string",
        )
        st.dataframe(event_frame, hide_index=True, use_container_width=True)


def _render_execution_boundaries(settings: RedBarSettings, bundle_id: str | None) -> None:
    _render_reservation_boundary(settings, bundle_id)
    render_canonical_paper_execution_panel(st, settings, bundle_id)
    render_canonical_paper_canary_panel(st, settings)


def _render_shadow_observability(settings: RedBarSettings, instrument_key: str) -> None:
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(settings.database_path)
    view = RedBarV2CanonicalObservabilityService(repository, database_path=settings.database_path).load(
        instrument_key=instrument_key,
        feature_enabled=settings.red_bar_v2_canonical_shadow_enabled,
        limit=25,
    )

    st.subheader("Canonical Red Bar V2 Shadow Observability")
    st.warning("CANONICAL SHADOW MODE — Read-only observational architecture. Legacy Red Bar V2 owns trade execution. This page cannot create, block, modify or exit a trade.")
    st.error("NO — canonical processing is observational only. Legacy Red Bar V2 remains execution authority.")

    status = view.status
    cols = st.columns(4)
    cols[0].metric("Feature configured", "ENABLED" if status.feature_enabled else "DISABLED")
    cols[1].metric("Persistence", status.availability)
    cols[2].metric("Freshness", status.freshness)
    cols[3].metric("Execution authority", status.authority)
    st.caption(f"Canonical authority: {status.canonical_authority} | Database: {status.database_display} | Runtime telemetry: {status.runtime_telemetry}")
    if status.latest_event_timestamp is not None:
        st.caption(f"Latest canonical observation: {status.latest_event_timestamp.isoformat()} | Age: {_text(round(status.age_seconds, 2) if status.age_seconds is not None else None)} seconds")

    if status.availability == "CANONICAL_DATA_CORRUPT":
        st.error("Persisted canonical evidence failed digest, schema or projection validation. Untrusted evidence is not rendered or repaired.")
        _render_execution_boundaries(settings, None)
        return
    if status.availability == "CANONICAL_READ_FAILED":
        st.error("Canonical observability failed while building the read-only projection. No partial evidence is trusted, and legacy execution is unaffected.")
        _render_execution_boundaries(settings, None)
        return
    if status.availability in {"SHADOW_DISABLED", "WAITING_FOR_FIRST_OBSERVATION", "CANONICAL_DATABASE_UNAVAILABLE"}:
        st.info("No trusted canonical observation is available yet. Opening or refreshing this page does not initialize schema or start shadow processing.")
        _render_execution_boundaries(settings, None)
        return

    section_1, section_2, section_3, parity, persistence = view.section_1, view.section_2, view.section_3, view.parity, view.persistence
    if not all((section_1, section_2, section_3, parity, persistence)):
        st.error("Canonical projection is incomplete; no untrusted partial evidence is rendered.")
        _render_execution_boundaries(settings, None)
        return

    st.markdown("### 1. Input readiness")
    st.caption("What information was available before evaluating the strategy?")
    readiness = pd.DataFrame([
        ("Underlying instrument", section_1.underlying_instrument),
        ("Futures instrument", _text(section_1.futures_instrument)),
        ("Trading date", _text(section_1.trading_date)),
        ("Reference status", section_1.reference_status),
        ("Reference high", _text(section_1.reference_high)),
        ("Reference low", _text(section_1.reference_low)),
        ("Reference midpoint", _text(section_1.reference_midpoint)),
        ("Index timestamp", _text(section_1.latest_index_timestamp)),
        ("Futures timestamp", _text(section_1.latest_futures_timestamp)),
        ("Context status", section_1.context_status),
        ("Futures volume available", str(section_1.futures_volume_available)),
        ("Futures VWAP available", str(section_1.futures_vwap_available)),
        ("Section 1 outcome", section_1.outcome),
        ("Reason code", section_1.reason_code),
    ], columns=["Field", "Persisted event-time value"], dtype="string")
    st.dataframe(readiness, hide_index=True, use_container_width=True)
    st.info(section_1.explanation)

    st.markdown("### 2. Canonical strategy decision")
    st.caption("What did the canonical Red Bar V2 state machine decide?")
    decision_cols = st.columns(4)
    decision_cols[0].metric("Admission", section_2.admission_outcome)
    decision_cols[1].metric("Direction", _text(section_2.direction))
    decision_cols[2].metric("Option side", _text(section_2.option_side))
    decision_cols[3].metric("Entry type", _text(section_2.entry_type))
    st.caption(f"State: {section_2.previous_state} → {section_2.current_state} | Timeframe: {section_2.evaluation_timeframe} | Trend strength: {_text(section_2.trend_strength)}")
    if section_2.evidence:
        evidence = pd.DataFrame([asdict(item) for item in section_2.evidence]).astype("string")
        evidence.columns = ["Evidence", "Numeric value", "Required interpretation", "Actual alignment"]
        st.dataframe(evidence, hide_index=True, use_container_width=True)
    st.write(f"**{section_2.admission_code}:** {section_2.admission_reason}")
    with st.expander("How this decision was reached"):
        st.write(section_2.explanation)

    st.markdown("### 3. RED BAR V2 CANONICAL BUNDLE")
    st.caption("Was an immutable opportunity bundle produced?")
    if section_3.bundle_available:
        bundle = pd.DataFrame([
            ("Bundle available", "YES"),
            ("Bundle ID", _text(section_3.bundle_id)),
            ("Signal ID", _text(section_3.signal_id)),
            ("Idempotency key", _text(section_3.idempotency_key)),
            ("Underlying instrument", _text(section_3.underlying_instrument)),
            ("Trading date", _text(section_3.trading_date)),
            ("Direction", _text(section_3.direction)),
            ("Option side", _text(section_3.option_side)),
            ("Entry type", _text(section_3.entry_type)),
            ("Evaluation timeframe", _text(section_3.evaluation_timeframe)),
            ("Created at", _text(section_3.created_at)),
            ("Bundle lifecycle status", _text(section_3.lifecycle_status)),
        ], columns=["Field", "Value"], dtype="string")
        st.dataframe(bundle, hide_index=True, use_container_width=True)
        if section_3.event_history:
            event_frame = pd.DataFrame([asdict(item) for item in section_3.event_history]).astype("string")
            event_frame.columns = ["Audit event type", "Event timestamp", "Source", "Reason code"]
            st.dataframe(event_frame, hide_index=True, use_container_width=True)
        st.info(section_3.explanation)
    else:
        st.info(section_3.explanation)

    st.markdown("### 4. Legacy ↔ canonical parity")
    st.caption("Did canonical Red Bar V2 agree with the authoritative legacy decision?")
    st.metric("Overall parity", parity.overall)
    if parity.rows:
        parity_frame = pd.DataFrame([asdict(row) for row in parity.rows]).astype("string")
        parity_frame.columns = ["Field", "Legacy", "Canonical", "Status"]
        st.dataframe(parity_frame, hide_index=True, use_container_width=True)
    if parity.mismatches:
        st.warning("Mismatch fields: " + ", ".join(parity.mismatches))
    st.caption(parity.explanation)

    st.markdown("### 5. Persistence and integrity")
    integrity = pd.DataFrame([
        ("Resolution ID", persistence.resolution_id),
        ("Source replay ID", persistence.source_replay_id),
        ("Resolution schema", persistence.schema_version),
        ("Bundle schema", _text(persistence.bundle_schema_version)),
        ("Payload integrity", persistence.payload_integrity),
        ("Persisted timestamp", _text(persistence.persisted_at)),
        ("Market-event timestamp", _text(persistence.event_timestamp)),
        ("Persistence delay seconds", _text(persistence.persistence_delay_seconds)),
        ("Lifecycle event count", str(persistence.event_count)),
        ("Persistence state", _text(persistence.persistence_outcome)),
    ], columns=["Field", "Value"], dtype="string")
    st.dataframe(integrity, hide_index=True, use_container_width=True)
    st.success(persistence.explanation)

    st.markdown("### 6. Recent canonical observations")
    history = pd.DataFrame([asdict(row) for row in view.history]).astype("string") if view.history else pd.DataFrame()
    if not history.empty:
        st.dataframe(history, hide_index=True, use_container_width=True)
    else:
        st.info("No recent canonical observations are available.")

    with st.expander("7. What happened from signal detection to shadow persistence?"):
        st.markdown("1. Legacy Red Bar V2 completed its authoritative evaluation.\n2. The newest admission event was copied into an immutable compact snapshot.\n3. The canonical state machine interpreted the same event-time evidence.\n4. Legacy and canonical outcomes were compared.\n5. The canonical resolution was stored as observational evidence.\n6. No order, position or exit was changed by this process.")
        st.caption(f"Selected observation: {persistence.resolution_id}; admission {section_2.admission_outcome}; parity {parity.overall}.")

    _render_execution_boundaries(settings, section_3.bundle_id if section_3.bundle_available else None)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    """Dedicated Red Bar V2 validation and canonical shadow observability workspace."""
    _render_shadow_observability(settings, instrument_key)
    st.divider()
    st.subheader("Red Bar V2 Validation")
    st.caption("Dedicated research workspace for the NEXT_RED_CANDLE RSI/VWAP strategy. Historical validation and promotion evidence are observation-only and cannot place paper or live orders.")
    mode_col, source_col, exit_col = st.columns(3)
    mode_col.metric("Strategy mode", "RESEARCH / SHADOW")
    source_col.metric("Replay source", "Underlying 1-minute OHLCV")
    exit_col.metric("Exit authority", "Legacy exit path unchanged")
    with st.expander("How to use this workspace", expanded=False):
        st.markdown("1. Confirm cached one-minute historical dates are available in **Research Lab → Historical Data**.\n2. Choose the validation end date below.\n3. Run the 10-day or 20-day Red Bar V2 validation.\n4. Review ready/blocked dates and candidate counts.\n5. Refresh promotion evidence after validation completes.")
    _render_window_panel(layout=layout, database=database, token=token, instrument_key=instrument_key)
    render_red_bar_v2_promotion_panel(st, settings)
