from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar
from zoneinfo import ZoneInfo

import streamlit as st

from red_bar_lab.services.market_trend_research.models import PcrBias
from red_bar_lab.services.market_trend_research.combined_pcr import (
    CombinedMarketPcr,
    CombinedMarketPcrCalculator,
    TOP_TEN_WEIGHTS,
)
from red_bar_lab.services.market_trend_research.contract_selection import (
    ContractSelection,
    _activity,
    _activity_interpretation,
    pcr_research_preference,
    research_direction,
    select_best_contracts,
)
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
    "Strike PCR", "PCR direction", "Previous refresh PCR",
    "PCR change vs refresh", "Opening PCR", "PCR change vs opening",
    "Overall PCR", "Overall PCR signal", "Recommendation",
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


def _signed_decimal(value: object, digits: int = 3) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if number == 0:
        return f"{number:.{digits}f}"
    return ("+" if number > 0 else "-") + f"{abs(number):.{digits}f}"


def _percent(value: object) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if number == 0:
        return "0.00%"
    return ("+" if number > 0 else "−") + f"{abs(number):.2f}%"


def _history_change_pct(
    persisted_pct: object,
    *,
    current_oi: object,
    absolute_change: object,
) -> float | None:
    """Recover legacy change percentage from persisted totals when possible."""

    if isinstance(persisted_pct, (int, float)) and not isinstance(
        persisted_pct, bool
    ):
        return float(persisted_pct)
    if (
        not isinstance(current_oi, (int, float))
        or isinstance(current_oi, bool)
        or not isinstance(absolute_change, (int, float))
        or isinstance(absolute_change, bool)
    ):
        return None
    previous_day_oi = float(current_oi) - float(absolute_change)
    if previous_day_oi <= 0:
        return None
    return float(absolute_change) / previous_day_oi * 100.0


def _movement(value: float | None, *, threshold: float) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value >= threshold:
        return "RISING"
    if value <= -threshold:
        return "FALLING"
    return "FLAT"


def _price_pcr_relationship(price_trend: str, pcr_trend: str) -> str:
    if "UNAVAILABLE" in {price_trend, pcr_trend}:
        return "INSUFFICIENT_HISTORY"
    if price_trend == pcr_trend == "RISING":
        return "BULLISH_CONFIRMATION"
    if price_trend == pcr_trend == "FALLING":
        return "BEARISH_CONFIRMATION"
    if price_trend == "FALLING" and pcr_trend == "RISING":
        return "BULLISH_DIVERGENCE"
    if price_trend == "RISING" and pcr_trend == "FALLING":
        return "BEARISH_DIVERGENCE"
    if price_trend == "FLAT" and pcr_trend != "FLAT":
        return "POSITIONING_LEADS_PRICE"
    if pcr_trend == "FLAT" and price_trend != "FLAT":
        return "PRICE_UNCONFIRMED"
    return "FLAT"


def _incremental_oi_driver(
    ce_change: float | None,
    pe_change: float | None,
) -> str:
    if ce_change is None or pe_change is None:
        return "UNAVAILABLE"
    side, value = (
        ("CE", ce_change)
        if abs(ce_change) >= abs(pe_change)
        else ("PE", pe_change)
    )
    if value == 0:
        return "FLAT"
    return f"{side}_{'ADDITION' if value > 0 else 'REDUCTION'}"


def _number(value: object, digits: int = 3) -> str:
    return "Not available" if value is None else f"{float(value):.{digits}f}"


def _oi_shares(aggregate: Mapping[str, object]) -> tuple[float | None, float | None]:
    ce = aggregate.get("total_ce_oi")
    pe = aggregate.get("total_pe_oi")
    if (
        not isinstance(ce, (int, float)) or isinstance(ce, bool)
        or not isinstance(pe, (int, float)) or isinstance(pe, bool)
    ):
        return None, None
    total = float(ce) + float(pe)
    if total <= 0:
        return None, None
    return float(ce) / total * 100.0, float(pe) / total * 100.0


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


def _strike_pcr(pe_oi: object, ce_oi: object) -> float | None:
    if not isinstance(pe_oi, (int, float)) or isinstance(pe_oi, bool):
        return None
    if not isinstance(ce_oi, (int, float)) or isinstance(ce_oi, bool) or ce_oi <= 0:
        return None
    return float(pe_oi) / float(ce_oi)


def _strike_pcr_direction(pcr: float | None) -> str:
    if pcr is None:
        return "UNAVAILABLE"
    return MarketTrendResearchPolicy().classify(pcr).value


def _strike_recommendation(signal: str, *, total: bool = False) -> str:
    if total:
        return "OBSERVATION"
    if signal == "BEARISH":
        return "BUY PE"
    if signal in {"BULLISH", "STRONGLY_BULLISH"}:
        return "BUY CE"
    return "WAIT"


def _current_rows(panel: dict[str, Any]) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    aggregate = panel.get("aggregate") or {}
    overall_pcr = (
        float(aggregate["pcr"])
        if isinstance(aggregate, Mapping)
        and isinstance(aggregate.get("pcr"), (int, float))
        else None
    )
    overall_signal = _strike_pcr_direction(overall_pcr)
    for row in panel.get("rows") or []:
        current_pcr = _strike_pcr(
            _field(row, "pe_current_oi"),
            _field(row, "ce_current_oi"),
        )
        refresh_pcr = _strike_pcr(
            _field(row, "pe_previous_refresh_oi"),
            _field(row, "ce_previous_refresh_oi"),
        )
        opening_pcr = _strike_pcr(
            _field(row, "pe_opening_oi"),
            _field(row, "ce_opening_oi"),
        )
        strike_signal = _strike_pcr_direction(current_pcr)
        rendered.append({
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
        "Strike PCR": _number(current_pcr),
        "PCR direction": strike_signal,
        "Previous refresh PCR": _number(refresh_pcr),
        "PCR change vs refresh": _signed_decimal(
            None if current_pcr is None or refresh_pcr is None else current_pcr - refresh_pcr
        ),
        "Opening PCR": _number(opening_pcr),
        "PCR change vs opening": _signed_decimal(
            None if current_pcr is None or opening_pcr is None else current_pcr - opening_pcr
        ),
        "Overall PCR": _number(overall_pcr),
        "Overall PCR signal": overall_signal,
        "Recommendation": _strike_recommendation(
            strike_signal,
            total=str(row.get("position") or "").upper() == "TOTAL",
        ),
        })
    return rendered


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


def _render_combined_market_pcr(
    repository: MarketTrendResearchRepository,
    *,
    nifty_projection: dict[str, Any],
    now: datetime,
) -> CombinedMarketPcr:
    snapshots: dict[str, dict[str, Any]] = {"NIFTY 50": nifty_projection}
    batch_reader = getattr(repository, "latest_projections", None)
    if callable(batch_reader):
        snapshots.update(batch_reader(
            underlyings=("NIFTY BANK", "SENSEX", *TOP_TEN_WEIGHTS),
        ))
    result = CombinedMarketPcrCalculator(
        maximum_age_seconds=_freshness_threshold_seconds(),
        accept_same_day_close=True,
    ).calculate(snapshots, now=now)
    st.markdown("## Combined Index PCR — NIFTY, Bank NIFTY and SENSEX")
    st.dataframe(_arrow_safe_rows([{
        "Combined PCR": (
            "Not available" if result.index_pcr is None else f"{result.index_pcr:.3f}"
        ),
        "Direction": result.direction,
        "Coverage": f"{result.coverage:.0%}",
        "Status": "FRESH" if result.index_pcr is not None else "INCOMPLETE",
    }]), width="stretch", hide_index=True)
    if result.score is None:
        st.info(
            "Combined Index PCR is withheld until NIFTY 50, Bank NIFTY and "
            "SENSEX all have usable PCR evidence."
        )
    with st.expander("Combined Index PCR component details", expanded=False):
        st.write(f"Index agreement: {result.agreement}")
        st.dataframe(_arrow_safe_rows([{
            "Component": component.name,
            "Weight": f"{component.weight:.0%}",
            "PCR": _number(component.pcr),
            "Direction": component.direction,
            "Fresh": "YES" if component.fresh else "NO",
            "Source time": _format_ist_timestamp(component.source_timestamp),
            "Coverage detail": component.detail,
        } for component in result.components if component.name != "NIFTY TOP 10"]), width="stretch", hide_index=True)
        st.caption(
            "Observational only. The score combines normalized directional "
            "evidence; it is not an arithmetic average of PCR ratios and has "
            "no signal, bundle, queue or execution authority."
        )
    direction_labels = {
        "BULLISH": "🟢 BULLISH",
        "BEARISH": "🔴 BEARISH",
        "NEUTRAL": "🟡 NEUTRAL",
        "UNAVAILABLE": "⚪ UNAVAILABLE",
    }
    top_ten_rows: list[dict[str, object]] = []
    for symbol, weight in TOP_TEN_WEIGHTS.items():
        snapshot = snapshots.get(symbol) or {}
        panel = snapshot.get("current_panel")
        aggregate = panel.get("aggregate") if isinstance(panel, Mapping) else {}
        aggregate = aggregate if isinstance(aggregate, Mapping) else {}
        evidence = _direction_evidence(aggregate)
        direction = str(evidence.get("direction") or "UNAVAILABLE").upper()
        top_ten_rows.append({
            "Stock": symbol,
            "NIFTY weight": f"{weight:.2f}%",
            "PCR": _number(aggregate.get("pcr")),
            "Direction": direction_labels.get(direction, f"⚪ {direction}"),
            "Source time": _format_ist_timestamp(snapshot.get("source_timestamp")),
        })
    top_ten_component = next(
        component for component in result.components
        if component.name == "NIFTY TOP 10"
    )
    st.markdown("## NIFTY Top-10 PCR Breadth")
    st.dataframe(_arrow_safe_rows([{
        "Breadth direction": direction_labels.get(
            top_ten_component.direction,
            top_ten_component.direction,
        ),
        "Weighted Top-10 PCR": _number(top_ten_component.pcr),
        "Coverage": top_ten_component.detail,
    }]), width="stretch", hide_index=True)
    with st.expander("NIFTY Top-10 stock directions", expanded=True):
        st.dataframe(
            _arrow_safe_rows(top_ten_rows),
            width="stretch",
            hide_index=True,
        )
    return result


def _contract_selection_for_cycle(
    repository: MarketTrendResearchRepository,
    *,
    projection: dict[str, Any],
    combined: CombinedMarketPcr,
    option_rows: list[dict[str, Any]],
    underlying: str,
    now: datetime,
    pcr_stale: bool,
) -> ContractSelection:
    path = getattr(repository, "path", None)
    if path is None:
        return ContractSelection("NONE", "INCOMPLETE", "Repository source unavailable", ())
    current_panel = projection.get("current_panel") or {}
    current_aggregate = current_panel.get("aggregate") or {}
    morning_aggregate = (projection.get("morning_panel") or {}).get("aggregate") or {}
    current_direction = str(_direction_evidence(current_aggregate).get("direction") or "UNAVAILABLE")
    morning_direction = str(_direction_evidence(morning_aggregate).get("direction") or "UNAVAILABLE")
    trend_direction, _ = research_direction(
        combined_direction=combined.direction,
        combined_ready=combined.score is not None,
        current_direction=current_direction,
        current_ready=bool(current_aggregate) and not pcr_stale,
        morning_direction=morning_direction,
    )
    side, status, reason = pcr_research_preference(trend_direction)
    rows = current_panel.get("rows") or []
    selected_strikes = frozenset(
        float(row["strike"])
        for row in rows
        if isinstance(row, Mapping)
        and isinstance(row.get("strike"), (int, float))
        and row.get("position") != "TOTAL"
    )
    candidates = select_best_contracts(
        option_rows,
        preferred_side=side,
        selected_expiry=str(current_panel.get("expiry") or ""),
        selected_strikes=selected_strikes,
        limit=4,
    ) if status == "PASSED" else ()
    return ContractSelection(side, status, reason, candidates)


def _render_best_contracts(selection: ContractSelection) -> None:
    st.markdown("#### Best four contracts from PCR research")
    if not selection.candidates:
        st.info(f"No contracts selected. {selection.reason}")
        return
    st.dataframe(_arrow_safe_rows([{
        "Rank": item.rank, "Contract": item.symbol, "Side": item.side,
        "Strike": f"{item.strike:.0f}", "Expiry": item.expiry,
        "Price": f"{item.current_price:.2f}", "Delta": f"{item.delta:.4f}",
        "VWAP": f"{item.vwap:.2f}", "IV": f"{item.iv:.2f}",
        "OI change %": _percent(item.oi_change_pct),
        "Premium change %": _percent(item.premium_change_pct),
        "Activity": item.activity,
        "Buildup interpretation": item.interpretation,
        "Bid / Ask": f"{item.bid:.2f} / {item.ask:.2f}",
        "Spread %": f"{item.spread_pct:.2f}%", "Score": f"{item.score:.1f}",
        "Reason": item.reason,
    } for item in selection.candidates]), width="stretch", hide_index=True)
    st.caption("Observational selection only. It creates no signal, opportunity or order.")


def _available_trading_days(
    repository: object,
    method_name: str,
    underlying: str,
) -> list[str]:
    """Best-effort distinct trading days via a repository reader method."""
    reader = getattr(repository, method_name, None)
    if not callable(reader):
        return []
    try:
        days = reader(underlying)
    except Exception:
        return []
    return [str(day) for day in days if day]


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result == result else None


def _nearest_history_entry(
    history_rows: list[dict[str, Any]],
    opened_at: datetime,
) -> tuple[dict[str, Any] | None, float | None]:
    """Pick the 5m PCR candle closest to a recommendation open time."""
    if opened_at.tzinfo is None or opened_at.utcoffset() is None:
        raise ValueError("opened_at must be timezone-aware")
    best_row: dict[str, Any] | None = None
    best_age: float | None = None
    for row in history_rows:
        candle = _parse_aware_timestamp(row.get("candle_close_timestamp"))
        if candle is None:
            continue
        age = abs((candle - opened_at).total_seconds())
        if best_age is None or age < best_age:
            best_row, best_age = row, age
    return best_row, best_age


def _pcr_side_alignment(
    side: object,
    pcr_change: float | None,
    *,
    threshold: float = 0.01,
) -> str:
    """Classify whether PCR movement supported the recommended side.

    The research policy reads rising PCR as bullish (favoring CE) and
    falling PCR as bearish (favoring PE).
    """
    if pcr_change is None:
        return "UNAVAILABLE"
    if abs(pcr_change) < threshold:
        return "FLAT"
    aligned = pcr_change > 0 if str(side).upper() == "CE" else pcr_change < 0
    return "WITH" if aligned else "AGAINST"


def _recommendation_pcr_rows(
    recommendation_rows: list[dict[str, Any]],
    history_rows: list[dict[str, Any]],
) -> list[dict[str, object]]:
    """Join each recommendation to the PCR evidence at its open time."""
    rendered: list[dict[str, object]] = []
    for row in recommendation_rows:
        opened_at = _parse_aware_timestamp(row.get("opened_at"))
        entry_overall = _float_or_none(row.get("entry_overall_pcr"))
        current_overall = _float_or_none(row.get("overall_pcr"))
        pcr_change = (
            current_overall - entry_overall
            if entry_overall is not None and current_overall is not None
            else None
        )
        candle, candle_age = (
            _nearest_history_entry(history_rows, opened_at)
            if opened_at is not None and history_rows
            else (None, None)
        )
        rendered.append({
            "Opened": _format_ist_timestamp(row.get("opened_at")),
            "Contract": (
                row.get("symbol")
                or f"{_number(row.get('strike'), 0)} {row.get('side') or ''}"
            ),
            "Side": row.get("side") or "Not available",
            "Entry strike PCR": _number(row.get("entry_strike_pcr")),
            "Overall PCR at entry": _number(entry_overall),
            "Entry delta": _number(_float_or_none(row.get("entry_delta"))),
            "Entry IV": _number(_float_or_none(row.get("entry_iv")), 2),
            "Entry contract VWAP": _number(
                _float_or_none(row.get("entry_contract_vwap")), 2
            ),
            "5m PCR at entry": _number(
                (candle or {}).get("overall_pcr")
            ),
            "Morning PCR at entry": _number(
                (candle or {}).get("morning_pcr")
            ),
            "Combined PCR at entry": _number(
                (candle or {}).get("combined_index_pcr")
            ),
            "Top-10 PCR at entry": _number(
                (candle or {}).get("top_ten_pcr")
            ),
            "Direction at entry": (
                (candle or {}).get("research_direction") or "Not available"
            ),
            "Overall PCR now": _number(current_overall),
            "PCR change since entry": _signed_decimal(pcr_change),
            "PCR vs recommended side": _pcr_side_alignment(
                row.get("side"), pcr_change
            ),
            "Matched candle age": (
                f"{candle_age:.0f}s" if candle_age is not None else "Not available"
            ),
        })
    return rendered


def _render_five_minute_pcr_history(
    repository: MarketTrendResearchRepository,
    *,
    underlying: str,
    now: datetime,
) -> None:
    today_ist = now.astimezone(IST).date()
    days = _available_trading_days(
        repository, "five_minute_pcr_trading_days", underlying
    )
    with st.expander("5-Minute Overall PCR History", expanded=False):
        if days:
            default = next(
                (day for day in days if day <= today_ist.isoformat()), days[0]
            )
            selected = st.selectbox(
                "Trading date",
                days,
                index=days.index(default),
                key="pcr_5m_history_trading_date",
            )
            try:
                chosen = date.fromisoformat(selected)
            except ValueError:
                chosen = today_ist
        else:
            chosen = today_ist
        reader = getattr(repository, "five_minute_pcr_history", None)
        rows = (
            reader(underlying=underlying, trading_date=chosen)
            if callable(reader)
            else []
        )
        if not rows:
            st.info(
                "Waiting for the first completed 5-minute candle with a "
                "contemporaneous Overall PCR snapshot."
            )
            return
        rendered: list[dict[str, object]] = []
        previous_spot: float | None = None
        previous_pcr: float | None = None
        previous_ce_day_change: float | None = None
        previous_pe_day_change: float | None = None
        for row in reversed(rows):
            spot = row.get("nifty_spot")
            spot = float(spot) if isinstance(spot, (int, float)) else None
            pcr = row.get("overall_pcr")
            pcr = float(pcr) if isinstance(pcr, (int, float)) else None
            price_change = (
                spot - previous_spot
                if spot is not None and previous_spot is not None
                else None
            )
            price_change_pct = (
                price_change / previous_spot * 100.0
                if price_change is not None and previous_spot not in {None, 0}
                else None
            )
            pcr_change = (
                pcr - previous_pcr
                if pcr is not None and previous_pcr is not None
                else None
            )
            price_trend = _movement(price_change_pct, threshold=0.05)
            pcr_trend = _movement(pcr_change, threshold=0.02)
            ce_day_change = row.get("ce_day_oi_change")
            ce_day_change = float(ce_day_change) if isinstance(ce_day_change, (int, float)) else None
            pe_day_change = row.get("pe_day_oi_change")
            pe_day_change = float(pe_day_change) if isinstance(pe_day_change, (int, float)) else None
            ce_increment = (
                ce_day_change - previous_ce_day_change
                if ce_day_change is not None and previous_ce_day_change is not None
                else None
            )
            pe_increment = (
                pe_day_change - previous_pe_day_change
                if pe_day_change is not None and previous_pe_day_change is not None
                else None
            )
            ce_change_pct = _history_change_pct(
                row.get("ce_day_oi_change_pct"),
                current_oi=row.get("total_ce_oi"),
                absolute_change=row.get("ce_day_oi_change"),
            )
            pe_change_pct = _history_change_pct(
                row.get("pe_day_oi_change_pct"),
                current_oi=row.get("total_pe_oi"),
                absolute_change=row.get("pe_day_oi_change"),
            )
            rendered.append({
                "Time": _format_ist_timestamp(row.get("candle_close_timestamp")),
                "NIFTY spot": _number(row.get("nifty_spot"), 2),
                "NIFTY change": _signed_decimal(price_change, 2),
                "NIFTY change %": _percent(price_change_pct),
                "RSI": _number(row.get("rsi"), 2),
                "VWAP": _number(row.get("vwap"), 2),
                "Fixed Morning PCR": _number(row.get("morning_pcr")),
                "NIFTY Strike PCR": _number(row.get("overall_pcr")),
                "PCR change": _signed_decimal(pcr_change),
                "Price trend": price_trend,
                "PCR trend": pcr_trend,
                "Price–PCR relationship": _price_pcr_relationship(
                    price_trend,
                    pcr_trend,
                ),
                "OI driver": _incremental_oi_driver(ce_increment, pe_increment),
                "Combined Index PCR": _number(row.get("combined_index_pcr")),
                "NIFTY Top-10 PCR": _number(row.get("top_ten_pcr")),
                "Overall Direction": row.get("research_direction", "Not available"),
                "CE day OI change %": _percent(ce_change_pct),
                "PE day OI change %": _percent(pe_change_pct),
                "CE day OI change": _signed(row.get("ce_day_oi_change")),
                "PE day OI change": _signed(row.get("pe_day_oi_change")),
            })
            previous_spot = spot if spot is not None else previous_spot
            previous_pcr = pcr if pcr is not None else previous_pcr
            previous_ce_day_change = (
                ce_day_change
                if ce_day_change is not None
                else previous_ce_day_change
            )
            previous_pe_day_change = (
                pe_day_change
                if pe_day_change is not None
                else previous_pe_day_change
            )
        st.dataframe(
            _arrow_safe_rows(list(reversed(rendered))),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "One immutable observation per completed NIFTY five-minute candle. "
            "This history is observational and has no signal or execution authority."
        )


def _render_strike_pcr_recommendation_tracker(
    repository: MarketTrendResearchRepository,
    *,
    underlying: str,
    now: datetime,
    option_rows: list[dict[str, Any]] | None = None,
) -> None:
    today_ist = now.astimezone(IST).date()
    days = _available_trading_days(
        repository, "strike_pcr_recommendation_trading_days", underlying
    )
    with st.expander("Strike PCR Buy Recommendation Tracker", expanded=False):
        if days:
            default = next(
                (day for day in days if day <= today_ist.isoformat()), days[0]
            )
            selected = st.selectbox(
                "Trading date",
                days,
                index=days.index(default),
                key="strike_pcr_recommendation_trading_date",
            )
            try:
                chosen = date.fromisoformat(selected)
            except ValueError:
                chosen = today_ist
        else:
            chosen = today_ist
        reader = getattr(repository, "strike_pcr_recommendations", None)
        rows = (
            reader(underlying=underlying, trading_date=chosen)
            if callable(reader)
            else []
        )
        option_evidence = {
            (float(item["strike"]), str(item.get("option_type") or "").upper()): item
            for item in (option_rows or [])
            if isinstance(item.get("strike"), (int, float))
        }
        if not rows:
            st.info(
                "No persisted strike-PCR recommendation is available yet. "
                "A recommendation opens only with a valid two-sided quote."
            )
            return

        def gain(current: object, entry: object) -> float | None:
            if not isinstance(current, (int, float)) or not isinstance(entry, (int, float)) or entry <= 0:
                return None
            return (float(current) - float(entry)) / float(entry) * 100.0

        rendered_rows: list[dict[str, object]] = []
        for row in rows:
            evidence = option_evidence.get(
                (float(row.get("strike", 0)), str(row.get("side") or "").upper()),
                {},
            )
            premium_change = evidence.get("premium_change_from_previous_refresh_pct")
            oi_change = evidence.get("oi_change_from_previous_refresh")
            activity = (
                _activity(float(premium_change), float(oi_change))
                if isinstance(premium_change, (int, float))
                and isinstance(oi_change, (int, float))
                else "UNAVAILABLE"
            )
            interpretation = (
                _activity_interpretation(str(row.get("side") or "").upper(), activity)
                if activity != "UNAVAILABLE"
                else "Not available"
            )
            rendered_rows.append({
            "State": row.get("status"),
            "Recommendation": f"BUY {row.get('side')}",
            "Contract": row.get("symbol") or f"{float(row.get('strike', 0)):.0f} {row.get('side')}",
            "Strike": _number(row.get("strike"), 0),
            "Entry strike PCR": _number(row.get("entry_strike_pcr")),
            "Current strike PCR": _number(row.get("last_strike_pcr")),
            "Strike signal": row.get("strike_signal"),
            "Entry Overall PCR": _number(row.get("entry_overall_pcr")),
            "Current Overall PCR": _number(row.get("overall_pcr")),
            "Overall PCR signal": row.get("overall_signal"),
            "Premium change %": _percent(premium_change),
            "OI change": _signed(oi_change),
            "Activity": activity,
            "Buildup interpretation": interpretation,
            "Entry ask (frozen)": _number(row.get("entry_price"), 2),
            "Current bid": _number(row.get("current_price"), 2),
            "Peak bid": _number(row.get("peak_price"), 2),
            "Current gain": _percent(gain(row.get("current_price"), row.get("entry_price"))),
            "Peak gain": _percent(gain(row.get("peak_price"), row.get("entry_price"))),
            "Opened": _format_ist_timestamp(row.get("opened_at")),
            "Peak time": _format_ist_timestamp(row.get("peak_at")),
            "Last update": _format_ist_timestamp(row.get("last_observed_at")),
            })
        st.dataframe(_arrow_safe_rows(rendered_rows), width="stretch", hide_index=True)
        st.caption(
            "PCR-only observational tracking. Entry uses the first valid ask; "
            "current and peak values use executable bid. No signal, opportunity "
            "or order is created."
        )
        history_reader = getattr(repository, "five_minute_pcr_history", None)
        history_rows = (
            history_reader(underlying=underlying, trading_date=chosen)
            if callable(history_reader)
            else []
        )
        st.markdown("#### PCR at recommendation time — evaluation view")
        st.dataframe(
            _arrow_safe_rows(_recommendation_pcr_rows(rows, history_rows)),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Each row joins one recommendation to the PCR evidence at its open "
            "time (nearest completed 5-minute candle): overall, morning, "
            "combined and top-10 PCR plus the research direction at that "
            "moment. 'PCR vs recommended side' compares the overall PCR "
            "movement since entry with the recommended side (rising PCR "
            "supports CE, falling PCR supports PE). Observational only — no "
            "signal, opportunity or order is created."
        )


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
    ce_share, pe_share = _oi_shares(aggregate)
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
    ]
    st.dataframe(_arrow_safe_rows([{
        "Fixed PCR": _number(aggregate.get("pcr")),
        "CE OI share": _percent(ce_share),
        "PE OI share": _percent(pe_share),
        "Direction": _bias(aggregate.get("classification"), stale=stale),
        "Status": "STALE" if stale else "FRESH",
    }]), width="stretch", hide_index=True)
    with st.expander("Morning Fixed-Level PCR details", expanded=False):
        st.dataframe(_arrow_safe_rows(_morning_rows(panel)), width="stretch", hide_index=True)
        st.dataframe(_arrow_safe_rows(summary), width="stretch", hide_index=True)
        total = _total(panel)
        st.write(f"Overall CE change since open: {_signed(total.get('ce_opening_change'))} ({_percent(total.get('ce_opening_change_pct'))})")
        st.write(f"Overall PE change since open: {_signed(total.get('pe_opening_change'))} ({_percent(total.get('pe_opening_change_pct'))})")
        st.caption("Fixed PCR = total current PE OI ÷ total current CE OI.")


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
    contract_selection: ContractSelection | None = None,
) -> None:
    st.markdown("## Current/Overall PCR")
    panel = projection.get("current_panel") or {}
    aggregate = panel.get("aggregate") or {}
    total = _total(panel)
    shares_source = aggregate if aggregate.get("total_ce_oi") is not None else {
        "total_ce_oi": total.get("ce_current_oi"),
        "total_pe_oi": total.get("pe_current_oi"),
    }
    ce_share, pe_share = _oi_shares(shares_source)
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
    ]
    st.dataframe(_arrow_safe_rows([{
        "Strike PCR": _number(aggregate.get("pcr")),
        "CE OI share": _percent(ce_share),
        "PE OI share": _percent(pe_share),
        "Direction": _bias(aggregate.get("classification"), stale=stale),
        "Status": "STALE" if stale else "FRESH",
    }]), width="stretch", hide_index=True)
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
        if contract_selection is not None:
            _render_best_contracts(contract_selection)
        st.caption("Strike PCR = total current PE OI ÷ total current CE OI.")
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
    combined = _render_combined_market_pcr(repository, nifty_projection=projection, now=current)
    contract_selection = _contract_selection_for_cycle(
        repository,
        projection=projection,
        combined=combined,
        option_rows=option_rows or [],
        underlying=underlying,
        now=current,
        pcr_stale=stale,
    )
    _render_current(
        projection,
        stale=stale,
        live_source_age=live_source_age,
        option_rows=option_rows,
        contract_selection=contract_selection,
    )
    _render_strike_pcr_recommendation_tracker(
        repository,
        underlying=underlying,
        now=current,
        option_rows=option_rows,
    )
    _render_five_minute_pcr_history(
        repository,
        underlying=underlying,
        now=current,
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
