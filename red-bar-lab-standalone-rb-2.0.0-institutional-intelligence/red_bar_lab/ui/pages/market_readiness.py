from __future__ import annotations

from red_bar_lab.ui._shared import *
from red_bar_lab.services.global_readiness_store import read_global_readiness_snapshots
from red_bar_lab.services.market_evidence_bundle_store import (
    read_latest_market_evidence_bundle,
)
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
    summarize_option_participation,
)
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


def _display_number(value, digits=3):
    return "—" if value is None else f"{float(value):.{digits}f}"


def _display_score(value):
    return "—" if value is None else f"{float(value):.1f}"


def _participation_table_rows(rows):
    result = []
    for item in rows:
        result.append(
            {
                "Side": item.get("option_type") or "—",
                "Strike": _display_number(item.get("strike"), 0),
                "Current premium": _display_number(item.get("current_price"), 2),
                "VWAP": _display_number(item.get("vwap"), 2),
                "Volume": _display_number(item.get("volume"), 0),
                "OI": _display_number(item.get("oi"), 0),
                "Change in OI": _display_number(item.get("oi_change"), 0),
                "Delta": _display_number(item.get("delta")),
                "RSI": _display_number(item.get("option_rsi"), 1),
                "IV (required; 1–150)": _display_number(item.get("iv"), 2),
                "State": item.get("participation_state") or "INSUFFICIENT",
                "Eligibility": item.get("contract_eligibility") or "—",
            }
        )
    return result


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


def _render_authoritative_page(settings, underlying_name, bundle, readiness_rows) -> None:
    st.caption(
        "Read-only consumer of the single authoritative Market at a Glance "
        "evidence bundle. This tab does not recalculate an independent market "
        "direction."
    )

    if not bundle:
        st.warning(
            "No authoritative market evidence bundle is available yet. "
            "Run the paper monitor/collector."
        )
        return

    st.markdown("### Authoritative market conclusion")
    columns = st.columns(6)
    columns[0].metric("Observed direction", bundle.get("observed_direction") or "UNAVAILABLE")
    columns[1].metric("Direction state", bundle.get("direction_state") or "UNAVAILABLE")
    columns[2].metric("Evidence readiness", bundle.get("evidence_readiness") or "UNAVAILABLE")
    columns[3].metric(
        "Derivatives confirmed",
        "YES" if bundle.get("derivatives_confirmation_passed") else "NO",
    )
    columns[4].metric("Trade eligibility", bundle.get("trade_eligibility") or "BLOCKED")
    columns[5].metric("Trade bias", bundle.get("trade_bias") or "WAIT")

    if bundle.get("trade_eligibility") == "ELIGIBLE":
        st.success(bundle.get("confirmation") or "Authoritative evidence is eligible.")
    else:
        st.warning(bundle.get("confirmation") or "Authoritative evidence remains blocked.")

    if bundle.get("primary_blocker"):
        st.error(f"Primary blocker: {bundle['primary_blocker']}")
    if bundle.get("blocking_reasons"):
        st.caption("Blocking reasons: " + ", ".join(bundle["blocking_reasons"]))
    if bundle.get("caution_reasons"):
        st.caption("Cautions: " + ", ".join(bundle["caution_reasons"]))

    st.markdown("### Authoritative evidence diagnostics")
    st.dataframe(
        _arrow_safe_rows(bundle.get("checklist") or []),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### Freshness and alignment")
    st.dataframe(
        _arrow_safe_rows(bundle.get("freshness_rows") or []),
        width="stretch",
        hide_index=True,
    )

    participation_rows = read_latest_option_participation(
        settings.database_path,
        underlying_name=underlying_name,
    )
    participation = summarize_option_participation(participation_rows)
    st.markdown("### ATM ±4 option participation")
    st.caption(
        "Contract-quality rule: premium, volume, OI, bid, ask and IV must be "
        "available; bid/ask spread must be at most 3%; IV must be between 1 and 150."
    )
    if participation_rows:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Spot", _display_number(participation.get("spot_price"), 2))
        p2.metric("ATM", _display_number(participation.get("atm_strike"), 0))
        p3.metric("CE pressure", _display_score(participation.get("ce_score")))
        p4.metric("PE pressure", _display_score(participation.get("pe_score")))
        st.dataframe(
            _arrow_safe_rows(_participation_table_rows(participation_rows)),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No ATM ±4 participation rows are available.")

    st.markdown("### Persisted evidence bundle")
    st.json(bundle)
    st.caption(
        f"Bundle: {bundle.get('bundle_id') or '—'} · "
        f"Safe evidence time: {bundle.get('safe_evidence_time') or '—'} · "
        "Authority: OBSERVATIONAL_ONLY"
    )

    with st.expander("Legacy global readiness diagnostics", expanded=False):
        if readiness_rows:
            st.dataframe(
                _arrow_safe_rows(readiness_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No legacy global readiness snapshots are available.")


def render_page(
    settings,
    layout,
    database,
    token,
    underlying_name,
    instrument_key,
    interval,
) -> None:
    # Protected workspace contracts delegated to the authoritative renderer:
    # Authoritative market conclusion
    # Authoritative evidence diagnostics
    # Persisted evidence bundle
    # Legacy global readiness diagnostics
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
