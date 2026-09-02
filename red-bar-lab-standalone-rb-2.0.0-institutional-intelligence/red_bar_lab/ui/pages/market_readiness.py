from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.ui._shared import *
from red_bar_lab.ui.live_monitor_diagnostics import (
    build_live_monitor_diagnostic_rows,
    read_live_reference_worker_status,
)
from red_bar_lab.ui.market_trend_research_panel import (
    render_market_trend_research_panel,
)
from red_bar_lab.ui.market_direction_summary import (
    render_market_direction_summary,
)
from red_bar_lab.ui.market_direction_validation_panel import (
    render_market_direction_validation_panel,
)


# Intentional hours-gate holds: the monitor is healthy (status stays
# RUNNING, no circuit breaker trips) but new entries are being held, so
# the banner must not claim there is "no active entry suspension".
_ENTRY_GATE_MESSAGES = {
    "OUTSIDE_AUTOMATIC_ENTRY_HOURS": (
        "The paper monitor is running, but new entries are on hold — "
        "outside automatic entry hours (Mon–Fri, 09:15–15:25 IST). "
        "Existing-position management remains active."
    ),
    "MARKET_CLOSED": (
        "The paper monitor is running, but new entries are on hold — "
        "the market is closed. Entries resume during trading hours."
    ),
}


def _entry_gate_message(status) -> str | None:
    decision = str(status.get("last_decision") or "")
    reason = str(status.get("last_reason") or "").upper()
    for key, message in _ENTRY_GATE_MESSAGES.items():
        if decision == key or key in reason:
            return message
    return None


def _format_age(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{seconds:.0f}s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.0f}m"
    return f"{minutes / 60.0:.1f}h"


def _decision_age_caption(database) -> str | None:
    """Caption showing when the newest diagnostic decision was recorded."""
    try:
        rows = database.read_paper_signal_diagnostics(limit=1)
    except Exception:
        return None
    if not rows:
        return None
    raw = rows[0].get("timestamp")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    age_seconds = (datetime.now(ZoneInfo("Asia/Kolkata")) - stamp).total_seconds()
    return (
        f"Decision recorded {str(raw)} ({_format_age(age_seconds)} ago) — "
        "the reason above reflects that moment, not necessarily the "
        "current cycle."
    )


def _render_monitor_status(database) -> None:
    st.markdown("### Paper monitor safety state")
    try:
        status = database.read_paper_monitor_status("PAPER-MONITOR") or {}
    except TypeError:
        status = database.read_paper_monitor_status() or {}
    except Exception:
        status = {}
    if not status:
        st.info("No persisted paper-monitor status is available.")
        return
    columns = st.columns(4)
    columns[0].metric("Monitor", status.get("status") or "UNKNOWN")
    columns[1].metric("Runtime state", status.get("current_state") or "UNKNOWN")
    columns[2].metric("Decision", status.get("last_decision") or "UNKNOWN")
    columns[3].metric("Heartbeat", status.get("heartbeat_at") or "—")
    if status.get("current_state") == "POSITION_MANAGEMENT_ONLY":
        st.error(
            "New paper entries are suspended. Existing-position management and "
            "confirmed reversal exits remain active."
        )
    elif status.get("status") == "DEGRADED":
        st.warning("The paper monitor is degraded and entry safety controls are active.")
    elif (gate_message := _entry_gate_message(status)) is not None:
        st.info(gate_message)
    else:
        st.success("The paper monitor is running without an active entry suspension.")
    if status.get("last_reason"):
        st.caption(f"Reason: {status['last_reason']}")
    age_caption = _decision_age_caption(database)
    if age_caption:
        st.caption(age_caption)
    if status.get("last_error"):
        st.caption(f"Last error: {status['last_error']}")


def _render_live_monitor_diagnostics(settings) -> None:
    """Surface the live reference worker's per-cycle diagnostics.

    When the worker runs and finds no signal candidates, the only
    observable evidence is a 0-attempts heartbeat. This panel reads the
    worker's status JSON and shows, per reference level, the current
    spot price vs. the level's source range, the price-relative status
    (PRICE_INSIDE_RANGE / PRICE_ABOVE_LEVEL / PRICE_BELOW_LEVEL), and a
    human-readable explanation of why no cross has fired.
    """
    status = read_live_reference_worker_status(settings)
    if not status:
        st.caption(
            "Live reference worker status not available yet. The worker "
            "writes one JSON file per cycle; the file appears next to the "
            "platform database after the first refresh."
        )
        return

    st.markdown("### Live reference monitor — why no signal this cycle")
    summary_rows, level_rows = build_live_monitor_diagnostic_rows(status)
    st.dataframe(
        _arrow_safe_rows(summary_rows),
        width="stretch",
        hide_index=True,
    )

    if not level_rows:
        st.caption(
            "No level diagnostics were captured in the last cycle. The "
            "worker reports a per-level breakdown only when spot price is "
            "available and at least one reference level is built."
        )
        return

    attempts = status.get("attempts") or 0
    active = status.get("active_attempts") or 0
    awaiting = status.get("awaiting_attempts") or 0
    if attempts == 0 and active == 0 and awaiting == 0:
        st.info(
            "No new signal candidates this cycle. The table below shows, "
            "for each reference level, where spot price sits relative to "
            "the level and the action required to trigger a cross."
        )
    else:
        st.caption(
            "Signal candidates are in flight. The table below still shows "
            "the price-vs-level snapshot for context."
        )
    st.dataframe(
        _arrow_safe_rows(level_rows),
        width="stretch",
        hide_index=True,
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
    st.subheader("Trade Evidence & Market Readiness")
    _render_monitor_status(database)
    _render_live_monitor_diagnostics(settings)

    render_market_direction_summary(
        settings.database_path,
        underlying=underlying_name,
    )

    research_tab, direction_validation_tab = st.tabs(
        [
            "Market Trend Research",
            "Market Direction Validation",
        ]
    )

    with research_tab:
        render_market_trend_research_panel(
            settings.database_path,
            underlying=underlying_name,
        )

    with direction_validation_tab:
        render_market_direction_validation_panel(
            settings.database_path,
            underlying=underlying_name,
        )
