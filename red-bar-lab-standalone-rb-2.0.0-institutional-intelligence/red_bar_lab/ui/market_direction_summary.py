from __future__ import annotations

import json
import sqlite3
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


def _read_pcr_history(
    database_path: str | Path,
    underlying: str,
    *,
    rolling_days: int = 3,
    sparkline_points: int = 20,
    now: datetime | None = None,
) -> dict[str, object]:
    """Read PCR historical context from the 5m history table.

    Returns a dict with:
        - previous_day_close (float | None): last 5m PCR of the most recent
          trading day strictly before today (None if not available)
        - previous_day_date (str | None): trading_date of that close
        - rolling_mean (float | None): mean of daily closing PCRs over the
          last ``rolling_days`` trading days, always excluding today so the
          window never contains intraday data from the current session
        - rolling_days_used (int): how many distinct days contributed
        - sparkline (list[tuple[str, float]]): the last ``sparkline_points``
          (timestamp, pcr) pairs ordered oldest -> newest, for plotting
    Best-effort: any DB error returns an empty result so the page keeps
    rendering.
    """
    empty: dict[str, object] = {
        "previous_day_close": None,
        "previous_day_date": None,
        "rolling_mean": None,
        "rolling_days_used": 0,
        "sparkline": [],
    }
    current = now or datetime.now(timezone.utc)
    today_ist = current.astimezone(IST).date().isoformat()
    try:
        with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            # 1) last close per completed trading day, most recent first
            daily_closes = conn.execute(
                """
                SELECT trading_date, overall_pcr, source_timestamp
                FROM (
                    SELECT trading_date, overall_pcr, source_timestamp,
                           ROW_NUMBER() OVER (
                               PARTITION BY trading_date
                               ORDER BY source_timestamp DESC
                           ) AS rk
                    FROM market_trend_research_pcr_5m_history
                    WHERE underlying = ? AND trading_date < ?
                ) WHERE rk = 1
                ORDER BY trading_date DESC
                """,
                (underlying, today_ist),
            ).fetchall()
            if not daily_closes:
                return empty
            previous_day = daily_closes[0]
            previous_day_close = float(previous_day["overall_pcr"])
            previous_day_date = str(previous_day["trading_date"])
            closes = [
                float(row["overall_pcr"])
                for row in daily_closes[: max(1, rolling_days)]
            ]
            rolling_mean = sum(closes) / len(closes) if closes else None
            # 2) last N 5m points for the sparkline
            rows = conn.execute(
                """
                SELECT source_timestamp, overall_pcr
                FROM market_trend_research_pcr_5m_history
                WHERE underlying = ?
                ORDER BY source_timestamp DESC
                LIMIT ?
                """,
                (underlying, sparkline_points),
            ).fetchall()
            sparkline = [
                (str(r["source_timestamp"]), float(r["overall_pcr"]))
                for r in reversed(rows)
            ]
            return {
                "previous_day_close": previous_day_close,
                "previous_day_date": previous_day_date,
                "rolling_mean": rolling_mean,
                "rolling_days_used": len(closes),
                "sparkline": sparkline,
            }
    except Exception:
        return empty


def _format_history_rows(history: Mapping[str, object]) -> list[dict[str, str]]:
    """Format the historical comparison rows for the summary table."""
    prev_close = history.get("previous_day_close")
    prev_date = history.get("previous_day_date")
    rolling = history.get("rolling_mean")
    rolling_n = history.get("rolling_days_used", 0)

    def _fmt(value: object) -> str:
        if isinstance(value, bool):
            return "Not available"
        if isinstance(value, (int, float)):
            return f"{float(value):.3f}"
        return "Not available"

    prev_status = "OK" if prev_close is not None else "INCOMPLETE"
    return [
        {
            "Component": "Previous trading day close (PCR)",
            "Live value": _fmt(prev_close),
            "Direction": "OBSERVATION",
            "Status": prev_status,
            "Interpretation": (
                f"Closing PCR for {prev_date}"
                if prev_date is not None
                else "No prior trading day in the 5m history table"
            ),
        },
        {
            "Component": f"Rolling mean PCR ({rolling_n}d)",
            "Live value": _fmt(rolling),
            "Direction": "OBSERVATION",
            "Status": "OK" if rolling is not None else "INCOMPLETE",
            "Interpretation": (
                "Mean of daily closing PCRs over the last "
                f"{rolling_n} trading day(s). Window is thin when fewer "
                "days are available."
            ),
        },
    ]


def _render_history_sparkline(history: Mapping[str, object]) -> None:
    sparkline = history.get("sparkline") or []
    if not sparkline:
        st.caption(
            "No 5m PCR history available yet for the sparkline."
        )
        return
    try:
        import pandas as _pd
        df = _pd.DataFrame(sparkline, columns=["timestamp", "pcr"])
        df["timestamp"] = _pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        st.line_chart(df, height=160)
    except Exception:
        # If pandas import or chart rendering fails, fall back to a small table
        st.dataframe(
            _arrow_safe_rows(
                [
                    {
                        "When": ts,
                        "PCR": f"{pcr:.3f}",
                    }
                    for ts, pcr in sparkline
                ]
            ),
            width="stretch",
            hide_index=True,
        )


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
    history = _read_pcr_history(database_path, underlying)
    current_index = next(
        (
            index
            for index, item in enumerate(rows)
            if item.get("Component") == "Current/Overall PCR"
        ),
        len(rows) - 1,
    )
    rows[current_index + 1:current_index + 1] = _format_history_rows(history)
    st.markdown("## Market Direction Summary")
    st.caption(
        "OBSERVATION ONLY — NO TRADING AUTHORITY. "
        "This page does not create, reject, bundle, reserve or execute a trade."
    )
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    with st.expander("PCR history — intraday sparkline", expanded=False):
        _render_history_sparkline(history)
        st.caption(
            "Last 5-minute Overall PCR observations across sessions. The "
            "previous-day close and rolling mean rows above always exclude "
            "today's intraday data."
        )
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


def _read_v2_cycle_journal_pcr(
    database_path: str | Path,
) -> dict[str, object] | None:
    """Read PCR context from the newest V2 cycle journal row that has one.

    The paper monitor journals overall/morning/combined PCR per cycle in
    ``red_bar_v2_cycle_evaluations.pcr_json``. Returns the most recent row
    with a non-empty PCR payload, or ``None`` when the journal table or PCR
    data is unavailable. Best-effort so the page keeps rendering.
    """
    try:
        with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT observed_at, trading_date, run_id,
                          admission_direction, admission_code, pcr_json
                   FROM red_bar_v2_cycle_evaluations
                   WHERE pcr_json IS NOT NULL AND pcr_json != '{}'
                   ORDER BY julianday(observed_at) DESC, observed_at DESC
                   LIMIT 1"""
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        pcr = json.loads(row["pcr_json"])
    except (TypeError, ValueError):
        return None
    if not isinstance(pcr, Mapping) or not pcr:
        return None
    return {
        "pcr": dict(pcr),
        "observed_at": row["observed_at"],
        "trading_date": row["trading_date"],
        "run_id": row["run_id"],
        "admission_direction": row["admission_direction"],
        "admission_code": row["admission_code"],
    }


def _format_v2_journal_pcr_row(
    journal: Mapping[str, object] | None,
) -> dict[str, str]:
    if not isinstance(journal, Mapping):
        return {
            "Component": "V2 Strategy PCR (latest cycle)",
            "Live value": "Not available",
            "Direction": "—",
            "Status": "UNAVAILABLE",
            "Interpretation": (
                "The V2 cycle journal has not recorded a PCR context yet."
            ),
        }
    pcr = journal.get("pcr")
    pcr = pcr if isinstance(pcr, Mapping) else {}
    overall = pcr.get("overall_pcr")
    overall_direction = str(pcr.get("overall_direction") or "—")
    observed_at = str(journal.get("observed_at") or "Not available")
    return {
        "Component": "V2 Strategy PCR (latest cycle)",
        "Live value": _number(overall),
        "Direction": overall_direction,
        "Status": "OBSERVED",
        "Interpretation": (
            "PCR context the V2 evaluation journaled on its latest cycle "
            f"(observed at {observed_at})"
        ),
    }


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


def _render_v2_journal_details(journal: Mapping[str, object]) -> None:
    pcr = journal.get("pcr")
    pcr = pcr if isinstance(pcr, Mapping) else {}
    detail_rows = [
        {"Field": "overall_pcr", "Value": _number(pcr.get("overall_pcr"))},
        {"Field": "overall_direction", "Value": str(pcr.get("overall_direction") or "Not available")},
        {"Field": "morning_pcr", "Value": _number(pcr.get("morning_pcr"))},
        {"Field": "combined_pcr", "Value": _number(pcr.get("combined_pcr"))},
        {"Field": "combined_direction", "Value": str(pcr.get("combined_direction") or "Not available")},
        {"Field": "combined_coverage", "Value": _number(pcr.get("combined_coverage"), 2)},
        {"Field": "admission_direction", "Value": str(journal.get("admission_direction") or "None")},
        {"Field": "admission_code", "Value": str(journal.get("admission_code") or "None")},
    ]
    st.caption("Journaled PCR context (latest cycle):")
    st.dataframe(
        _arrow_safe_rows(detail_rows),
        width="stretch",
        hide_index=True,
    )
    raw_observed_at = str(journal.get("observed_at") or "")
    try:
        observed_ist = datetime.fromisoformat(raw_observed_at).astimezone(IST)
        observed_text = observed_ist.strftime("%d %b %Y, %I:%M:%S %p IST")
    except (TypeError, ValueError):
        observed_text = raw_observed_at or "Not available"
    st.caption(
        "Source: red_bar_v2_cycle_evaluations.pcr_json · "
        f"Run id = `{journal.get('run_id', '—')}` · "
        f"Cycle observed at {observed_text}."
    )
    admission_direction = str(journal.get("admission_direction") or "")
    overall_direction = str(pcr.get("overall_direction") or "")
    if admission_direction and overall_direction and admission_direction != overall_direction:
        st.warning(
            f"Divergence to evaluate: the latest admitted candidate direction is "
            f"{admission_direction} while the journaled Overall PCR direction is "
            f"{overall_direction}."
        )


def _render_v2_pcr_section(database_path: str | Path) -> None:
    journal = _read_v2_cycle_journal_pcr(database_path)
    with st.expander("Red Bar V2 strategy PCR context (informational)", expanded=False):
        if journal is not None:
            st.dataframe(
                _arrow_safe_rows([_format_v2_journal_pcr_row(journal)]),
                width="stretch",
                hide_index=True,
            )
            _render_v2_journal_details(journal)
            st.caption(
                "Read-only. The V2 strategy does not block admission on PCR; "
                "this panel shows the PCR the strategy actually journaled on "
                "its latest cycle."
            )
            return
        evidence = _read_v2_pcr_evidence(database_path)
        row = _format_v2_pcr_row(evidence)
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
                "No V2 cycle journal PCR and no process_evidence row for "
                "step_name='check:pcr_informational' was found. The journal "
                "PCR appears once the paper monitor persists a cycle with a "
                "usable PCR context."
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
