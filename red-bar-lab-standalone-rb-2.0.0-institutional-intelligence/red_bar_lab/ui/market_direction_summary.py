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
    _render_vwap_touch_journal(database_path)
    _render_pcr_best_trade_evaluation(database_path, underlying)
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


_VWAP_TOUCH_THRESHOLD_POINTS = 10.0
_VWAP_TOUCH_FORWARD_CANDLES = 15


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result == result and abs(result) != float("inf") else None


def _parse_ist_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    return parsed.astimezone(IST) if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)


def _futures_snapshot_days(database_path: str | Path) -> list[str]:
    try:
        with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                """SELECT DISTINCT substr(observed_at, 1, 10) AS day
                   FROM nifty_futures_diagnostic_snapshots
                   ORDER BY day DESC"""
            ).fetchall()
    except Exception:
        return []
    return [str(row[0]) for row in rows if row[0]]


def _read_futures_touch_candles(
    database_path: str | Path,
    trading_day: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the day's completed 1m candles plus session VWAP metadata.

    Picks the snapshot with the longest candle list among the newest rows of
    the day, so mid-day re-renders see the candles collected so far.
    """
    try:
        with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                """SELECT payload_json
                   FROM nifty_futures_diagnostic_snapshots
                   WHERE substr(observed_at, 1, 10) = ?
                   ORDER BY julianday(observed_at) DESC, observed_at DESC
                   LIMIT 6""",
                (trading_day,),
            ).fetchall()
    except Exception:
        return [], {}
    best: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            continue
        market = payload.get("market")
        market = market if isinstance(market, Mapping) else {}
        candles = market.get("completed_candles")
        candles = candles if isinstance(candles, list) else []
        if len(candles) > len(best):
            best = [c for c in candles if isinstance(c, Mapping)]
            meta = {
                "futures_vwap": _as_float(market.get("futures_vwap")),
                "futures_vwap_acceptance": market.get("futures_vwap_acceptance"),
                "futures_close_vs_vwap_points": _as_float(
                    market.get("futures_close_vs_vwap_points")
                ),
            }
    return best, meta


def _vwap_series(candles: list[Mapping[str, Any]]) -> list[float]:
    series: list[float] = []
    cum_tp_volume = cum_volume = 0.0
    for candle in candles:
        high = _as_float(candle.get("high"))
        low = _as_float(candle.get("low"))
        close = _as_float(candle.get("close"))
        volume = _as_float(candle.get("volume")) or 0.0
        if high is None or low is None or close is None:
            series.append(series[-1] if series else 0.0)
            continue
        typical = (high + low + close) / 3.0
        cum_tp_volume += typical * volume
        cum_volume += volume
        series.append(cum_tp_volume / cum_volume if cum_volume > 0 else typical)
    return series


def _vwap_touch_events(
    candles: list[Mapping[str, Any]],
    vwaps: list[float],
    *,
    threshold: float = _VWAP_TOUCH_THRESHOLD_POINTS,
    forward: int = _VWAP_TOUCH_FORWARD_CANDLES,
) -> list[dict[str, Any]]:
    """Detect returns to session VWAP after price moved at least `threshold` away."""
    events: list[dict[str, Any]] = []
    for index in range(6, len(candles)):
        previous_close = _as_float(candles[index - 1].get("close"))
        if previous_close is None:
            continue
        away = previous_close - vwaps[index - 1]
        if abs(away) < threshold:
            continue
        high = _as_float(candles[index].get("high"))
        low = _as_float(candles[index].get("low"))
        close = _as_float(candles[index].get("close"))
        vwap = vwaps[index]
        if high is None or low is None or close is None:
            continue
        if not low <= vwap <= high:
            continue
        approach = "DOWN" if away > 0 else "UP"
        if close > vwap:
            close_side = "ABOVE"
        elif close < vwap:
            close_side = "BELOW"
        else:
            close_side = "AT"
        window = candles[index + 1:index + 1 + forward]
        next_move = None
        accepted = None
        if window:
            last_close = _as_float(window[-1].get("close"))
            if last_close is not None:
                next_move = last_close - close
            if approach == "DOWN":
                far = [c for c in window if (_as_float(c.get("close")) or vwap) < vwap]
            else:
                far = [c for c in window if (_as_float(c.get("close")) or vwap) > vwap]
            accepted = len(far) >= max(1, int(0.6 * len(window)))
        events.append({
            "timestamp": str(candles[index].get("timestamp") or ""),
            "approach": approach,
            "vwap": vwap,
            "close": close,
            "close_side": close_side,
            "accepted": accepted,
            "next_move": next_move,
        })
    return events


def _touch_day_pcr_rows(
    repository: MarketTrendResearchRepository,
    *,
    underlying: str,
    trading_day: str,
) -> list[dict[str, Any]]:
    try:
        history = repository.five_minute_pcr_history(
            underlying=underlying,
            trading_date=date.fromisoformat(trading_day),
            limit=100,
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for row in reversed(history):
        if not isinstance(row, Mapping):
            continue
        ts = _parse_ist_timestamp(row.get("candle_close_timestamp"))
        overall = _as_float(row.get("overall_pcr"))
        if ts is None or overall is None:
            continue
        rows.append({
            "ts": ts,
            "overall": overall,
            "direction": str(row.get("research_direction") or ""),
        })
    for previous, current in zip(rows, rows[1:]):
        current["slope"] = current["overall"] - previous["overall"]
    if rows:
        rows[0]["slope"] = None
    return rows


def _touch_pcr_context(
    event_ts: datetime | None,
    pcr_rows: list[dict[str, Any]],
    *,
    max_age_seconds: float = 600.0,
) -> dict[str, Any] | None:
    if event_ts is None or not pcr_rows:
        return None
    latest = None
    for row in pcr_rows:
        if row["ts"] <= event_ts:
            latest = row
        else:
            break
    if latest is None:
        return None
    if (event_ts - latest["ts"]).total_seconds() > max_age_seconds:
        return None
    return latest


_PCR_BAND_BULLISH_MINIMUM = 1.25
_PCR_BAND_BEARISH_MAXIMUM = 0.7


def _pcr_evaluation_band(pcr: float | None) -> str:
    if pcr is None:
        return "UNAVAILABLE"
    if pcr >= _PCR_BAND_BULLISH_MINIMUM:
        return "BULLISH"
    if pcr < _PCR_BAND_BEARISH_MAXIMUM:
        return "BEARISH"
    return "NEUTRAL"


def _pcr_evaluation_alignment(band: str, side: object) -> str:
    side_text = str(side or "").upper()
    if side_text not in {"CE", "PE"}:
        return "UNAVAILABLE"
    if band == "BULLISH":
        return "ALIGNED" if side_text == "CE" else "COUNTER"
    if band == "BEARISH":
        return "ALIGNED" if side_text == "PE" else "COUNTER"
    if band == "NEUTRAL":
        return "NEUTRAL"
    return "UNAVAILABLE"


def _evaluation_points(entry: object, value: object) -> float | None:
    entry_float = _as_float(entry)
    value_float = _as_float(value)
    if entry_float is None or value_float is None:
        return None
    return value_float - entry_float


def _pcr_evaluation_trades(
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize recommendation rows into band-labelled trade outcomes."""
    trades: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pcr = _as_float(row.get("entry_overall_pcr"))
        band = _pcr_evaluation_band(pcr)
        side = str(row.get("side") or "").upper()
        strike = _as_float(row.get("strike"))
        trades.append({
            "opened_at": str(row.get("opened_at") or ""),
            "contract": (
                str(row.get("symbol"))
                if row.get("symbol")
                else f"{strike or 0:.0f} {side}"
            ),
            "side": side or "UNAVAILABLE",
            "entry_pcr": pcr,
            "band": band,
            "alignment": _pcr_evaluation_alignment(band, side),
            "entry_price": _as_float(row.get("entry_price")),
            "peak_points": _evaluation_points(
                row.get("entry_price"), row.get("peak_price")
            ),
            "last_points": _evaluation_points(
                row.get("entry_price"), row.get("current_price")
            ),
            "status": str(row.get("status") or "UNAVAILABLE"),
        })
    return trades


def _pcr_evaluation_alignment_summary(
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "ALIGNED": [],
        "COUNTER": [],
        "NEUTRAL": [],
    }
    for trade in trades:
        if trade.get("alignment") in groups:
            groups[trade["alignment"]].append(trade)
    summary: list[dict[str, Any]] = []
    for name in ("ALIGNED", "COUNTER", "NEUTRAL"):
        members = groups[name]
        finals = [t["last_points"] for t in members if t["last_points"] is not None]
        peaks = [t["peak_points"] for t in members if t["peak_points"] is not None]
        hits = sum(1 for value in finals if value > 0)
        summary.append({
            "Group": name,
            "Trades": len(members),
            "Hit rate": (
                f"{hits / len(finals) * 100.0:.0f}%" if finals else "Not available"
            ),
            "Avg peak pts": (
                f"{sum(peaks) / len(peaks):+.1f}" if peaks else "Not available"
            ),
            "Avg final pts": (
                f"{sum(finals) / len(finals):+.1f}" if finals else "Not available"
            ),
            "Best peak pts": f"{max(peaks):+.1f}" if peaks else "Not available",
        })
    return summary


def _pcr_evaluation_vwap_events(
    database_path: str | Path,
    days: list[str],
) -> list[dict[str, Any]]:
    """Collect VWAP touch events across every requested day with candle data."""
    available = set(_futures_snapshot_days(database_path))
    events: list[dict[str, Any]] = []
    for day in days:
        if day not in available:
            continue
        candles, _meta = _read_futures_touch_candles(database_path, day)
        if len(candles) < 20:
            continue
        events.extend(_vwap_touch_events(candles, _vwap_series(candles)))
    return events


def _render_vwap_touch_journal(database_path: str | Path) -> None:
    repository = MarketTrendResearchRepository(database_path)
    with st.expander("Futures VWAP × PCR touch journal", expanded=False):
        futures_days = _futures_snapshot_days(database_path)
        pcr_days = set()
        reader = getattr(repository, "five_minute_pcr_trading_days", None)
        if callable(reader):
            try:
                pcr_days = set(reader("NIFTY 50"))
            except Exception:
                pcr_days = set()
        days = [day for day in futures_days if day in pcr_days]
        if not days:
            st.info(
                "Waiting for a trading day that has both futures 1-minute "
                "candles and 5-minute PCR history."
            )
            return
        selected = st.selectbox(
            "Trading date",
            days,
            index=0,
            key="vwap_touch_journal_trading_date",
        )
        candles, meta = _read_futures_touch_candles(database_path, selected)
        if len(candles) < 20:
            st.info("Not enough completed futures candles for this day yet.")
            return
        vwaps = _vwap_series(candles)
        events = _vwap_touch_events(candles, vwaps)
        pcr_rows = _touch_day_pcr_rows(
            repository, underlying="NIFTY 50", trading_day=selected
        )
        rendered: list[dict[str, object]] = []
        for event in events:
            ts = _parse_ist_timestamp(event["timestamp"])
            context = _touch_pcr_context(ts, pcr_rows)
            slope = (context or {}).get("slope")
            rendered.append({
                "Time (IST)": ts.strftime("%H:%M") if ts else "Not available",
                "Approach": f"{event['approach']} to VWAP",
                "VWAP": f"{event['vwap']:.1f}",
                "Candle close": f"{event['close']:.1f}",
                "Closed": event["close_side"],
                "Outcome": (
                    "Not available" if event["accepted"] is None
                    else "ACCEPTED" if event["accepted"] else "REJECTED"
                ),
                "Next 15m move": (
                    "Not available" if event["next_move"] is None
                    else f"{event['next_move']:+.1f}"
                ),
                "PCR at touch": _number((context or {}).get("overall")),
                "PCR direction": str((context or {}).get("direction") or "Not available"),
                "PCR slope": (
                    "Not available" if slope is None else f"{slope:+.2f}"
                ),
            })
        if rendered:
            st.dataframe(
                _arrow_safe_rows(rendered), width="stretch", hide_index=True
            )
        else:
            st.info(
                f"No return-to-VWAP touches beyond "
                f"{_VWAP_TOUCH_THRESHOLD_POINTS:.0f} points were detected on "
                "this day."
            )
        last_close = _as_float(candles[-1].get("close"))
        session_vwap = vwaps[-1] if vwaps else None
        if last_close is not None and session_vwap:
            st.caption(
                f"Session summary: final close {last_close:.1f} vs VWAP "
                f"{session_vwap:.1f} ({last_close - session_vwap:+.1f} pts) · "
                f"system acceptance = "
                f"{meta.get('futures_vwap_acceptance') or 'UNAVAILABLE'}."
            )
        st.caption(
            "A touch is a candle that re-enters session VWAP after price was "
            f"{_VWAP_TOUCH_THRESHOLD_POINTS:.0f}+ points away; ACCEPTED means "
            f"≥60% of the next {_VWAP_TOUCH_FORWARD_CANDLES} closes held "
            "through VWAP. PCR columns join the nearest completed 5-minute "
            "PCR candle at or before the touch. Read-only; observational only."
        )


def _points_text(value: object) -> str:
    number = _as_float(value)
    return "Not available" if number is None else f"{number:+.1f}"


def _render_pcr_best_trade_evaluation(
    database_path: str | Path,
    underlying: str,
) -> None:
    repository = MarketTrendResearchRepository(database_path)
    with st.expander("PCR Best-Trade Evaluation", expanded=False):
        reader = getattr(
            repository, "strike_pcr_recommendation_trading_days", None
        )
        days: list[str] = []
        if callable(reader):
            try:
                days = [str(day) for day in reader(underlying)]
            except Exception:
                days = []
        if not days:
            st.info(
                "No persisted strike PCR recommendations yet. Trades appear "
                "here once the research layer opens a recommendation with a "
                "valid two-sided quote."
            )
            return
        selected = st.selectbox(
            "Trading date",
            ["All days", *days],
            index=0,
            key="pcr_best_trade_evaluation_trading_date",
        )
        chosen_days = days if selected == "All days" else [selected]
        trades: list[dict[str, Any]] = []
        for day in chosen_days:
            try:
                chosen = date.fromisoformat(day)
            except ValueError:
                continue
            trades.extend(
                _pcr_evaluation_trades(
                    repository.strike_pcr_recommendations(
                        underlying=underlying, trading_date=chosen
                    )
                )
            )
        if not trades:
            st.info("No recommendation rows exist for the selected day(s).")
            return
        st.markdown("#### Best trades per PCR band")
        ranked = sorted(
            trades,
            key=lambda trade: (
                trade["peak_points"]
                if trade["peak_points"] is not None
                else float("-inf")
            ),
            reverse=True,
        )
        table: list[dict[str, object]] = []
        for trade in ranked:
            ts = _parse_ist_timestamp(trade["opened_at"])
            row: dict[str, object] = {}
            if len(chosen_days) > 1:
                row["Date"] = (
                    ts.astimezone(IST).date().isoformat() if ts else "Not available"
                )
            row.update({
                "Time (IST)": ts.strftime("%H:%M") if ts else "Not available",
                "Contract": trade["contract"],
                "Side": trade["side"],
                "Entry PCR": _number(trade["entry_pcr"]),
                "PCR band": trade["band"],
                "Alignment": trade["alignment"],
                "Entry": _number(trade["entry_price"], 2),
                "Peak pts": _points_text(trade["peak_points"]),
                "Final pts": _points_text(trade["last_points"]),
                "State": trade["status"],
            })
            table.append(row)
        st.dataframe(_arrow_safe_rows(table), width="stretch", hide_index=True)
        st.markdown("#### Band alignment — the standout statistic")
        st.dataframe(
            _arrow_safe_rows(_pcr_evaluation_alignment_summary(trades)),
            width="stretch",
            hide_index=True,
        )
        st.markdown("#### VWAP behavior — what happened after candles reached VWAP")
        events = _pcr_evaluation_vwap_events(database_path, chosen_days)
        if events:
            decided = [event for event in events if event["accepted"] is not None]
            accepted = [event for event in decided if event["accepted"]]
            moves = [
                event["next_move"] for event in events
                if event["next_move"] is not None
            ]
            st.dataframe(
                _arrow_safe_rows([{
                    "Touches": len(events),
                    "Accepted": (
                        f"{len(accepted)}/{len(decided)}"
                        if decided else "Not available"
                    ),
                    "Acceptance rate": (
                        f"{len(accepted) / len(decided) * 100.0:.0f}%"
                        if decided else "Not available"
                    ),
                    "Avg next 15m move": (
                        f"{sum(moves) / len(moves):+.1f} pts"
                        if moves else "Not available"
                    ),
                    "Best next 15m move": (
                        f"{max(moves):+.1f} pts" if moves else "Not available"
                    ),
                    "Worst next 15m move": (
                        f"{min(moves):+.1f} pts" if moves else "Not available"
                    ),
                }]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No futures VWAP touches (10+ points away) are persisted for "
                "the selected day(s)."
            )
        st.caption(
            "PCR bands: ≥1.25 BULLISH, <0.7 BEARISH, 0.7–1.25 NEUTRAL. "
            "ALIGNED means the band agreed with the bought side (BULLISH+CE or "
            "BEARISH+PE); COUNTER means the opposite. Peak/Final pts subtract "
            "the frozen entry ask from the peak/latest bid. The touch-by-touch "
            "detail lives in the Futures VWAP × PCR touch journal above. "
            "Read-only; observational only — no trading authority."
        )


def render_market_direction_summary(
    database_path: str | Path,
    *,
    underlying: str,
) -> None:
    _render_summary_cycle(database_path, underlying)


__all__ = ["render_market_direction_summary"]
