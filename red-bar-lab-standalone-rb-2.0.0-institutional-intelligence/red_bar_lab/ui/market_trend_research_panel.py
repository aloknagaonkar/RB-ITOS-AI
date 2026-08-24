from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

import streamlit as st

from red_bar_lab.services.market_trend_research.policy import (
    MarketTrendResearchPolicy,
)
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)
from red_bar_lab.ui._shared import _arrow_safe_rows

MORNING_COLUMNS = (
    "Strike",
    "Position",
    "CE current OI",
    "CE opening OI",
    "CE since-open ΔOI",
    "CE since-open ΔOI%",
    "PE current OI",
    "PE opening OI",
    "PE since-open ΔOI",
    "PE since-open ΔOI%",
)
CURRENT_COLUMNS = (
    "Strike",
    "Position",
    "CE current OI",
    "CE previous-day OI",
    "CE day ΔOI",
    "CE day ΔOI%",
    "PE current OI",
    "PE previous-day OI",
    "PE day ΔOI",
    "PE day ΔOI%",
)


def _freshness_threshold_seconds() -> float:
    default = MarketTrendResearchPolicy().maximum_source_age_seconds
    raw = os.getenv("MARKET_TREND_RESEARCH_MAX_SOURCE_AGE_SECONDS")
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _source_age_seconds(
    source_timestamp: object,
    *,
    now: datetime | None = None,
    negative_tolerance_seconds: float = 1.0,
) -> float | None:
    if not isinstance(source_timestamp, str) or not source_timestamp.strip():
        return None
    text = source_timestamp.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        source = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if source.tzinfo is None or source.utcoffset() is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    age = (current.astimezone(timezone.utc) - source.astimezone(timezone.utc)).total_seconds()
    if age < -negative_tolerance_seconds:
        return None
    return max(0.0, age)


def _source_age_text(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.1f} seconds"


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
    if number == 0:
        return "0"
    return ("+" if number > 0 else "−") + _indian(abs(number))


def _percent(value: object) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if number == 0:
        return "0.00%"
    return ("+" if number > 0 else "−") + f"{abs(number):.2f}%"


def _number(value: object, digits: int = 3) -> str:
    return "Not available" if value is None else f"{float(value):.{digits}f}"


def _bias(value: object, *, stale: bool = False) -> str:
    label = {
        "BEARISH": "Bearish PCR evidence",
        "NEUTRAL": "Neutral PCR evidence",
        "BULLISH": "Bullish PCR evidence",
        "STRONGLY_BULLISH": "Strongly bullish PCR evidence",
        "UNAVAILABLE": "PCR evidence not available",
    }.get(str(value), "PCR evidence not available")
    return f"{label} — stale" if stale else label


def _position(value: object) -> str:
    return {
        "BELOW_ATM": "Below ATM",
        "BELOW ATM": "Below ATM",
        "ATM": "ATM",
        "ABOVE_ATM": "Above ATM",
        "ABOVE ATM": "Above ATM",
        "TOTAL": "Overall total",
    }.get(str(value), "Not available")


def _field(row: dict[str, Any], name: str) -> object:
    return row.get(name)


def _morning_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in panel.get("rows") or []:
        output.append(
            {
                "Strike": str(row.get("strike", "Not available")),
                "Position": _position(row.get("position")),
                "CE current OI": _indian(_field(row, "ce_current_oi")),
                "CE opening OI": _indian(_field(row, "ce_opening_oi")),
                "CE since-open ΔOI": _signed(_field(row, "ce_opening_change")),
                "CE since-open ΔOI%": _percent(_field(row, "ce_opening_change_pct")),
                "PE current OI": _indian(_field(row, "pe_current_oi")),
                "PE opening OI": _indian(_field(row, "pe_opening_oi")),
                "PE since-open ΔOI": _signed(_field(row, "pe_opening_change")),
                "PE since-open ΔOI%": _percent(_field(row, "pe_opening_change_pct")),
            }
        )
    return output


def _current_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in panel.get("rows") or []:
        output.append(
            {
                "Strike": str(row.get("strike", "Not available")),
                "Position": _position(row.get("position")),
                "CE current OI": _indian(_field(row, "ce_current_oi")),
                "CE previous-day OI": _indian(_field(row, "ce_previous_day_oi")),
                "CE day ΔOI": _signed(_field(row, "ce_previous_day_change")),
                "CE day ΔOI%": _percent(_field(row, "ce_previous_day_change_pct")),
                "PE current OI": _indian(_field(row, "pe_current_oi")),
                "PE previous-day OI": _indian(_field(row, "pe_previous_day_oi")),
                "PE day ΔOI": _signed(_field(row, "pe_previous_day_change")),
                "PE day ΔOI%": _percent(_field(row, "pe_previous_day_change_pct")),
            }
        )
    return output


def _refresh_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in panel.get("rows") or []:
        output.append(
            {
                "Strike": str(row.get("strike", "Not available")),
                "Position": _position(row.get("position")),
                "CE previous refresh OI": _indian(_field(row, "ce_previous_refresh_oi")),
                "CE refresh ΔOI": _signed(_field(row, "ce_previous_refresh_change")),
                "CE refresh ΔOI%": _percent(_field(row, "ce_previous_refresh_change_pct")),
                "PE previous refresh OI": _indian(_field(row, "pe_previous_refresh_oi")),
                "PE refresh ΔOI": _signed(_field(row, "pe_previous_refresh_change")),
                "PE refresh ΔOI%": _percent(_field(row, "pe_previous_refresh_change_pct")),
            }
        )
    return output


def _range(panel: dict[str, Any]) -> str:
    strikes = [
        float(row["strike"])
        for row in panel.get("rows") or []
        if isinstance(row.get("strike"), (int, float))
    ]
    return "Not available" if not strikes else f"{min(strikes):.0f}–{max(strikes):.0f}"


def _total(panel: dict[str, Any]) -> dict[str, Any]:
    return next(
        (row for row in panel.get("rows") or [] if row.get("position") == "TOTAL"),
        {},
    )


def _render_morning(
    projection: dict[str, Any],
    *,
    stale: bool,
    live_source_age: float | None,
) -> None:
    st.markdown("## Morning Fixed-Level PCR")
    panel = projection.get("morning_panel")
    reference = projection.get("morning_reference") or {}
    baseline = projection.get("opening_oi_baseline") or {}
    if not panel:
        lifecycle = projection.get("lifecycle_state") or "WAITING_FOR_REFERENCE"
        message = (
            "Waiting for the first valid NIFTY reference level."
            if lifecycle == "WAITING_FOR_REFERENCE"
            else "Waiting for the first complete fresh opening option-OI baseline."
        )
        st.info(message)
        st.write(f"Reference-level status: {reference.get('status') or 'Not available'}")
        st.write(f"OI-baseline status: {baseline.get('status') or 'Not available'}")
        return

    aggregate = panel.get("aggregate") or {}
    summary = [
        {"Field": "Reference-level status", "Value": reference.get("status") or "Not available"},
        {"Field": "Reference NIFTY level", "Value": _number(reference.get("reference_spot"), 2)},
        {"Field": "Reference timestamp", "Value": reference.get("reference_timestamp") or "Not available"},
        {"Field": "Fixed ATM", "Value": _number(reference.get("fixed_atm"), 0)},
        {"Field": "Actual expiry", "Value": panel.get("expiry") or "Not available"},
        {"Field": "Sessions to expiry", "Value": str(panel.get("sessions_to_expiry", "Not available"))},
        {"Field": "Window", "Value": f"ATM ±{panel.get('window_steps', 'Not available')}"},
        {"Field": "Fixed strike range", "Value": _range(panel)},
        {
            "Field": "Expected/observed contracts",
            "Value": f"{panel.get('expected_contract_count', 0)}/{panel.get('observed_contract_count', 0)}",
        },
        {"Field": "Opening OI baseline timestamp", "Value": baseline.get("baseline_timestamp") or "Not available"},
        {"Field": "Current snapshot timestamp", "Value": panel.get("source_timestamp") or "Not available"},
        {"Field": "Source age", "Value": _source_age_text(live_source_age)},
        {"Field": "PCR", "Value": _number(aggregate.get("pcr"))},
        {"Field": "PCR directional evidence", "Value": _bias(aggregate.get("classification"), stale=stale)},
    ]
    st.dataframe(_arrow_safe_rows(summary), width="stretch", hide_index=True)
    st.dataframe(_arrow_safe_rows(_morning_rows(panel)), width="stretch", hide_index=True)
    total = _total(panel)
    st.write(
        "Overall CE change since open: "
        f"{_signed(total.get('ce_opening_change'))} "
        f"({_percent(total.get('ce_opening_change_pct'))})"
    )
    st.write(
        "Overall PE change since open: "
        f"{_signed(total.get('pe_opening_change'))} "
        f"({_percent(total.get('pe_opening_change_pct'))})"
    )
    st.write(
        "Morning fixed-level PCR: Total current PE OI ÷ "
        f"Total current CE OI = {_number(aggregate.get('pcr'))}"
    )
    st.write(
        "PCR directional evidence: "
        f"{_bias(aggregate.get('classification'), stale=stale)}"
    )


def _render_refresh_diagnostics(panel: dict[str, Any]) -> None:
    aggregate = panel.get("aggregate") or {}
    current_timestamp = panel.get("source_timestamp")
    previous_timestamp = panel.get("previous_timestamp")
    with st.expander("Short-term OI movement since previous refresh", expanded=False):
        st.caption(
            "This compares adjacent collector snapshots and may remain zero when "
            "the exchange-reported OI has not updated."
        )
        elapsed = "Not available"
        if current_timestamp and previous_timestamp:
            current = _parse_aware_timestamp(current_timestamp)
            previous = _parse_aware_timestamp(previous_timestamp)
            if current is not None and previous is not None:
                elapsed = str((current - previous).total_seconds())
        details = [
            {"Field": "Current snapshot timestamp", "Value": current_timestamp or "Not available"},
            {"Field": "Previous comparable snapshot timestamp", "Value": previous_timestamp or "Not available"},
            {"Field": "Elapsed seconds", "Value": elapsed},
            {"Field": "Current PCR", "Value": _number(aggregate.get("pcr"))},
            {"Field": "Previous PCR", "Value": _number(aggregate.get("previous_pcr"))},
            {"Field": "PCR change", "Value": _number(aggregate.get("absolute_change"))},
            {"Field": "PCR change percentage", "Value": _percent(aggregate.get("percentage_change"))},
            {"Field": "PCR slope", "Value": _number(aggregate.get("slope_per_minute"), 5)},
            {"Field": "Comparability", "Value": panel.get("data_status") or "Not available"},
        ]
        st.dataframe(_arrow_safe_rows(details), width="stretch", hide_index=True)
        st.dataframe(_arrow_safe_rows(_refresh_rows(panel)), width="stretch", hide_index=True)


def _parse_aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _render_current(
    projection: dict[str, Any],
    *,
    stale: bool,
    live_source_age: float | None,
) -> None:
    st.markdown("## Current/Overall PCR")
    panel = projection.get("current_panel") or {}
    aggregate = panel.get("aggregate") or {}
    summary = [
        {"Field": "Current NIFTY level", "Value": _number(panel.get("spot"), 2)},
        {"Field": "Current ATM", "Value": _number(panel.get("atm"), 0)},
        {"Field": "Actual expiry", "Value": panel.get("expiry") or "Not available"},
        {"Field": "Sessions to expiry", "Value": str(panel.get("sessions_to_expiry", "Not available"))},
        {"Field": "Current window", "Value": f"ATM ±{panel.get('window_steps', 'Not available')}"},
        {"Field": "Selected strike range", "Value": _range(panel)},
        {
            "Field": "Expected/observed contracts",
            "Value": f"{panel.get('expected_contract_count', 0)}/{panel.get('observed_contract_count', 0)}",
        },
        {"Field": "Source timestamp", "Value": panel.get("source_timestamp") or "Not available"},
        {"Field": "Source age", "Value": _source_age_text(live_source_age)},
        {"Field": "PCR", "Value": _number(aggregate.get("pcr"))},
        {"Field": "PCR directional evidence", "Value": _bias(aggregate.get("classification"), stale=stale)},
    ]
    st.dataframe(_arrow_safe_rows(summary), width="stretch", hide_index=True)
    st.dataframe(_arrow_safe_rows(_current_rows(panel)), width="stretch", hide_index=True)
    total = _total(panel)
    st.write(
        "Overall CE day change: "
        f"{_signed(total.get('ce_previous_day_change'))} "
        f"({_percent(total.get('ce_previous_day_change_pct'))})"
    )
    st.write(
        "Overall PE day change: "
        f"{_signed(total.get('pe_previous_day_change'))} "
        f"({_percent(total.get('pe_previous_day_change_pct'))})"
    )
    st.write(
        "Current/Overall PCR: Total current PE OI ÷ "
        f"Total current CE OI = {_number(aggregate.get('pcr'))}"
    )
    st.write(
        "PCR directional evidence: "
        f"{_bias(aggregate.get('classification'), stale=stale)}"
    )
    _render_refresh_diagnostics(panel)


def render_market_trend_research_panel(
    database_path: str | Path,
    *,
    underlying: str,
) -> None:
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

    quality = projection.get("quality") or {}
    live_source_age = _source_age_seconds(projection.get("source_timestamp"))
    threshold = _freshness_threshold_seconds()
    stale = (
        live_source_age is None
        or live_source_age > threshold
        or quality.get("state") == "STALE"
    )
    if stale:
        if live_source_age is None:
            st.warning(
                "STALE DATA — source age is not available. "
                "Values are shown for diagnosis only."
            )
        else:
            st.warning(
                "STALE DATA — last research snapshot is "
                f"{live_source_age:.1f} seconds old. "
                "Values are shown for diagnosis only."
            )

    runtime_mode = projection.get("runtime_mode", "ONE_SHOT")
    automatic_refresh = projection.get("automatic_refresh", "NOT_CONNECTED")
    st.caption(
        f"Runtime mode: {runtime_mode} · "
        f"Automatic refresh: {automatic_refresh} · "
        f"Calendar source: {projection.get('calendar_source', 'Not available')}"
    )
    if health:
        st.caption(
            f"Heartbeat: {health.get('heartbeat_at', 'Not available')} · "
            f"Last success: {health.get('last_success_at', 'Not available')} · "
            f"Consecutive failures: {health.get('consecutive_failures', 0)}"
        )

    _render_morning(
        projection,
        stale=stale,
        live_source_age=live_source_age,
    )
    _render_current(
        projection,
        stale=stale,
        live_source_age=live_source_age,
    )

    with st.expander("Internal diagnostics", expanded=False):
        st.write(
            {
                "quality": projection.get("quality"),
                "persisted_evaluation_source_age_seconds": quality.get(
                    "source_age_seconds"
                ),
                "live_source_age_seconds": live_source_age,
                "freshness_threshold_seconds": threshold,
                "latency": projection.get("latency"),
                "lifecycle_state": projection.get("lifecycle_state"),
                "agreement_state": projection.get("agreement_state"),
                "schema_version": projection.get("schema_version"),
                "legacy_projection": not any(
                    "ce_previous_day_oi" in row
                    for row in (projection.get("current_panel") or {}).get("rows", [])
                ),
            }
        )
