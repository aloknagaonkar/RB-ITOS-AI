from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar
from zoneinfo import ZoneInfo

import streamlit as st

from red_bar_lab.services.market_trend_research.models import PcrBias
from red_bar_lab.services.market_trend_research.policy import MarketTrendResearchPolicy
from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
)
from red_bar_lab.ui._shared import _arrow_safe_rows

IST = ZoneInfo("Asia/Kolkata")
F = TypeVar("F", bound=Callable[..., object])

MORNING_COLUMNS = (
    "Strike", "Position", "CE current OI", "CE opening OI",
    "CE since-open ΔOI", "CE since-open ΔOI%", "PE current OI",
    "PE opening OI", "PE since-open ΔOI", "PE since-open ΔOI%",
)
CURRENT_COLUMNS = (
    "Strike", "Position", "CE current OI", "CE previous-day OI",
    "CE OI change today", "CE OI change %", "PE current OI",
    "PE previous-day OI", "PE OI change today", "PE OI change %",
)


def _bounded_seconds(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if 2.0 <= value <= 60.0 else default


MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS = _bounded_seconds(
    "MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS", 5.0
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


def _parse_aware_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _format_ist_timestamp(value: object) -> str:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        return "Not available"
    local = parsed.astimezone(IST)
    hour = local.strftime("%I").lstrip("0") or "0"
    return f"{local:%d %b %Y}, {hour}:{local:%M:%S %p} IST"


def _source_age_seconds(
    source_timestamp: object,
    *,
    now: datetime | None = None,
    negative_tolerance_seconds: float = 1.0,
) -> float | None:
    source = _parse_aware_timestamp(source_timestamp)
    if source is None:
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


@dataclass(frozen=True, slots=True)
class RuntimeHealthView:
    state: str
    heartbeat_age_seconds: float | None
    heartbeat: str
    last_success: str
    last_failure: str
    consecutive_failures: int
    safe_reason: str | None


def _safe_reason(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if not text or len(text) > 64:
        return None
    return text if all(ch.isalnum() or ch in "_-" for ch in text) else None


def _runtime_health_state(
    health: Mapping[str, object] | None,
    *,
    now: datetime,
    expected_refresh_seconds: float,
) -> RuntimeHealthView:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    raw = health or {}
    heartbeat_age = _source_age_seconds(raw.get("heartbeat_at"), now=now)
    try:
        failures = max(0, int(raw.get("consecutive_failures", 0)))
    except (TypeError, ValueError):
        failures = 0
    running_limit = max(3.0 * expected_refresh_seconds, 15.0)
    degraded_limit = max(12.0 * expected_refresh_seconds, 60.0)
    if heartbeat_age is None or heartbeat_age > degraded_limit:
        state = "STOPPED"
    elif failures > 0 or heartbeat_age > running_limit:
        state = "DEGRADED"
    else:
        state = "RUNNING"
    return RuntimeHealthView(
        state=state,
        heartbeat_age_seconds=heartbeat_age,
        heartbeat=_format_ist_timestamp(raw.get("heartbeat_at")),
        last_success=_format_ist_timestamp(raw.get("last_success_at")),
        last_failure=_format_ist_timestamp(raw.get("last_failure_at")),
        consecutive_failures=failures,
        safe_reason=_safe_reason(raw.get("last_failure_reason")),
    )


def _fragment(run_every: str) -> Callable[[F], F]:
    fragment = getattr(st, "fragment", None)
    if callable(fragment):
        return fragment(run_every=run_every)
    return lambda function: function


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
        "BELOW_ATM": "Below ATM", "BELOW ATM": "Below ATM", "ATM": "ATM",
        "ABOVE_ATM": "Above ATM", "ABOVE ATM": "Above ATM",
        "TOTAL": "Overall total",
    }.get(str(value), "Not available")


def _field(row: dict[str, Any], name: str) -> object:
    return row.get(name)


def _morning_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    return [{
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
    } for row in panel.get("rows") or []]


def _current_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    return [{
        "Strike": str(row.get("strike", "Not available")),
        "Position": _position(row.get("position")),
        "CE current OI": _indian(_field(row, "ce_current_oi")),
        "CE previous-day OI": _indian(_field(row, "ce_previous_day_oi")),
        "CE OI change today": _signed(_field(row, "ce_previous_day_change")),
        "CE OI change %": _percent(_field(row, "ce_previous_day_change_pct")),
        "PE current OI": _indian(_field(row, "pe_current_oi")),
        "PE previous-day OI": _indian(_field(row, "pe_previous_day_oi")),
        "PE OI change today": _signed(_field(row, "pe_previous_day_change")),
        "PE OI change %": _percent(_field(row, "pe_previous_day_change_pct")),
    } for row in panel.get("rows") or []]


def _option_metric_rows(
    panel: Mapping[str, Any],
    option_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Correlate persisted option metrics to the exact PCR strike window."""

    selected_expiry = str(panel.get("expiry") or "")
    by_expiry_strike_side = {
        (
            str(row.get("expiry") or ""),
            float(row["strike"]),
            str(row.get("option_type") or "").upper(),
        ): row
        for row in option_rows
        if isinstance(row.get("strike"), (int, float))
        and str(row.get("option_type") or "").upper() in {"CE", "PE"}
    }
    result: list[dict[str, str]] = []
    for pcr_row in panel.get("rows") or []:
        strike = pcr_row.get("strike")
        if not isinstance(strike, (int, float)):
            continue
        ce = by_expiry_strike_side.get(
            (selected_expiry, float(strike), "CE"), {}
        )
        pe = by_expiry_strike_side.get(
            (selected_expiry, float(strike), "PE"), {}
        )
        result.append(
            {
                "Strike": f"{float(strike):.0f}",
                "CE current price": _number(ce.get("current_price"), 2),
                "CE Delta": _number(ce.get("delta"), 4),
                "CE VWAP": _number(ce.get("vwap"), 2),
                "CE IV": _number(ce.get("iv"), 2),
                "CE OI change %": _percent(ce.get("oi_change_pct")),
                "PE current price": _number(pe.get("current_price"), 2),
                "PE Delta": _number(pe.get("delta"), 4),
                "PE VWAP": _number(pe.get("vwap"), 2),
                "PE IV": _number(pe.get("iv"), 2),
                "PE OI change %": _percent(pe.get("oi_change_pct")),
            }
        )
    return result


def _option_metrics_source_time(
    panel: Mapping[str, Any],
    option_rows: list[dict[str, Any]],
) -> str:
    selected_expiry = str(panel.get("expiry") or "")
    selected_strikes = {
        float(row["strike"])
        for row in panel.get("rows") or []
        if isinstance(row.get("strike"), (int, float))
    }
    timestamps = {
        str(row.get("observed_at"))
        for row in option_rows
        if str(row.get("expiry") or "") == selected_expiry
        and isinstance(row.get("strike"), (int, float))
        and float(row["strike"]) in selected_strikes
        and str(row.get("option_type") or "").upper() in {"CE", "PE"}
        and row.get("observed_at")
    }
    return (
        _format_ist_timestamp(next(iter(timestamps)))
        if len(timestamps) == 1
        else "Not available"
    )


def _refresh_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    return [{
        "Strike": str(row.get("strike", "Not available")),
        "Position": _position(row.get("position")),
        "CE previous refresh OI": _indian(_field(row, "ce_previous_refresh_oi")),
        "CE refresh ΔOI": _signed(_field(row, "ce_previous_refresh_change")),
        "CE refresh ΔOI%": _percent(_field(row, "ce_previous_refresh_change_pct")),
        "PE previous refresh OI": _indian(_field(row, "pe_previous_refresh_oi")),
        "PE refresh ΔOI": _signed(_field(row, "pe_previous_refresh_change")),
        "PE refresh ΔOI%": _percent(_field(row, "pe_previous_refresh_change_pct")),
    } for row in panel.get("rows") or []]


def _range(panel: dict[str, Any]) -> str:
    strikes = [float(row["strike"]) for row in panel.get("rows") or []
               if isinstance(row.get("strike"), (int, float))]
    return "Not available" if not strikes else f"{min(strikes):.0f}–{max(strikes):.0f}"


def _total(panel: dict[str, Any]) -> dict[str, Any]:
    return next((row for row in panel.get("rows") or [] if row.get("position") == "TOTAL"), {})


def _direction_evidence(aggregate: Mapping[str, object]) -> dict[str, object]:
    persisted = aggregate.get("direction_evidence")
    if isinstance(persisted, dict):
        return persisted
    raw = aggregate.get("classification", "UNAVAILABLE")
    try:
        classification = PcrBias(str(raw))
    except ValueError:
        classification = PcrBias.UNAVAILABLE
    evidence = MarketTrendResearchPolicy().direction_evidence(
        aggregate.get("pcr") if isinstance(aggregate.get("pcr"), (int, float)) else None,
        classification=classification,
    )
    return asdict(evidence)


def _render_market_direction_research(projection: dict[str, Any], *, stale: bool) -> None:
    aggregate = (projection.get("current_panel") or {}).get("aggregate") or {}
    evidence = _direction_evidence(aggregate)
    direction = str(evidence.get("direction", "UNAVAILABLE"))
    displayed_direction = f"{direction} — STALE" if stale else direction
    st.markdown("### Market Direction Research")
    st.dataframe(_arrow_safe_rows([{
        "PCR market direction": displayed_direction,
        "Current PCR": _number(evidence.get("pcr")),
        "Final combined direction": "NOT YET CALCULATED",
    }]), width="stretch", hide_index=True)


def _render_morning(projection: dict[str, Any], *, stale: bool, live_source_age: float | None) -> None:
    st.markdown("## Morning Fixed-Level PCR")
    panel = projection.get("morning_panel")
    reference = projection.get("morning_reference") or {}
    baseline = projection.get("opening_oi_baseline") or {}
    if not panel:
        lifecycle = projection.get("lifecycle_state") or "WAITING_FOR_REFERENCE"
        st.info("Waiting for the first valid NIFTY reference level." if lifecycle == "WAITING_FOR_REFERENCE"
                else "Waiting for the first complete fresh opening option-OI baseline.")
        st.write(f"Reference-level status: {reference.get('status') or 'Not available'}")
        st.write(f"OI-baseline status: {baseline.get('status') or 'Not available'}")
        return
    aggregate = panel.get("aggregate") or {}
    summary = [
        {"Field": "Reference-level status", "Value": reference.get("status") or "Not available"},
        {"Field": "Reference NIFTY level", "Value": _number(reference.get("reference_spot"), 2)},
        {"Field": "Reference timestamp", "Value": _format_ist_timestamp(reference.get("reference_timestamp"))},
        {"Field": "Fixed ATM", "Value": _number(reference.get("fixed_atm"), 0)},
        {"Field": "Actual expiry", "Value": panel.get("expiry") or "Not available"},
        {"Field": "Sessions to expiry", "Value": str(panel.get("sessions_to_expiry", "Not available"))},
        {"Field": "Window", "Value": f"ATM ±{panel.get('window_steps', 'Not available')}"},
        {"Field": "Fixed strike range", "Value": _range(panel)},
        {"Field": "Expected/observed contracts", "Value": f"{panel.get('expected_contract_count', 0)}/{panel.get('observed_contract_count', 0)}"},
        {"Field": "Opening OI baseline timestamp", "Value": _format_ist_timestamp(baseline.get("baseline_timestamp"))},
        {"Field": "Current snapshot timestamp", "Value": _format_ist_timestamp(panel.get("source_timestamp"))},
        {"Field": "Source age", "Value": _source_age_text(live_source_age)},
        {"Field": "PCR", "Value": _number(aggregate.get("pcr"))},
        {"Field": "PCR directional evidence", "Value": _bias(aggregate.get("classification"), stale=stale)},
    ]
    st.dataframe(_arrow_safe_rows(_morning_rows(panel)), width="stretch", hide_index=True)
    with st.expander("Morning Fixed-Level PCR details", expanded=False):
        st.dataframe(_arrow_safe_rows(summary), width="stretch", hide_index=True)
        total = _total(panel)
        st.write(f"Overall CE change since open: {_signed(total.get('ce_opening_change'))} ({_percent(total.get('ce_opening_change_pct'))})")
        st.write(f"Overall PE change since open: {_signed(total.get('pe_opening_change'))} ({_percent(total.get('pe_opening_change_pct'))})")
        st.write(f"Morning fixed-level PCR: Total current PE OI ÷ Total current CE OI = {_number(aggregate.get('pcr'))}")
        st.write(f"PCR directional evidence: {_bias(aggregate.get('classification'), stale=stale)}")


def _render_refresh_diagnostics(panel: dict[str, Any]) -> None:
    aggregate = panel.get("aggregate") or {}
    current_timestamp = panel.get("source_timestamp")
    previous_timestamp = panel.get("previous_timestamp")
    current = _parse_aware_timestamp(current_timestamp)
    previous = _parse_aware_timestamp(previous_timestamp)
    elapsed = "Not available" if current is None or previous is None else f"{(current - previous).total_seconds():.1f}"
    with st.expander("Short-term OI movement since previous refresh", expanded=False):
        st.caption("This compares adjacent collector snapshots and may remain zero when the exchange-reported OI has not updated.")
        details = [
            {"Field": "Current snapshot timestamp", "Value": _format_ist_timestamp(current_timestamp)},
            {"Field": "Previous comparable snapshot timestamp", "Value": _format_ist_timestamp(previous_timestamp)},
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


def _render_current(
    projection: dict[str, Any],
    *,
    stale: bool,
    live_source_age: float | None,
    option_rows: list[dict[str, Any]] | None = None,
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
        {"Field": "Expected/observed contracts", "Value": f"{panel.get('expected_contract_count', 0)}/{panel.get('observed_contract_count', 0)}"},
        {"Field": "Source timestamp", "Value": _format_ist_timestamp(panel.get("source_timestamp"))},
        {"Field": "Source age", "Value": _source_age_text(live_source_age)},
        {"Field": "PCR", "Value": _number(aggregate.get("pcr"))},
        {"Field": "PCR directional evidence", "Value": _bias(aggregate.get("classification"), stale=stale)},
    ]
    total = _total(panel)
    total_panel = {"rows": [total]} if total else {"rows": []}
    st.dataframe(
        _arrow_safe_rows(_current_rows(total_panel)),
        width="stretch",
        hide_index=True,
    )
    with st.expander("Current/Overall PCR details", expanded=False):
        st.write(f"Total CE OI change: {_signed(total.get('ce_previous_day_change'))} ({_percent(total.get('ce_previous_day_change_pct'))})")
        st.write(f"Total PE OI change: {_signed(total.get('pe_previous_day_change'))} ({_percent(total.get('pe_previous_day_change_pct'))})")
        st.dataframe(_arrow_safe_rows(_current_rows(panel)), width="stretch", hide_index=True)
        st.markdown("#### Selected-strike Delta, VWAP and IV")
        st.caption(
            "Metrics are correlated by exact strike and CE/PE side from the "
            "latest persisted option-participation snapshot. They do not change "
            "the Current/Overall PCR calculation."
        )
        metric_rows = _option_metric_rows(panel, option_rows or [])
        metric_fields = (
            "CE current price", "CE Delta", "CE VWAP", "CE IV",
            "CE OI change %", "PE current price", "PE Delta", "PE VWAP",
            "PE IV", "PE OI change %",
        )
        if any(
            row.get(field) != "Not available"
            for row in metric_rows
            for field in metric_fields
        ):
            st.dataframe(
                _arrow_safe_rows(metric_rows),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Option metrics source time: "
                + _option_metrics_source_time(panel, option_rows or [])
            )
        else:
            st.info(
                "Delta, VWAP and IV are not available for the selected PCR "
                "strikes in the latest persisted option snapshot."
            )
        st.write(f"Current/Overall PCR: Total current PE OI ÷ Total current CE OI = {_number(aggregate.get('pcr'))}")
        st.write(f"PCR directional evidence: {_bias(aggregate.get('classification'), stale=stale)}")
        st.markdown("#### Current/Overall PCR snapshot details")
        st.dataframe(
            _arrow_safe_rows(summary),
            width="stretch",
            hide_index=True,
        )
    _render_refresh_diagnostics(panel)


def _render_operational_status(
    *, health_view: RuntimeHealthView, projection_age: float | None,
    projection_stale: bool, now: datetime
) -> None:
    projection_label = "STALE" if projection_stale else "FRESH"
    if projection_age is not None:
        projection_label += f" · {projection_age:.1f}s"
    st.markdown("### Market Trend Research Status")
    st.dataframe(_arrow_safe_rows([{
        "Collector status": health_view.state,
        "Projection status": projection_label,
        "Source age": _source_age_text(projection_age),
        "UI refresh": f"Every {MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g}s",
    }]), width="stretch", hide_index=True)
    with st.expander("Market Trend Research runtime details", expanded=False):
        st.write(f"Collector status: {health_view.state}")
        st.write(f"Heartbeat: {health_view.heartbeat}")
        st.write(f"Heartbeat age: {_source_age_text(health_view.heartbeat_age_seconds)}")
        st.write(f"Last success: {health_view.last_success}")
        if health_view.last_failure != "Not available":
            st.write(f"Last failure: {health_view.last_failure}")
        st.write(f"Consecutive failures: {health_view.consecutive_failures}")
        st.write(f"Collection cadence: {MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g} seconds")
        st.caption(f"Last UI refresh: {_format_ist_timestamp(now)}")
        st.caption(f"UI refresh: every {MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g} seconds · Read-only projection")
        st.caption("The collector runs as a separate observational process. This page does not start, stop or control it.")
    if health_view.state == "STOPPED":
        st.warning("No fresh data is being collected. Values below are retained for diagnosis.")
    elif health_view.state == "DEGRADED":
        reason = f" Reason: {health_view.safe_reason}." if health_view.safe_reason else ""
        st.warning(f"Collector health is degraded.{reason}")


def _render_projection_cycle(
    repository: MarketTrendResearchRepository,
    *, underlying: str,
    now: datetime | None = None,
    option_rows: list[dict[str, Any]] | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    projection = repository.latest_projection(underlying=underlying)
    health = repository.latest_runtime_health()
    health_view = _runtime_health_state(
        health, now=current,
        expected_refresh_seconds=MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS,
    )
    if not projection:
        _render_operational_status(
            health_view=health_view, projection_age=None,
            projection_stale=True, now=current,
        )
        st.info("No persisted Market Trend Research projection is available.")
        return
    quality = projection.get("quality") or {}
    live_source_age = _source_age_seconds(projection.get("source_timestamp"), now=current)
    threshold = _freshness_threshold_seconds()
    stale = live_source_age is None or live_source_age > threshold or quality.get("state") == "STALE"
    _render_operational_status(
        health_view=health_view, projection_age=live_source_age,
        projection_stale=stale, now=current,
    )
    if stale:
        if live_source_age is None:
            st.warning("STALE DATA — source age is not available. Values are shown for diagnosis only.")
        else:
            st.warning(f"STALE DATA — last research snapshot is {live_source_age:.1f} seconds old. Values are shown for diagnosis only.")
    st.caption(
        f"Declared runtime mode: {projection.get('runtime_mode', 'ONE_SHOT')} · "
        f"Persisted automatic-refresh label: {projection.get('automatic_refresh', 'NOT_CONNECTED')} · "
        f"Calendar source: {projection.get('calendar_source', 'Not available')}"
    )
    _render_morning(projection, stale=stale, live_source_age=live_source_age)
    _render_market_direction_research(projection, stale=stale)
    _render_current(
        projection,
        stale=stale,
        live_source_age=live_source_age,
        option_rows=option_rows,
    )
    with st.expander("Internal diagnostics", expanded=False):
        aggregate = (projection.get("current_panel") or {}).get("aggregate") or {}
        st.write({
            "raw_projection_source_timestamp": projection.get("source_timestamp"),
            "raw_runtime_health": health,
            "quality": projection.get("quality"),
            "persisted_evaluation_source_age_seconds": quality.get("source_age_seconds"),
            "live_source_age_seconds": live_source_age,
            "freshness_threshold_seconds": threshold,
            "runtime_health_state": health_view.state,
            "pcr_direction_reason_code": _direction_evidence(aggregate).get("reason_code"),
            "latency": projection.get("latency"),
            "lifecycle_state": projection.get("lifecycle_state"),
            "agreement_state": projection.get("agreement_state"),
            "schema_version": projection.get("schema_version"),
            "legacy_projection": not any(
                "ce_previous_day_oi" in row
                for row in (projection.get("current_panel") or {}).get("rows", [])
            ),
        })


@_fragment(run_every=f"{MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g}s")
def _market_trend_research_fragment(database_path: str | Path, underlying: str) -> None:
    option_rows = read_latest_option_participation(
        database_path,
        underlying_name=underlying,
    )
    _render_projection_cycle(
        MarketTrendResearchRepository(database_path),
        underlying=underlying,
        option_rows=option_rows,
    )


def render_market_trend_research_panel(database_path: str | Path, *, underlying: str) -> None:
    with st.expander("Market Trend Research architecture boundary", expanded=False):
        st.error("OBSERVATIONAL ONLY")
        st.write("Final Combined Market Direction: NOT YET CALCULATED")
        st.write("Signal generated: NO")
        st.write("Canonical bundle created: NO")
        st.write("Opportunity queued: NO")
        st.write("Paper trade created: NO")
    _market_trend_research_fragment(database_path, underlying)
