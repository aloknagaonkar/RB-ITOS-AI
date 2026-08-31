from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from red_bar_lab.services.market_trend_research.combined_pcr import (
    CombinedMarketPcrCalculator,
    TOP_TEN_WEIGHTS,
)
from red_bar_lab.services.market_trend_research.policy import (
    MarketTrendResearchPolicy,
)
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)
from red_bar_lab.services.market_trend_research.contract_selection import (
    pcr_research_preference,
    research_direction,
    select_best_contracts,
)
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)
from red_bar_lab.services.market_trend_research.volume_confirmation import (
    compare_volume_confirmation,
)
from red_bar_lab.ui._shared import _arrow_safe_rows, st
from red_bar_lab.ui.market_trend_research_panel import (
    MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS,
)

IST = ZoneInfo("Asia/Kolkata")


def _fragment(function):
    fragment = getattr(st, "fragment", None)
    return (
        fragment(run_every=f"{MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS:g}s")(function)
        if callable(fragment)
        else function
    )


def _number(value: object, digits: int = 3) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "Not available"
    return f"{float(value):.{digits}f}"


def _aggregate(panel: object) -> Mapping[str, Any]:
    if not isinstance(panel, Mapping):
        return {}
    aggregate = panel.get("aggregate")
    return aggregate if isinstance(aggregate, Mapping) else {}


def _pcr_direction(aggregate: Mapping[str, Any]) -> str:
    evidence = aggregate.get("direction_evidence")
    if isinstance(evidence, Mapping):
        direction = str(evidence.get("direction") or "").upper()
        if direction:
            return direction
    classification = str(aggregate.get("classification") or "UNAVAILABLE").upper()
    return "BULLISH" if "BULLISH" in classification else classification


def _fresh(source_timestamp: object, *, now: datetime) -> bool:
    return _fresh_with_limit(
        source_timestamp,
        now=now,
        maximum_age_seconds=MarketTrendResearchPolicy().maximum_source_age_seconds,
    )


def _fresh_with_limit(
    source_timestamp: object,
    *,
    now: datetime,
    maximum_age_seconds: float,
) -> bool:
    if not isinstance(source_timestamp, str):
        return False
    normalized = source_timestamp[:-1] + "+00:00" if source_timestamp.endswith("Z") else source_timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    age = (now - parsed.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= maximum_age_seconds


def _status(*, available: bool, fresh: bool, ready: bool = True) -> str:
    if not available:
        return "INCOMPLETE"
    if not fresh:
        return "STALE"
    return "FRESH" if ready else "PARTIAL"


@_fragment
def _render_summary_cycle(database_path: str | Path, underlying: str) -> None:
    now = datetime.now(timezone.utc)
    repository = MarketTrendResearchRepository(database_path)
    projection = repository.latest_projection(underlying=underlying)
    projection = projection or {}
    current_panel = projection.get("current_panel")
    morning_panel = projection.get("morning_panel")
    current_aggregate = _aggregate(current_panel)
    morning_aggregate = _aggregate(morning_panel)
    source_timestamp = projection.get("source_timestamp")
    pcr_fresh = _fresh(source_timestamp, now=now)
    raw_trading_date = projection.get("trading_date")
    try:
        trading_date = date.fromisoformat(str(raw_trading_date))
    except ValueError:
        trading_date = now.astimezone(IST).date()
    preopen = repository.latest_preopen_spots(
        underlying=underlying,
        trading_date=trading_date,
    )
    preopen_by_provider = {item.provider: item for item in preopen}
    nse_preopen = preopen_by_provider.get("NSE")
    upstox_preopen = preopen_by_provider.get("UPSTOX")
    preopen_difference = (
        abs(nse_preopen.spot - upstox_preopen.spot)
        if nse_preopen is not None and upstox_preopen is not None
        else None
    )
    preopen_difference_pct = (
        preopen_difference / nse_preopen.spot * 100.0
        if preopen_difference is not None and nse_preopen is not None
        else None
    )
    preopen_state = (
        "CONFLICT"
        if preopen_difference_pct is not None and preopen_difference_pct > 0.10
        else "ALIGNED"
        if nse_preopen is not None and upstox_preopen is not None
        else "NSE_ONLY"
        if nse_preopen is not None
        else "UPSTOX_ONLY"
        if upstox_preopen is not None
        else "UNAVAILABLE"
    )

    related = repository.latest_projections(
        underlyings=("NIFTY BANK", "SENSEX", *TOP_TEN_WEIGHTS),
    )
    combined_inputs: dict[str, Mapping[str, Any]] = {"NIFTY 50": projection}
    combined_inputs.update(related)
    combined = CombinedMarketPcrCalculator(
        accept_same_day_close=True,
    ).calculate(combined_inputs, now=now)

    option_rows = read_latest_option_participation(
        database_path,
        underlying_name=underlying,
    )
    trend_direction, trend_reason = research_direction(
        combined_direction=combined.direction,
        combined_ready=combined.score is not None,
        current_direction=_pcr_direction(current_aggregate),
        current_ready=bool(current_aggregate) and pcr_fresh,
        morning_direction=_pcr_direction(morning_aggregate),
    )
    preferred_side, preference_status, preference_reason = (
        pcr_research_preference(trend_direction)
    )
    preference_explanation = (
        preference_reason if preference_status == "PASSED" else trend_reason
    )
    current_rows = current_panel.get("rows") if isinstance(current_panel, Mapping) else ()
    selected_strikes = frozenset(
        float(row["strike"])
        for row in (current_rows or ())
        if isinstance(row, Mapping) and isinstance(row.get("strike"), (int, float))
        and row.get("position") != "TOTAL"
    )
    futures_rows = read_nifty_futures_snapshots(
        database_path,
        underlying_name="NIFTY 50",
        limit=1,
    )
    futures_relative_volume = (
        futures_rows[0].get("relative_volume") if futures_rows else None
    )
    volume_comparison = compare_volume_confirmation(
        option_rows,
        selected_expiry=(
            str(current_panel.get("expiry") or "")
            if isinstance(current_panel, Mapping) else ""
        ),
        selected_strikes=selected_strikes,
        futures_relative_volume=(
            float(futures_relative_volume)
            if isinstance(futures_relative_volume, (int, float))
            and not isinstance(futures_relative_volume, bool)
            else None
        ),
    )
    candidates = select_best_contracts(
        option_rows,
        preferred_side=preferred_side,
        selected_expiry=str(current_panel.get("expiry") or "") if isinstance(current_panel, Mapping) else "",
        selected_strikes=selected_strikes,
        limit=4,
    ) if preference_status == "PASSED" else ()
    top_ten = next(
        component for component in combined.components
        if component.name == "NIFTY TOP 10"
    )

    rows = [
        {
            "Component": "Pre-Open NIFTY Reference",
            "Live value": (
                f"NSE {_number(nse_preopen.spot, 2)} / "
                f"Upstox {_number(upstox_preopen.spot, 2)}"
                if nse_preopen is not None and upstox_preopen is not None
                else _number((nse_preopen or upstox_preopen).spot, 2)
                if (nse_preopen or upstox_preopen) is not None
                else "Not available"
            ),
            "Direction": "OBSERVATION",
            "Status": preopen_state,
            "Interpretation": (
                f"Difference {_number(preopen_difference, 2)} points / "
                f"{_number(preopen_difference_pct, 3)}%"
                if preopen_difference is not None
                else "Waiting for both independent sources"
            ),
        },
        {
            "Component": "Morning Fixed-Level PCR",
            "Live value": _number(morning_aggregate.get("pcr")),
            "Direction": _pcr_direction(morning_aggregate),
            "Status": _status(
                available=bool(morning_aggregate),
                fresh=pcr_fresh,
            ),
            "Interpretation": "Fixed morning strike positioning",
        },
        {
            "Component": "Combined Index PCR",
            "Live value": _number(combined.index_pcr),
            "Direction": combined.direction,
            "Status": "FRESH" if combined.score is not None else "INCOMPLETE",
            "Interpretation": (
                f"{combined.agreement}; {combined.coverage:.0%} coverage"
            ),
        },
        {
            "Component": "NIFTY Top-10 PCR Breadth",
            "Live value": _number(top_ten.pcr),
            "Direction": top_ten.direction,
            "Status": "FRESH" if top_ten.fresh else "INCOMPLETE",
            "Interpretation": top_ten.detail,
        },
        {
            "Component": "Current/Overall PCR",
            "Live value": _number(current_aggregate.get("pcr")),
            "Direction": _pcr_direction(current_aggregate),
            "Status": _status(
                available=bool(current_aggregate),
                fresh=pcr_fresh,
            ),
            "Interpretation": "Current NIFTY option positioning",
        },
        {
            "Component": "PCR research CE/PE preference",
            "Live value": f"BUY {preferred_side}" if preferred_side in {"CE", "PE"} else "WAIT",
            "Direction": trend_direction,
            "Status": preference_status,
            "Interpretation": preference_explanation,
        },
        {
            "Component": "Volume Confirmation",
            "Live value": (
                f"CE {volume_comparison.ce.score:.0f}/20 · "
                f"PE {volume_comparison.pe.score:.0f}/20"
            ),
            "Direction": volume_comparison.direction,
            "Status": volume_comparison.status,
            "Interpretation": volume_comparison.interpretation,
        },
        {
            "Component": "Best four contracts",
            "Live value": "; ".join(candidate.symbol for candidate in candidates) or "Not selected",
            "Direction": preferred_side if preferred_side in {"CE", "PE"} else "WAIT",
            "Status": "ELIGIBLE" if len(candidates) == 4 else "PARTIAL" if candidates else "BLOCKED",
            "Interpretation": f"{len(candidates)}/4 eligible contracts; {trend_reason}",
        },
    ]
    st.markdown("## Market Direction Summary")
    st.caption(
        "OBSERVATION ONLY — NO TRADING AUTHORITY. "
        "This page does not create, reject, bundle, reserve or execute a trade."
    )
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    with st.expander("Pre-open NIFTY source evidence", expanded=False):
        if preopen:
            st.dataframe(_arrow_safe_rows([{
                "Provider": item.provider,
                "Spot": f"{item.spot:,.2f}",
                "Source time (IST)": item.source_timestamp.astimezone(IST).strftime(
                    "%d %b %Y, %I:%M:%S %p IST"
                ),
                "Captured time (IST)": item.captured_at.astimezone(IST).strftime(
                    "%d %b %Y, %I:%M:%S %p IST"
                ),
                "Status": item.status,
            } for item in preopen]), width="stretch", hide_index=True)
            st.caption(
                "NSE is preferred for the immutable morning reference when fresh; "
                "Upstox is retained independently as validation and fallback evidence."
            )
        else:
            st.info("No pre-open NIFTY source observations have been stored for this session.")
    with st.expander("Volume Confirmation details", expanded=False):
        volume_checks = tuple(
            (side, check)
            for side, confirmation in (
                ("CE", volume_comparison.ce),
                ("PE", volume_comparison.pe),
            )
            for check in confirmation.checks
        )
        if volume_checks:
            st.dataframe(_arrow_safe_rows([{
                "Side": side,
                "Check": check.check,
                "Live value": check.live_value,
                "Required": check.required,
                "Status": check.status,
                "Points": f"{check.points:.0f}",
            } for side, check in volume_checks]), width="stretch", hide_index=True)
        else:
            st.info(
                "CE/PE volume comparison is incomplete because current option "
                "participation rows are unavailable."
            )
        st.caption(
            "Observational only. Volume confirmation does not create, reject, "
            "bundle, reserve or execute a trade."
        )
    with st.expander("Best four contract selection details", expanded=False):
        if candidates:
            st.dataframe(_arrow_safe_rows([{
                "Rank": item.rank,
                "Contract": item.symbol,
                "Side": item.side,
                "Strike": f"{item.strike:.0f}",
                "Expiry": item.expiry,
                "Price": f"{item.current_price:.2f}",
                "Delta": f"{item.delta:.4f}",
                "VWAP": f"{item.vwap:.2f}",
                "IV": f"{item.iv:.2f}",
                "OI change %": _number(item.oi_change_pct, 2),
                "Premium change %": _number(item.premium_change_pct, 2),
                "Activity": item.activity,
                "Buildup interpretation": item.interpretation,
                "Bid / Ask": f"{item.bid:.2f} / {item.ask:.2f}",
                "Spread %": f"{item.spread_pct:.2f}%",
                "Score": f"{item.score:.1f}",
                "Reason": item.reason,
            } for item in candidates]), width="stretch", hide_index=True)
        else:
            st.info(f"No contracts selected. {preference_reason}")
    _render_v2_pcr_section(database_path)
    st.caption(
        "Read-only summary of persisted research. Detailed evidence remains "
        "inside the two tabs below; this summary has no trading authority."
    )


def _read_v2_pcr_evidence(database_path: str | Path) -> dict[str, object] | None:
    """Read the most recent V2 strategy ``check:pcr_informational`` row.

    Returns the row dict (with ``artifacts`` already decoded) or ``None``
    if the strategy has not yet recorded one today. Best-effort: any DB
    error returns ``None`` so the page can keep rendering.
    """
    try:
        from red_bar_lab.storage.database import RedBarDatabase
        db = RedBarDatabase(str(database_path))
        return db.read_latest_step_evidence(
            process_name="red_bar_v2_strategy",
            step_name="check:pcr_informational",
        )
    except Exception:
        return None


def _format_v2_pcr_row(evidence: Mapping[str, object] | None) -> dict[str, str]:
    artifacts = (evidence or {}).get("artifacts") or {}
    if not isinstance(artifacts, Mapping):
        artifacts = {}
    current = artifacts.get("current_pcr")
    morning = artifacts.get("morning_pcr")
    shift = artifacts.get("shift")

    def _fmt(value: object) -> str:
        if isinstance(value, bool):
            return "Not available"
        if isinstance(value, (int, float)):
            return f"{float(value):.3f}"
        return "Not available"

    if evidence is None or (current is None and morning is None):
        status = "UNAVAILABLE"
        direction = "—"
        interpretation = (
            "Red Bar V2 strategy has not recorded a PCR audit row yet. "
            "The values above are the research PCR, not the strategy PCR."
        )
    else:
        status = str((evidence or {}).get("status") or "—")
        direction = "INFORMATIONAL"
        if isinstance(shift, (int, float)) and not isinstance(shift, bool):
            if shift > 0.05:
                interpretation = "current > morning (positioning shifted bullish)"
            elif shift < -0.05:
                interpretation = "current < morning (positioning shifted bearish)"
            else:
                interpretation = "current ≈ morning (positioning stable)"
        else:
            interpretation = "shift not computable (one of the values missing)"

    return {
        "Component": "V2 Strategy PCR (current 5m)",
        "Live value": _fmt(current),
        "Direction": direction,
        "Status": status,
        "Interpretation": interpretation,
    }


def _render_v2_pcr_section(database_path: str | Path) -> None:
    evidence = _read_v2_pcr_evidence(database_path)
    row = _format_v2_pcr_row(evidence)
    with st.expander("Red Bar V2 strategy PCR context (informational)", expanded=False):
        st.dataframe(
            _arrow_safe_rows([row]),
            width="stretch",
            hide_index=True,
        )
        artifacts = (evidence or {}).get("artifacts") or {}
        if isinstance(artifacts, Mapping) and artifacts:
            detail_rows = [
                {
                    "Field": "current_pcr",
                    "Value": artifacts.get("current_pcr", "Not available"),
                },
                {
                    "Field": "morning_pcr",
                    "Value": artifacts.get("morning_pcr", "Not available"),
                },
                {
                    "Field": "shift",
                    "Value": artifacts.get("shift", "Not computable"),
                },
            ]
            st.caption("Raw audit values:")
            st.dataframe(
                _arrow_safe_rows(detail_rows),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Source: process_evidence row where step_name = "
                "'check:pcr_informational'. Run id = "
                f"`{evidence.get('run_id', '—')}` · "
                f"started_at = `{evidence.get('started_at', '—')}`."
            )
        else:
            st.caption(
                "No process_evidence row for step_name='check:pcr_informational' "
                "was found. The Red Bar V2 strategy writes this row whenever a "
                "live evaluation records a current or morning PCR value."
            )
        st.caption(
            "Read-only. The V2 strategy does not block admission on PCR; "
            "this panel exists so the trader can see what PCR the strategy "
            "actually saw, not just what the research layer reports."
        )


def render_market_direction_summary(
    database_path: str | Path,
    *,
    underlying: str,
) -> None:
    _render_summary_cycle(database_path, underlying)


__all__ = ["render_market_direction_summary"]
