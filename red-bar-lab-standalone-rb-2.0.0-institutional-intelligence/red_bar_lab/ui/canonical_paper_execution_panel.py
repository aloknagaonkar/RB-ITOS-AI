from __future__ import annotations

import pandas as pd

from red_bar_lab.services.red_bar_v2_canonical.paper_execution_observability import (
    SQLiteCanonicalPaperExecutionObservabilityRepository,
)


def render_canonical_paper_execution_panel(st, settings, bundle_id: str | None) -> None:
    st.markdown("### 10. Paper Execution")
    st.warning(
        "PAPER ONLY — canonical execution has no live-broker authority. "
        "Legacy paper execution remains available and live execution is unchanged."
    )
    mode = str(settings.red_bar_v2_canonical_paper_execution_mode)
    enabled = bool(settings.red_bar_v2_canonical_paper_execution_enabled)
    st.caption(f"Feature: {'ENABLED' if enabled else 'DISABLED'} | Mode: {mode} | Authority: PAPER ONLY")
    if not enabled:
        st.info("PAPER_EXECUTION_DISABLED — no canonical reservation or paper command is created.")
        return
    if mode != "PAPER_CANARY":
        st.info("OBSERVE_ONLY — readiness may be inspected, but no reservation or paper command is mutated.")
        return
    if bundle_id is None:
        st.info("NO_CANONICAL_EXECUTION — no selected canonical bundle is available.")
        return
    result = SQLiteCanonicalPaperExecutionObservabilityRepository(
        settings.database_path
    ).latest_for_bundle(bundle_id=bundle_id)
    if result.status == "NO_CANONICAL_EXECUTION":
        st.info("NO_CANONICAL_EXECUTION — no canonical paper command exists for this bundle.")
        return
    if result.status == "EXECUTION_DATA_CORRUPT":
        st.error("EXECUTION_DATA_CORRUPT — persisted command or lifecycle evidence failed integrity validation. No execution evidence is trusted.")
        return
    if result.status == "EXECUTION_DATABASE_UNAVAILABLE":
        st.info("EXECUTION_DATABASE_UNAVAILABLE — canonical paper execution storage is unavailable. Legacy execution is unaffected.")
        return
    evidence = result.evidence
    if evidence is None:
        st.error("Canonical paper execution projection is incomplete; no partial evidence is rendered.")
        return
    command = evidence.command
    rows = [
        ("Observability status", result.status),
        ("Handled authority", "CANONICAL PAPER"),
        ("Bundle ID", command.bundle_id),
        ("Reservation ID", command.reservation_id),
        ("Reservation owner", command.reservation_owner),
        ("Reservation expiry", command.reservation_expiry.isoformat()),
        ("Command ID", command.command_id),
        ("Execution ID", command.execution_id),
        ("Selected contract", command.contract.tradingsymbol),
        ("Contract instrument", command.contract.instrument_key),
        ("Option side", command.contract.option_side.value),
        ("Quantity", str(command.quantity)),
        ("Paper order type", command.order_type),
        ("Execution state", evidence.state.value),
        ("Paper order ID", str(evidence.paper_order_id or "—")),
        ("Reason code", evidence.reason_code),
        ("Signal timestamp", command.signal_timestamp.isoformat()),
        ("Command created", command.created_at.isoformat()),
    ]
    st.dataframe(
        pd.DataFrame(rows, columns=["Field", "Verified value"], dtype="string"),
        hide_index=True,
        use_container_width=True,
    )
    event_rows = [
        {
            "Event type": event_type.value,
            "Timestamp": timestamp.isoformat(),
            "Reason code": reason,
            "Paper order ID": str(order_id or "—"),
        }
        for event_type, timestamp, reason, order_id in evidence.events
    ]
    if event_rows:
        st.dataframe(
            pd.DataFrame(event_rows, dtype="string"),
            hide_index=True,
            use_container_width=True,
        )
    if result.status == "RECOVERY_REQUIRED":
        st.warning("RECOVERY_REQUIRED — submission outcome is not proven. The UI cannot retry or release the reservation.")
