from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository
from red_bar_lab.ui._shared import _arrow_safe_rows

COLUMNS = (
    "Strike",
    "Position",
    "CE current OI",
    "CE previous OI",
    "CE ΔOI",
    "CE ΔOI%",
    "PE current OI",
    "PE previous OI",
    "PE ΔOI",
    "PE ΔOI%",
)


def _indian(value: object) -> str:
    if value is None:
        return "Not available"
    number = int(round(float(value)))
    sign = "−" if number < 0 else ""
    digits = str(abs(number))
    if len(digits) <= 3:
        return sign + digits
    last = digits[-3:]
    lead = digits[:-3]
    groups: list[str] = []
    while lead:
        groups.append(lead[-2:])
        lead = lead[:-2]
    return sign + ",".join(reversed(groups)) + "," + last


def _signed(value: object) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    prefix = "+" if number > 0 else "−" if number < 0 else ""
    return prefix + _indian(abs(number))


def _percent(value: object) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    prefix = "+" if number > 0 else "−" if number < 0 else ""
    return f"{prefix}{abs(number):.2f}%"


def _number(value: object, digits: int = 3) -> str:
    return "Not available" if value is None else f"{float(value):.{digits}f}"


def _bias(value: object) -> str:
    return {
        "BEARISH": "Bearish PCR evidence",
        "NEUTRAL": "Neutral PCR evidence",
        "BULLISH": "Bullish PCR evidence",
        "STRONGLY_BULLISH": "Strongly bullish PCR evidence",
        "UNAVAILABLE": "PCR evidence not available",
    }.get(str(value), "PCR evidence not available")


def _table_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in panel.get("rows") or []:
        rows.append({
            "Strike": str(row.get("strike", "Not available")),
            "Position": str(row.get("position", "Not available")),
            "CE current OI": _indian(row.get("ce_current_oi")),
            "CE previous OI": _indian(row.get("ce_baseline_oi")),
            "CE ΔOI": _signed(row.get("ce_change")),
            "CE ΔOI%": _percent(row.get("ce_change_pct")),
            "PE current OI": _indian(row.get("pe_current_oi")),
            "PE previous OI": _indian(row.get("pe_baseline_oi")),
            "PE ΔOI": _signed(row.get("pe_change")),
            "PE ΔOI%": _percent(row.get("pe_change_pct")),
        })
    return rows


def _range(panel: dict[str, Any]) -> str:
    strikes = [
        float(row["strike"])
        for row in panel.get("rows") or []
        if isinstance(row.get("strike"), (int, float))
    ]
    return "Not available" if not strikes else f"{min(strikes):.0f}–{max(strikes):.0f}"


def _footer(panel: dict[str, Any]) -> None:
    rows = panel.get("rows") or []
    total = next((row for row in rows if row.get("position") == "TOTAL"), {})
    aggregate = panel.get("aggregate") or {}
    st.write(
        f"Overall CE OI change: {_signed(total.get('ce_change'))} "
        f"({_percent(total.get('ce_change_pct'))})"
    )
    st.write(
        f"Overall PE OI change: {_signed(total.get('pe_change'))} "
        f"({_percent(total.get('pe_change_pct'))})"
    )
    st.write(
        "PCR calculation: Total current PE OI ÷ Total current CE OI = "
        f"{_number(aggregate.get('pcr'))}"
    )
    st.write(f"PCR directional evidence: {_bias(aggregate.get('classification'))}")
    st.write(f"Data status: {panel.get('data_status') or 'Not available'}")


def _render_morning(projection: dict[str, Any]) -> None:
    st.markdown("## Morning Fixed-Level PCR")
    panel = projection.get("morning_panel")
    reference = projection.get("morning_reference") or {}
    baseline = projection.get("opening_oi_baseline") or {}
    quality = projection.get("quality") or {}
    if not panel:
        st.info(
            "Morning research is waiting for the reference level or the complete opening OI baseline."
        )
        st.write(f"Reference-level status: {reference.get('status') or 'Not available'}")
        st.write(f"OI-baseline status: {baseline.get('status') or 'Not available'}")
        return
    aggregate = panel.get("aggregate") or {}
    summary = [
        {"Field": "Reference-level status", "Value": reference.get("status") or "Not available"},
        {"Field": "NIFTY reference level", "Value": _number(reference.get("reference_spot"), 2)},
        {"Field": "Reference timestamp", "Value": reference.get("reference_timestamp") or "Not available"},
        {"Field": "Fixed ATM", "Value": _number(reference.get("fixed_atm"), 0)},
        {"Field": "Actual expiry", "Value": panel.get("expiry") or "Not available"},
        {"Field": "Sessions to expiry", "Value": str(panel.get("sessions_to_expiry", "Not available"))},
        {"Field": "Window", "Value": f"ATM ±{panel.get('window_steps', 'Not available')}"},
        {"Field": "Fixed strike range", "Value": _range(panel)},
        {"Field": "Expected/observed contracts", "Value": f"{panel.get('expected_contract_count', 0)}/{panel.get('observed_contract_count', 0)}"},
        {"Field": "OI-baseline status", "Value": baseline.get("status") or "Not available"},
        {"Field": "OI-baseline timestamp", "Value": baseline.get("baseline_timestamp") or "Not available"},
        {"Field": "Current source timestamp", "Value": panel.get("source_timestamp") or "Not available"},
        {"Field": "Source age", "Value": f"{_number(quality.get('source_age_seconds'), 1)} seconds"},
        {"Field": "PCR", "Value": _number(aggregate.get("pcr"))},
        {"Field": "PCR directional evidence", "Value": _bias(aggregate.get("classification"))},
    ]
    st.dataframe(_arrow_safe_rows(summary), width="stretch", hide_index=True)
    st.dataframe(_arrow_safe_rows(_table_rows(panel)), width="stretch", hide_index=True)
    _footer(panel)


def _render_current(projection: dict[str, Any]) -> None:
    st.markdown("## Current/Overall PCR")
    panel = projection.get("current_panel") or {}
    aggregate = panel.get("aggregate") or {}
    quality = projection.get("quality") or {}
    summary = [
        {"Field": "Current NIFTY level", "Value": _number(panel.get("spot"), 2)},
        {"Field": "Current ATM", "Value": _number(panel.get("atm"), 0)},
        {"Field": "Actual expiry", "Value": panel.get("expiry") or "Not available"},
        {"Field": "Sessions to expiry", "Value": str(panel.get("sessions_to_expiry", "Not available"))},
        {"Field": "Window", "Value": f"ATM ±{panel.get('window_steps', 'Not available')}"},
        {"Field": "Selected strike range", "Value": _range(panel)},
        {"Field": "Expected/observed contracts", "Value": f"{panel.get('expected_contract_count', 0)}/{panel.get('observed_contract_count', 0)}"},
        {"Field": "Current snapshot timestamp", "Value": panel.get("source_timestamp") or "Not available"},
        {"Field": "Previous comparable snapshot timestamp", "Value": panel.get("previous_timestamp") or "Not available"},
        {"Field": "Source age", "Value": f"{_number(quality.get('source_age_seconds'), 1)} seconds"},
        {"Field": "PCR", "Value": _number(aggregate.get("pcr"))},
        {"Field": "Previous PCR", "Value": _number(aggregate.get("previous_pcr"))},
        {"Field": "PCR change", "Value": _number(aggregate.get("absolute_change"))},
        {"Field": "PCR change percentage", "Value": _percent(aggregate.get("percentage_change"))},
        {"Field": "PCR slope", "Value": _number(aggregate.get("slope_per_minute"), 5)},
        {"Field": "Persistence", "Value": aggregate.get("persistence_state") or "Not available"},
        {"Field": "PCR directional evidence", "Value": _bias(aggregate.get("classification"))},
    ]
    st.dataframe(_arrow_safe_rows(summary), width="stretch", hide_index=True)
    st.dataframe(_arrow_safe_rows(_table_rows(panel)), width="stretch", hide_index=True)
    _footer(panel)


def render_market_trend_research_panel(database_path: str | Path, *, underlying: str) -> None:
    st.error("OBSERVATIONAL ONLY")
    st.write("Final market direction: NOT YET CALCULATED")
    st.write("Signal generated: NO")
    st.write("Canonical bundle created: NO")
    st.write("Opportunity queued: NO")
    st.write("Paper trade created: NO")
    repository = MarketTrendResearchRepository(database_path)
    projection = repository.latest_projection(underlying=underlying)
    health = repository.latest_runtime_health()
    if not projection:
        st.info("No persisted Market Trend Research projection is available.")
        return
    st.caption(
        f"Runtime mode: {projection.get('runtime_mode', 'ONE_SHOT')} · "
        f"Automatic refresh: {projection.get('automatic_refresh', 'NOT_CONNECTED')} · "
        f"Calendar source: {projection.get('calendar_source', 'Not available')}"
    )
    if health:
        st.caption(
            f"Heartbeat: {health.get('heartbeat_at', 'Not available')} · "
            f"Last success: {health.get('last_success_at', 'Not available')} · "
            f"Consecutive failures: {health.get('consecutive_failures', 0)}"
        )
    _render_morning(projection)
    _render_current(projection)
    with st.expander("Diagnostics", expanded=False):
        st.write({
            "quality": projection.get("quality"),
            "latency": projection.get("latency"),
            "lifecycle_state": projection.get("lifecycle_state"),
            "agreement_state": projection.get("agreement_state"),
        })
