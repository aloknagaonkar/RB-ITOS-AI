from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import os
import html

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.live_service import RedBarLiveService
from red_bar_lab.intelligence.service import RedBarIntelligenceDatasetService
from red_bar_lab.intelligence.shadow import ShadowIntelligenceEngine
from red_bar_lab.intelligence.validation import ShadowValidationService
from red_bar_lab.intelligence.candidate_inspection import inspect_candidate
from red_bar_lab.intelligence.institutional_flow import InstitutionalFlowService
from red_bar_lab.features.store import RedBarFeatureStore
from red_bar_lab.options.service import RedBarOptionsContextService
from red_bar_lab.collector.service import RedBarDualMarketCollector, market_clock_mode
from red_bar_lab.pipeline.orchestrator import RedBarIntelligencePipelineOrchestrator
from red_bar_lab.backfill.historical_options import RedBarHistoricalOptionsBackfillService
from red_bar_lab.operations.service import RedBarOperationsCenterService
from red_bar_lab.context.service import RedBarMarketContextService
from red_bar_lab.context.volume_structure_service import RedBarVolumeStructureService
from red_bar_lab.services.bulk_backtest_service import BulkHistoricalBacktestService
from red_bar_lab.services.historical_decision_replay import HistoricalDecisionReplayService
from red_bar_lab.services.historical_option_sync import HistoricalOptionChainSyncService
from red_bar_lab.services.replay_diagnostics import ReplayDiagnosticsService
from red_bar_lab.services.replay_accuracy import ReplayAccuracyService
from red_bar_lab.brokers.zerodha_client import ZerodhaKiteClient, ZerodhaAPIError
from red_bar_lab.execution.paper_engine import RedBarPaperExecutionEngine, PaperContract
from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.providers import ZerodhaLiveExecutionProvider
from red_bar_lab.market.upstox_intelligence import UnifiedUpstoxMarketIntelligenceService
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.services.upstox_service import (
    MissingAccessToken,
    RedBarUpstoxService,
    resolve_access_token,
)
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.strategy.level_engine import build_daily_levels
from red_bar_lab.strategy.signal_engine import scan_reference_levels
from red_bar_lab.strategy.trade_engine import evaluate_active_signals
from red_bar_lab.strategy.signal_view import (
    sequence_signal_attempts,
    summarize_completed_signals,
)
from red_bar_lab.strategy.trade_outcome import (
    actionable_trade_rows,
    benchmark_trade_rows,
    summarize_actionable_models,
    benchmark_summary,
    decorate_trade_row,
    summarize_signal_trade_models,
)


@st.cache_resource(show_spinner=False)
def _cached_database(database_path: str) -> RedBarDatabase:
    """Reuse the lightweight database facade across Streamlit reruns."""
    database = RedBarDatabase(database_path)
    database.initialize()
    return database


@st.cache_resource(show_spinner=False)
def _cached_paper_market_stack(
    access_token: str,
    underlying_name: str,
    instrument_key: str,
):
    """Keep Upstox clients and their in-memory caches alive across reruns."""
    provider = RedBarUpstoxService(access_token)
    intelligence = UnifiedUpstoxMarketIntelligenceService(
        provider,
        cache_ttl_seconds=10.0,
    )
    market = UpstoxPaperMarketAdapter(
        intelligence,
        underlying_name,
        instrument_key,
    )
    return provider, intelligence, market


def _historical_service(token: str, layout: ArtifactLayout) -> RedBarHistoricalService:
    return RedBarHistoricalService(
        RedBarUpstoxService(resolve_access_token(token)), layout
    )


def _build_and_store_levels(
    database: RedBarDatabase,
    historical: RedBarHistoricalService,
    instrument_key: str,
    selected_date: date,
    dates: tuple[date, ...],
) -> int:
    from red_bar_lab.services.ui_business_logic import build_and_store_levels
    return build_and_store_levels(
        database, historical, instrument_key, selected_date, dates
    )



def _arrow_safe_value(value):
    """Normalize UI values so Streamlit/PyArrow sees stable column types."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (list, tuple, dict, set)):
        return str(value)
    return str(value)


def _arrow_safe_rows(rows):
    if rows is None:
        return []
    safe = []
    for row in rows:
        if hasattr(row, "items"):
            safe.append({
                str(key): _arrow_safe_value(value)
                for key, value in row.items()
            })
        else:
            safe.append({"value": _arrow_safe_value(row)})
    return safe




def _arrow_safe_dataframe(data):
    """Return a DataFrame whose columns can be serialized consistently by PyArrow."""
    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    else:
        frame = pd.DataFrame(data)

    for column in frame.columns:
        series = frame[column]

        if pd.api.types.is_datetime64_any_dtype(series):
            frame[column] = series.map(
                lambda value: value.isoformat()
                if value is not None and not pd.isna(value)
                else None
            )
            continue

        if not (
            pd.api.types.is_object_dtype(series)
            or pd.api.types.is_string_dtype(series)
        ):
            continue

        non_null = [
            value for value in series.tolist()
            if value is not None and not (
                isinstance(value, float) and pd.isna(value)
            )
        ]
        type_names = {type(value).__name__ for value in non_null}
        has_complex = any(
            isinstance(value, (bytes, bytearray, list, tuple, dict, set))
            for value in non_null
        )

        if len(type_names) > 1 or has_complex:
            def as_text(value):
                if value is None:
                    return None
                if isinstance(value, float) and pd.isna(value):
                    return None
                if isinstance(value, (bytes, bytearray)):
                    try:
                        return bytes(value).decode("utf-8")
                    except Exception:
                        return repr(bytes(value))
                if isinstance(value, dict):
                    return str({
                        str(key): _arrow_safe_value(item)
                        for key, item in value.items()
                    })
                if isinstance(value, (list, tuple, set)):
                    return str([_arrow_safe_value(item) for item in value])
                return str(value)

            frame[column] = series.map(as_text)

    return frame


def _st_dataframe_arrow_safe(data, **kwargs):
    """Render a dataframe after Arrow compatibility normalization."""
    return st.dataframe(_arrow_safe_dataframe(data), **kwargs)

def _trade_display_rows(rows):
    """Small, readable trade table with outcome columns first."""
    display = []
    for source in rows:
        row = decorate_trade_row(source)
        display.append({
            "trade_id": row.get("trade_id"),
            "signal_id": row.get("signal_id"),
            "level_type": row.get("level_type"),
            "direction": row.get("direction"),
            "state": row.get("status"),
            "trade_result": row.get("trade_result"),
            "successful_failed": row.get("trade_success"),
            "points_gained": row.get("points_gained"),
            "exit_reason": row.get("exit_reason"),
            "exit_model": row.get("exit_model"),
            "model_parameter": row.get("model_parameter"),
            "entry_time": row.get("entry_timestamp"),
            "entry_price": row.get("entry_price"),
            "exit_time": row.get("exit_timestamp"),
            "exit_price": row.get("exit_price"),
            "risk_points": row.get("risk_points"),
            "r_multiple": row.get("r_multiple"),
            "mfe": row.get("mfe"),
            "mae": row.get("mae"),
            "session_mfe": row.get("session_mfe_points"),
            "move_after_target": row.get("move_after_target_points"),
            "holding_minutes": row.get("holding_minutes"),
        })
    return _arrow_safe_rows(display)


INDIA_TZ = ZoneInfo("Asia/Kolkata")


def _is_session_complete(trading_date: date) -> bool:
    from red_bar_lab.services.ui_business_logic import is_session_complete
    return is_session_complete(trading_date)


def _filter_backtest_rows(
    rows,
    *,
    signal_type,
    direction,
    exit_model,
    trade_result,
    signal_quality="ALL",
    min_success_score=0,
):
    from red_bar_lab.services.ui_business_logic import filter_backtest_rows
    return filter_backtest_rows(
        rows, signal_type=signal_type, direction=direction,
        exit_model=exit_model, trade_result=trade_result,
        signal_quality=signal_quality, min_success_score=min_success_score,
    )


def _filtered_backtest_summary(rows):
    from red_bar_lab.services.ui_business_logic import filtered_backtest_summary
    return filtered_backtest_summary(rows)


def _format_ist_time(value):
    from red_bar_lab.services.ui_business_logic import format_ist_time
    return format_ist_time(value)


def _round_points(value):
    from red_bar_lab.services.ui_business_logic import round_points
    return round_points(value)


def _trade_timeline_rows(rows):
    if not rows:
        return []
    timeline = [{
        "time_ist": _format_ist_time(rows[0].get("entry_timestamp")),
        "event": "ENTRY",
        "model": "SIGNAL",
        "price": rows[0].get("entry_price"),
        "points": 0.0,
        "status": "ACTIVE",
    }]
    for row in sorted(
        rows,
        key=lambda r: (
            str(r.get("exit_timestamp") or "9999"),
            str(r.get("exit_model") or ""),
            str(r.get("model_parameter") or ""),
        ),
    ):
        if row.get("exit_timestamp") is None:
            continue
        timeline.append({
            "time_ist": _format_ist_time(row.get("exit_timestamp")),
            "event": str(row.get("exit_reason") or "EXIT"),
            "model": (
                f"{row.get('exit_model')} "
                f"{row.get('model_parameter') or ''}"
            ).strip(),
            "price": row.get("exit_price"),
            "points": _round_points(row.get("points")),
            "status": row.get("status"),
        })
    return timeline


def _actionable_completion_exit(trade_rows):
    from red_bar_lab.services.ui_business_logic import actionable_completion_exit
    return actionable_completion_exit(trade_rows)


def _current_dashboard_rows(
    database,
    instrument_key,
    trading_date,
    active_attempts,
    completed_attempts,
):
    from red_bar_lab.services.ui_business_logic import current_dashboard_rows
    return current_dashboard_rows(
        database, instrument_key, trading_date,
        active_attempts, completed_attempts,
    )


def _decision_badge_html(value: object, tone: str = "info") -> str:
    palette = {
        "pass": ("#dcfce7", "#166534", "#86efac"),
        "buy": ("#dcfce7", "#166534", "#86efac"),
        "neutral": ("#fef9c3", "#854d0e", "#fde047"),
        "warning": ("#ffedd5", "#9a3412", "#fdba74"),
        "fail": ("#fee2e2", "#991b1b", "#fca5a5"),
        "portfolio": ("#f3e8ff", "#6b21a8", "#d8b4fe"),
        "info": ("#dbeafe", "#1e40af", "#93c5fd"),
        "shadow": ("#f3f4f6", "#374151", "#d1d5db"),
    }
    bg, fg, border = palette.get(tone, palette["info"])
    safe = html.escape(str(value))
    return (
        f'<span style="display:inline-block;padding:3px 8px;'
        f'border-radius:999px;background:{bg};color:{fg};'
        f'border:1px solid {border};font-weight:700;font-size:0.82rem;">'
        f'{safe}</span>'
    )


def _tone_for_value(value: object, *, portfolio: bool = False) -> str:
    text = str(value or "").upper()
    if portfolio and any(
        word in text for word in ("REVERSE", "CONFLICT", "HEDGE")
    ):
        return "portfolio"
    if any(word in text for word in ("FAIL", "REJECT", "STALE", "LOSS")):
        return "fail"
    if any(word in text for word in ("WARNING", "WEAK")):
        return "warning"
    if any(
        word in text
        for word in ("PASS", "BUY CE", "BUY PE", "BULLISH", "BEARISH", "EXECUTED")
    ):
        return "pass"
    if any(word in text for word in ("WAIT", "NEUTRAL", "MIXED", "RANGE", "PENDING")):
        return "neutral"
    return "info"


def _render_colored_decision_rows(rows: list[dict[str, object]]) -> None:
    pieces = [
        '<div style="border:1px solid #e5e7eb;border-radius:10px;'
        'overflow:hidden;margin-bottom:8px;">'
    ]
    for index, row in enumerate(rows):
        module = html.escape(str(row.get("Module") or ""))
        value = row.get("Value")
        tone = str(row.get("Tone") or _tone_for_value(value))
        reason = html.escape(str(row.get("Reason") or ""))
        bg = "#fafafa" if index % 2 == 0 else "#ffffff"
        pieces.append(
            f'<div style="display:grid;grid-template-columns:42% 58%;'
            f'gap:8px;padding:8px 10px;background:{bg};'
            f'border-bottom:1px solid #f1f5f9;">'
            f'<div><strong>{module}</strong>'
            + (f'<div style="font-size:0.72rem;color:#64748b;">{reason}</div>' if reason else "")
            + '</div>'
            f'<div>{_decision_badge_html(value, tone)}</div>'
            f'</div>'
        )
    pieces.append("</div>")
    st.markdown("".join(pieces), unsafe_allow_html=True)



def _confidence_tone(confidence: object) -> str:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "info"
    if value >= 80:
        return "pass"
    if value >= 60:
        return "neutral"
    if value >= 40:
        return "warning"
    return "fail"


def _render_shadow_intelligence_rows(
    rows: list[dict[str, object]],
) -> None:
    pieces = [
        '<div style="border:1px solid #e5e7eb;border-radius:10px;'
        'overflow:hidden;margin-bottom:8px;">'
    ]
    for index, row in enumerate(rows):
        module = html.escape(str(row.get("Module") or ""))
        status = str(row.get("Status") or "NEUTRAL")
        direction = str(row.get("Direction") or "NEUTRAL")
        confidence = row.get("Confidence", 0)
        recommendation = str(row.get("Recommendation") or "WAIT")
        reason = html.escape(str(row.get("Reason") or ""))
        status_tone = _tone_for_value(
            status,
            portfolio=(module == "Portfolio"),
        )
        direction_tone = _tone_for_value(
            direction,
            portfolio=(module == "Portfolio"),
        )
        recommendation_tone = _tone_for_value(
            recommendation,
            portfolio=(module == "Portfolio"),
        )
        confidence_tone = _confidence_tone(confidence)
        bg = "#fafafa" if index % 2 == 0 else "#ffffff"
        badges = " ".join(
            [
                _decision_badge_html(status, status_tone),
                _decision_badge_html(direction, direction_tone),
                _decision_badge_html(
                    f"{float(confidence):.0f}%"
                    if confidence is not None else "N/A",
                    confidence_tone,
                ),
                _decision_badge_html(
                    recommendation,
                    recommendation_tone,
                ),
            ]
        )
        pieces.append(
            f'<div style="padding:8px 10px;background:{bg};'
            f'border-bottom:1px solid #f1f5f9;">'
            f'<div style="font-weight:700;margin-bottom:5px;">{module}</div>'
            f'<div style="display:flex;gap:4px;flex-wrap:wrap;">{badges}</div>'
            + (
                f'<div style="font-size:0.72rem;color:#64748b;'
                f'margin-top:4px;">{reason}</div>'
                if reason else ""
            )
            + '</div>'
        )
    pieces.append("</div>")
    st.markdown("".join(pieces), unsafe_allow_html=True)




@st.fragment
def _render_candidate_workbench_fragment(
    ranked_rows,
    ranked_contracts,
    paper_engine,
    paper_market,
    today_text: str,
    paper_data_ready: bool,
    ranked_at,
    database,
    intelligence_snapshot,
    latest_signal,
    latest_direction: str,
    market_open: bool,
    auto_min_score: float,
    open_orders,
) -> None:
    """Candidate analysis surface.

    Rank selection changes ALL analysis panels in this fragment:
    Candidate Workbench, Current Rule Engine analysis, and Shadow
    Intelligence. Candidate rank is discovery order; RB-1.4.1 execution authority comes from the Primary Decision Engine through the existing safety Committee; Shadow is informational-only.
    """
    st.markdown("#### Top Ranked Candidates")
    if not ranked_rows:
        st.info(
            "Refresh and rank candidates to populate the Top-5 workbench."
        )
        return

    execution_candidate = ranked_rows[0]
    execution_symbol = str(execution_candidate.get("Option") or "")

    st.caption(
        "RULE-BASED PAPER RECOMMENDATION — not an AI recommendation. "
        "Rank is discovery order only. Every candidate is independently evaluated for automatic paper execution. "
        "Select Rank #1–#5 to analyse its rule score, intelligence and execution evidence."
    )
    # RB-0.9.5: committee-first dashboard with transparent soft scoring. Ranking remains discovery order,
    # while execution authority comes from the latest persisted committee run.
    current_signal_id_for_dashboard = str(latest_signal.get("signal_id") or "") if latest_signal else ""
    committee_rows = []
    if current_signal_id_for_dashboard:
        try:
            all_committee_rows = database.read_institutional_execution_evaluations(
                signal_id=current_signal_id_for_dashboard,
                limit=50,
            )
            if all_committee_rows:
                newest_committee_time = all_committee_rows[0].get("evaluated_at")
                committee_rows = [
                    row for row in all_committee_rows
                    if row.get("evaluated_at") == newest_committee_time
                ]
        except Exception:
            committee_rows = []

    committee_by_symbol = {
        str(row.get("candidate_symbol") or ""): row
        for row in committee_rows
    }

    st.markdown("### Execution Committee Dashboard")
    dashboard_rows = []
    for idx, row in enumerate(ranked_rows):
        symbol = str(row.get("Option") or "")
        committee = committee_by_symbol.get(symbol, {})
        decision = str(committee.get("decision") or "PENDING")
        dashboard_rows.append(
            {
                "Rank": int(row.get("Rank") or idx + 1),
                "Candidate": symbol,
                "Rule Score": round(float(row.get("Score") or 0.0), 2),
                "Primary %": committee.get("primary_confidence_pct") if committee.get("primary_confidence_pct") is not None else row.get("Score"),
                "Shadow": committee.get("shadow_decision"),
                "Shadow %": committee.get("shadow_confidence_pct"),
                "Agreement": committee.get("agreement"),
                "Shadow Adj": committee.get("shadow_adjustment_pct"),
                "Final Confidence %": committee.get("execution_probability_pct"),
                "Expectancy %": committee.get("expectancy_pct") if committee.get("expectancy_pct") is not None else committee.get("expected_value_pct"),
                "Expected Win %": committee.get("expected_win_pct"),
                "Expected Loss %": committee.get("expected_loss_pct"),
                "TSS": committee.get("selection_score"),
                "Opportunity": committee.get("opportunity_score"),
                "Historical": committee.get("historical_score"),
                "Committee Decision": decision,
                "Execution": "YES" if committee.get("eligible") else ("NO" if committee else "PENDING"),
                "Reason": committee.get("reason") or "Awaiting committee evaluation",
            }
        )
    st.dataframe(
        _arrow_safe_rows(dashboard_rows),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Rank is discovery order only. Candidate Lifecycle validity is checked before committee evaluation. Every active candidate is independently evaluated. "
        "The Rule Engine is PRIMARY. Shadow Intelligence is advisory: agreement adds confidence, "
        "conflict subtracts confidence. Final confidence + expectancy authorize execution when hard safety controls pass."
    )

    labels = []
    symbol_by_label = {}
    for idx, row in enumerate(ranked_rows):
        rank_no = int(row.get("Rank") or idx + 1)
        label = f"Rank #{rank_no}"
        labels.append(label)
        symbol_by_label[label] = str(row.get("Option") or "")

    stored_symbol = str(
        st.session_state.get(
            "paper_inspected_candidate_symbol",
            execution_symbol,
        )
    )
    default_index = next(
        (
            idx
            for idx, label in enumerate(labels)
            if symbol_by_label[label] == stored_symbol
        ),
        0,
    )

    selected_label = st.radio(
        "Inspect Candidate / Analyse Candidate",
        labels,
        index=default_index,
        horizontal=True,
        key="paper_candidate_radio",
        help=(
            "Changes the inspection view only. Automatic execution is decided independently by the execution committee."
        ),
    )
    selected_symbol = symbol_by_label[selected_label]
    st.session_state["paper_inspected_candidate_symbol"] = selected_symbol

    selected_row = next(
        (
            row for row in ranked_rows
            if str(row.get("Option") or "") == selected_symbol
        ),
        execution_candidate,
    )
    selected_rank = int(selected_row.get("Rank") or 1)
    inspection = inspect_candidate(selected_row, execution_candidate)

    # --------------------------------------------------------------
    # Candidate Workbench
    # --------------------------------------------------------------
    st.markdown("### Candidate Detail — Committee Inspection")
    entry = float(
        selected_row.get("Ask")
        or selected_row.get("LTP")
        or 0.0
    )
    stop = round(entry * 0.85, 2) if entry > 0 else None
    target1 = round(entry * 1.25, 2) if entry > 0 else None
    target2 = round(entry * 1.40, 2) if entry > 0 else None

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Selected", f"Rank #{selected_rank}")
    m2.metric("Contract", selected_symbol or "—")
    m3.metric("Rule Score", f"{inspection.score:.2f}/100")
    m4.metric("Candidate Health", f"{inspection.health_score:.1f}%")
    m5.metric("Health Band", inspection.health_band)

    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Entry Ref", f"₹{entry:.2f}" if entry else "—")
    p2.metric("Stop", f"₹{stop:.2f}" if stop is not None else "—")
    p3.metric("Target 1", f"₹{target1:.2f}" if target1 is not None else "—")
    p4.metric("Target 2", f"₹{target2:.2f}" if target2 is not None else "—")
    p5.metric("Decision", selected_row.get("Decision") or "—")

    selected_committee = committee_by_symbol.get(selected_symbol, {})
    st.markdown("#### Institutional Execution Committee — Candidate Detail")
    if selected_committee:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Primary Confidence", f"{float(selected_committee.get('primary_confidence_pct') or selected_committee.get('rule_quality_score') or 0.0):.1f}%")
        c2.metric("Shadow", str(selected_committee.get("shadow_decision") or "WAIT"))
        c3.metric("Agreement", str(selected_committee.get("agreement") or "—"))
        c4.metric("Shadow Adjustment", f"{float(selected_committee.get('shadow_adjustment_pct') or 0.0):+.1f} pts")
        c5.metric("Final Confidence", f"{float(selected_committee.get('execution_probability_pct') or 0.0):.1f}%")
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("Expectancy", f"{float(selected_committee.get('expectancy_pct') or selected_committee.get('expected_value_pct') or 0.0):+.2f}%")
        x2.metric("Expected Win", f"{float(selected_committee.get('expected_win_pct') or selected_committee.get('expected_reward_pct') or 0.0):.2f}%")
        x3.metric("Expected Loss", f"{float(selected_committee.get('expected_loss_pct') or selected_committee.get('expected_risk_pct') or 0.0):.2f}%")
        x4.metric("Committee", str(selected_committee.get("decision") or "—"))
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("TSS", f"{float(selected_committee.get('selection_score') or 0.0):.1f}")
        e2.metric("Historical", f"{float(selected_committee.get('historical_score') or 0.0):.1f}")
        e3.metric("Expectancy Confidence", f"{float(selected_committee.get('expectancy_confidence_pct') or 0.0):.1f}%")
        e4.metric("Half-Kelly (Research)", f"{float(selected_committee.get('kelly_fraction_pct') or 0.0):.1f}%")
        st.caption(f"Expectancy source: {selected_committee.get('expectancy_source') or 'legacy'} · " + str(selected_committee.get("reason") or ""))

        authority_rows = []
        for item in selected_committee.get("expert_votes") or []:
            authority_rows.append({
                "Layer": item.get("expert"),
                "Confidence / Score": item.get("score"),
                "Adjustment / Result": item.get("contribution"),
                "Authority": item.get("source"),
                "Explanation": item.get("detail"),
            })
        if authority_rows:
            st.markdown("##### Primary Decision + Shadow Information")
            st.dataframe(_arrow_safe_rows(authority_rows), width="stretch", hide_index=True)

        contribution_rows = []
        for item in selected_committee.get("modules") or []:
            contribution_rows.append({
                "Shadow Module": item.get("module"),
                "Recommendation": item.get("current_recommendation"),
                "Support": item.get("current_support"),
                "Confidence %": item.get("current_confidence"),
                "Reliability": item.get("reliability_score"),
                "Historical Samples": item.get("supportive_samples"),
                "Historical Win Rate %": item.get("win_rate_pct"),
            })
        if contribution_rows:
            st.markdown("##### Shadow Intelligence Detail (Advisory Only)")
            st.dataframe(_arrow_safe_rows(contribution_rows), width="stretch", hide_index=True)
            st.caption("Individual shadow modules explain the advisor decision; they do not directly dilute the Primary Rule Engine score.")
    else:
        st.info("Committee evaluation is pending for this candidate. Ranking itself does not authorize execution.")

    # --------------------------------------------------------------
    # Why Rank #N differs from Rank #1
    # --------------------------------------------------------------
    st.markdown(
        "### Why Rank #1?"
        if selected_rank == 1
        else f"### Why Rank #{selected_rank} vs Rank #1?"
    )

    components = [
        ("Rule Score", "Score", None),
        ("Spread", "Spread Score", 15.0),
        ("Liquidity", "Liquidity", 20.0),
        ("Volume", "Volume Score", 15.0),
        ("Open Interest", "OI Score", 10.0),
        ("VWAP", "VWAP Score", 10.0),
        ("EMA", "EMA Score", 10.0),
        ("Momentum", "Momentum", 10.0),
        ("Momentum %", "Momentum %", None),
        ("Delta", "Delta", None),
        ("Gamma", "Gamma", None),
        ("IV", "IV", None),
        ("Theta", "Theta", None),
        ("Vega", "Vega", None),
    ]
    difference_rows = []
    for label, key, maximum in components:
        best_value = execution_candidate.get(key)
        selected_value = selected_row.get(key)
        difference = None
        try:
            difference = float(selected_value) - float(best_value)
        except (TypeError, ValueError):
            pass

        explanation = "SAME"
        if selected_rank == 1:
            explanation = "RANK #1"
        elif difference is not None:
            if abs(difference) < 0.000001:
                explanation = "SAME"
            elif difference > 0:
                explanation = "SELECTED BETTER"
            else:
                explanation = "RANK #1 BETTER"

        difference_rows.append(
            {
                "Metric": label,
                "Rank #1": best_value,
                f"Rank #{selected_rank}": selected_value,
                "Difference": (
                    round(difference, 4)
                    if difference is not None else None
                ),
                "Advantage": explanation,
            }
        )

    st.dataframe(
        _arrow_safe_rows(difference_rows),
        width="stretch",
        hide_index=True,
    )

    if selected_rank != 1:
        score_gap = float(execution_candidate.get("Score") or 0.0) - float(
            selected_row.get("Score") or 0.0
        )
        better = []
        weaker = []
        for label, key, _ in components[1:8]:
            try:
                delta = float(selected_row.get(key) or 0.0) - float(
                    execution_candidate.get(key) or 0.0
                )
            except (TypeError, ValueError):
                continue
            if delta > 0:
                better.append(f"{label} +{delta:.1f}")
            elif delta < 0:
                weaker.append(f"{label} {delta:.1f}")

        st.info(
            f"Rank #{selected_rank} is {score_gap:.2f} rule-score points "
            f"behind Rank #1."
        )
        if better:
            st.success(
                "Where selected candidate is stronger: "
                + ", ".join(better)
            )
        if weaker:
            st.warning(
                "Where Rank #1 has the advantage: "
                + ", ".join(weaker)
            )

    # Full score breakdown + Greeks.
    st.markdown("#### Candidate Score & Contribution Breakdown")
    st.dataframe(
        _arrow_safe_rows(list(inspection.score_breakdown)),
        width="stretch",
        hide_index=True,
    )

    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Delta", selected_row.get("Delta") or "—")
    g2.metric("Gamma", selected_row.get("Gamma") or "—")
    g3.metric("IV", selected_row.get("IV") or "—")
    g4.metric("Theta", selected_row.get("Theta") or "—")
    g5.metric("Vega", selected_row.get("Vega") or "—")
    st.caption(
        "Greeks are shown for analysis and Shadow Intelligence. "
        "They feed persisted intelligence evidence; RB-0.9.2 can use their historically validated reliability in the final execution committee."
    )

    # --------------------------------------------------------------
    # Both analysis engines now follow selected candidate.
    # --------------------------------------------------------------

    st.markdown("### Discovery Leader / Candidate Detail")
    execution_col, inspection_col = st.columns(2)

    with execution_col:
        st.markdown("#### Execution Candidate")
        st.markdown(
            _decision_badge_html(
                "RANK #1 · DISCOVERY LEADER",
                "pass",
            ),
            unsafe_allow_html=True,
        )
        ex1, ex2, ex3 = st.columns(3)
        ex1.metric(
            "Contract",
            execution_candidate.get("Option") or "—",
        )
        ex2.metric(
            "Score",
            f"{float(execution_candidate.get('Score') or 0):.1f}",
        )
        ex3.metric(
            "Decision",
            execution_candidate.get("Decision") or "—",
        )

    with inspection_col:
        st.markdown("#### Candidate Detail")
        st.markdown(
            _decision_badge_html(
                (
                    "RANK #1 · DISCOVERY LEADER"
                    if selected_rank == 1
                    else f"RANK #{selected_rank} · INDEPENDENT CANDIDATE"
                ),
                "pass" if selected_rank == 1 else "info",
            ),
            unsafe_allow_html=True,
        )
        in1, in2, in3 = st.columns(3)
        in1.metric("Contract", selected_symbol or "—")
        in2.metric("Score", f"{inspection.score:.1f}")
        in3.metric(
            "Execution Path",
            "COMMITTEE EVALUATION",
        )

        if selected_rank != 1:
            selected_score = float(selected_row.get("Score") or 0.0)
            rank1_score = float(
                execution_candidate.get("Score") or 0.0
            )
            st.caption(
                f"Difference vs Rank #1: "
                f"{selected_score - rank1_score:+.2f} points"
            )

    with st.expander("Compare Two Candidates", expanded=False):
        compare_labels = [
            (
                f"Rank #{int(row.get('Rank') or idx + 1)} · "
                f"{row.get('Option')}"
            )
            for idx, row in enumerate(ranked_rows)
        ]

        left_compare, right_compare = st.columns(2)
        with left_compare:
            compare_a = st.selectbox(
                "Candidate A",
                compare_labels,
                index=0,
                key="candidate_compare_a",
            )
        with right_compare:
            compare_b = st.selectbox(
                "Candidate B",
                compare_labels,
                index=1 if len(compare_labels) > 1 else 0,
                key="candidate_compare_b",
            )

        row_a = ranked_rows[compare_labels.index(compare_a)]
        row_b = ranked_rows[compare_labels.index(compare_b)]

        compare_metrics = [
            ("Rule Score", "Score"),
            ("Spread", "Spread Score"),
            ("Liquidity", "Liquidity"),
            ("Volume", "Volume Score"),
            ("Open Interest", "OI Score"),
            ("VWAP", "VWAP Score"),
            ("EMA", "EMA Score"),
            ("Momentum", "Momentum"),
            ("Momentum %", "Momentum %"),
            ("Delta", "Delta"),
            ("Gamma", "Gamma"),
            ("IV", "IV"),
            ("Theta", "Theta"),
            ("Vega", "Vega"),
        ]

        rows = []
        for metric, key in compare_metrics:
            a_value = row_a.get(key)
            b_value = row_b.get(key)
            difference = None
            advantage = "INFO"
            try:
                a_num = float(a_value)
                b_num = float(b_value)
                difference = a_num - b_num
                if abs(difference) < 0.000001:
                    advantage = "TIE"
                elif difference > 0:
                    advantage = "A"
                else:
                    advantage = "B"
            except (TypeError, ValueError):
                pass

            rows.append(
                {
                    "Metric": metric,
                    "Candidate A": a_value,
                    "Candidate B": b_value,
                    "A - B": (
                        round(difference, 4)
                        if difference is not None
                        else None
                    ),
                    "Advantage": advantage,
                }
            )

        st.dataframe(
            _arrow_safe_rows(rows),
            width="stretch",
            hide_index=True,
        )

        score_a = float(row_a.get("Score") or 0.0)
        score_b = float(row_b.get("Score") or 0.0)
        if score_a > score_b:
            winner = str(row_a.get("Option") or "Candidate A")
        elif score_b > score_a:
            winner = str(row_b.get("Option") or "Candidate B")
        else:
            winner = "TIE"

        st.success(
            f"Rule-score winner: {winner}. "
            "Comparison is analysis-only and cannot change execution."
        )


    st.markdown("### Decision Engine Comparison")
    st.caption(
        "Both panels analyse the SAME selected Rank. "
        "Rank is discovery order only; each candidate is independently evaluated by Performance Selection and the Institutional Execution Committee."
    )

    current_signal_id = (
        str(latest_signal.get("signal_id"))
        if latest_signal else ""
    )
    signal_age_seconds = None
    if latest_signal and latest_signal.get("confirmation_timestamp"):
        try:
            signal_ts = pd.Timestamp(
                latest_signal.get("confirmation_timestamp")
            )
            if signal_ts.tzinfo is None:
                signal_ts = signal_ts.tz_localize("Asia/Kolkata")
            else:
                signal_ts = signal_ts.tz_convert("Asia/Kolkata")
            signal_age_seconds = (
                pd.Timestamp(datetime.now(ZoneInfo("Asia/Kolkata")))
                - signal_ts
            ).total_seconds()
        except Exception:
            signal_age_seconds = None

    duplicate_free = True
    if current_signal_id:
        duplicate_free = not database.paper_execution_exists_for_signal(
            signal_id=current_signal_id,
            account_id="PAPER-STD",
        )

    selected_trade_side = (
        "BUY CE"
        if selected_row.get("Type") == "CE"
        else "BUY PE"
        if selected_row.get("Type") == "PE"
        else "WAIT"
    )
    selected_score = float(selected_row.get("Score") or 0.0)
    selected_score_pass = selected_score >= float(auto_min_score)
    selected_quote_ok = float(
        selected_row.get("Ask")
        or selected_row.get("LTP")
        or 0.0
    ) > 0
    freshness_pass = bool(
        signal_age_seconds is not None
        and 0 <= signal_age_seconds <= 180
    )
    selected_would_be_ready = bool(
        latest_signal
        and market_open
        and duplicate_free
        and selected_score_pass
        and selected_quote_ok
    )
    selected_rule_decision = (
        selected_trade_side if selected_would_be_ready else "WAIT"
    )

    left, right = st.columns(2)

    with left:
        st.markdown("#### RULE EVIDENCE — CANDIDATE DETAIL")
        st.markdown(
            _decision_badge_html(
                f"ANALYSING RANK #{selected_rank}",
                "pass" if selected_rank == 1 else "info",
            ),
            unsafe_allow_html=True,
        )
        rule_rows = [
            {
                "Module": "Candidate",
                "Value": selected_symbol,
                "Tone": "info",
                "Reason": f"Rank #{selected_rank}",
            },
            {
                "Module": "Discovery Leader",
                "Value": execution_symbol,
                "Tone": "info",
                "Reason": "Rank #1 is discovery order only; committee approval controls execution",
            },
            {
                "Module": "Red Bar Confirmed",
                "Value": "PASS" if latest_signal else "FAIL",
            },
            {
                "Module": "Market Hours",
                "Value": "PASS" if market_open else "FAIL",
            },
            {
                "Module": "Signal Age (Informational)",
                "Value": "FRESH" if freshness_pass else "OLDER",
                "Tone": "info",
                "Reason": (
                    f"{signal_age_seconds:.0f}s; RB-1.5.0 does not block on age alone"
                    if signal_age_seconds is not None
                    else "Age unavailable"
                ),
            },
            {
                "Module": "Duplicate Check",
                "Value": "PASS" if duplicate_free else "FAIL",
            },
            {
                "Module": "Direction Mapping",
                "Value": f"{latest_direction} → {selected_row.get('Type')}",
                "Tone": "info",
            },
            {
                "Module": "Spread Score",
                "Value": f"{float(selected_row.get('Spread Score') or 0):.1f}/15",
                "Tone": "pass" if float(selected_row.get("Spread Score") or 0) >= 12 else "warning",
            },
            {
                "Module": "Liquidity Score",
                "Value": f"{float(selected_row.get('Liquidity') or 0):.1f}/20",
                "Tone": "pass" if float(selected_row.get("Liquidity") or 0) >= 15 else "warning",
            },
            {
                "Module": "Volume Score",
                "Value": f"{float(selected_row.get('Volume Score') or 0):.1f}/15",
                "Tone": "pass" if float(selected_row.get("Volume Score") or 0) >= 10 else "warning",
            },
            {
                "Module": "OI Score",
                "Value": f"{float(selected_row.get('OI Score') or 0):.1f}/10",
                "Tone": "pass" if float(selected_row.get("OI Score") or 0) >= 7 else "warning",
            },
            {
                "Module": "VWAP Score",
                "Value": f"{float(selected_row.get('VWAP Score') or 0):.1f}/10",
                "Tone": "pass" if float(selected_row.get("VWAP Score") or 0) > 0 else "warning",
            },
            {
                "Module": "EMA Score",
                "Value": f"{float(selected_row.get('EMA Score') or 0):.1f}/10",
                "Tone": "pass" if float(selected_row.get("EMA Score") or 0) > 0 else "warning",
            },
            {
                "Module": "Momentum",
                "Value": f"{float(selected_row.get('Momentum') or 0):.1f}/10",
                "Tone": "pass" if float(selected_row.get("Momentum") or 0) >= 6 else "warning",
            },
            {
                "Module": "Candidate Score",
                "Value": (
                    f"PASS · {selected_score:.1f}/100"
                    if selected_score_pass
                    else f"FAIL · {selected_score:.1f}/100"
                ),
                "Reason": f"Minimum {float(auto_min_score):.1f}",
            },
            {
                "Module": "Rule Evidence Decision",
                "Value": selected_rule_decision,
                "Tone": "buy" if selected_rule_decision.startswith("BUY") else "neutral",
            },
            {
                "Module": "Execution Impact",
                "Value": "COMMITTEE CONTROLLED",
                "Tone": "info",
                "Reason": "Rank does not grant execution authority; this candidate must independently clear committee gates",
            },
        ]
        _render_colored_decision_rows(rule_rows)

    shadow_decision = None
    shadow_features = {}
    if current_signal_id:
        try:
            shadow_features = RedBarFeatureStore(
                database
            ).get_features(current_signal_id)
        except Exception:
            shadow_features = {}

    if intelligence_snapshot:
        try:
            shadow_engine = ShadowIntelligenceEngine()
            shadow_decision = shadow_engine.evaluate(
                current_decision=selected_rule_decision,
                direction=latest_direction,
                spot_price=intelligence_snapshot.spot_price,
                pcr_oi=intelligence_snapshot.pcr_oi,
                call_wall=intelligence_snapshot.call_wall,
                put_wall=intelligence_snapshot.put_wall,
                max_pain=intelligence_snapshot.max_pain,
                chain_rows=intelligence_snapshot.chain,
                best_candidate=selected_row,
                market_features=shadow_features,
                open_orders=open_orders,
            )
            # Preserve historical validation integrity: only Rank #1 shadow
            # evaluation is persisted as execution-engine evidence.
            if current_signal_id and selected_rank == 1:
                database.insert_shadow_intelligence_evaluation(
                    {
                        "signal_id": current_signal_id,
                        "trading_date": today_text,
                        **shadow_decision.as_dict(),
                    }
                )
        except Exception as exc:
            st.warning(
                f"Selected-candidate Shadow Intelligence unavailable: {exc}"
            )

    with right:
        st.markdown("#### INTELLIGENCE EVIDENCE — CANDIDATE DETAIL")
        st.markdown(
            _decision_badge_html(
                f"RANK #{selected_rank} · SHADOW ANALYSIS",
                "shadow",
            ),
            unsafe_allow_html=True,
        )
        if shadow_decision:
            shadow_rows = [
                {
                    "Module": item.module,
                    "Status": item.status,
                    "Direction": item.direction,
                    "Confidence": item.confidence,
                    "Recommendation": item.recommendation,
                    "Reason": item.reason,
                }
                for item in shadow_decision.modules
            ]
            _render_shadow_intelligence_rows(shadow_rows)
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Shadow Decision", shadow_decision.shadow_decision)
            s2.metric(
                "Shadow Confidence",
                f"{shadow_decision.shadow_confidence:.1f}%",
            )
            s3.metric("Agreement", shadow_decision.agreement)
            s4.metric("Portfolio Action", shadow_decision.portfolio_action)
            st.info(
                "Candidate-level Shadow analysis only. "
                "Execution Impact = NONE."
            )
        else:
            st.caption("No Shadow analysis is available for this candidate.")

    if shadow_decision:
        st.markdown("#### Candidate Agreement")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Candidate Rank", f"#{selected_rank}")
        a2.metric("Rule Engine", selected_rule_decision)
        a3.metric("Shadow Engine", shadow_decision.shadow_decision)
        a4.metric("Agreement", shadow_decision.agreement)

    st.caption(
        f"Candidate ranking snapshot: {ranked_at or '—'}"
    )




def _render_paper_exit_engine_panel(
    *,
    position: dict[str, object],
    paper_engine,
    paper_market,
    database,
    intelligence_snapshot,
    instrument_key: str,
    today_text: str,
) -> None:
    """Render the CE/PE Paper Exit Engine for one open position."""
    if not position:
        return

    order_id = str(position.get("order_id") or "")
    signal_id = str(position.get("signal_id") or "")
    signal = (
        database.read_signal_attempt_by_id(signal_id)
        if signal_id else None
    )

    # Latest NIFTY/underlying spot from the shared Upstox snapshot.
    current_underlying = None
    if intelligence_snapshot is not None:
        try:
            if intelligence_snapshot.spot_price is not None:
                current_underlying = float(
                    intelligence_snapshot.spot_price
                )
        except Exception:
            current_underlying = None

    # Detect a confirmed opposite Red Bar after entry.
    opposite_confirmed = False
    try:
        original_direction = str(
            (signal or {}).get("direction") or ""
        ).upper()
        opposite_direction = (
            "BULLISH" if original_direction == "BEARISH"
            else "BEARISH" if original_direction == "BULLISH"
            else ""
        )
        entry_timestamp = str(
            position.get("entry_timestamp") or ""
        )
        if opposite_direction:
            today_signals = database.read_signal_attempts(
                instrument_key,
                today_text,
            )
            opposite_confirmed = any(
                str(row.get("direction") or "").upper()
                == opposite_direction
                and bool(row.get("confirmation_timestamp"))
                and str(row.get("confirmation_timestamp") or "")
                > entry_timestamp
                for row in today_signals
            )
    except Exception:
        opposite_confirmed = False

    # Actual selected option candle state.
    option_candle = None
    candle_frame = None
    try:
        if paper_market is not None:
            candle_frame = paper_engine.option_candles(
                zerodha=paper_market,
                instrument_token=int(position["instrument_token"]),
                date_from=today_text,
                date_to=today_text,
                interval="minute",
            )
            if candle_frame is not None and not candle_frame.empty:
                last = candle_frame.iloc[-1]
                close = float(
                    last.get("close")
                    or position.get("current_price")
                    or position.get("entry_price")
                    or 0.0
                )
                lookback = min(
                    5,
                    max(1, len(candle_frame) - 1),
                )
                momentum_pct = 0.0
                if len(candle_frame) >= 2:
                    previous = float(
                        candle_frame.iloc[
                            -1 - lookback
                        ].get("close")
                        or close
                    )
                    if previous:
                        momentum_pct = (
                            (close - previous)
                            / previous
                            * 100.0
                        )

                volume_series = pd.to_numeric(
                    candle_frame["volume"],
                    errors="coerce",
                ).fillna(0.0)
                average_volume = (
                    float(volume_series.tail(20).mean())
                    if len(volume_series) else 0.0
                )
                current_volume = float(
                    last.get("volume") or 0.0
                )
                relative_volume = (
                    current_volume / average_volume
                    if average_volume > 0 else None
                )
                option_candle = {
                    "close": close,
                    "vwap": float(last.get("vwap") or close),
                    "ema9": float(last.get("ema9") or close),
                    "ema21": float(last.get("ema21") or close),
                    "momentum_pct": momentum_pct,
                    "relative_volume": relative_volume,
                }
    except Exception:
        option_candle = None

    # OI/PCR/Greeks remain advisory Shadow Exit evidence.
    pcr_supportive = None
    oi_supportive = None
    greeks_supportive = None
    option_type = str(
        position.get("option_type") or ""
    ).upper()

    if intelligence_snapshot is not None:
        try:
            pcr = float(intelligence_snapshot.pcr_oi)
            if option_type == "CE":
                pcr_supportive = pcr >= 1.10
            elif option_type == "PE":
                pcr_supportive = pcr <= 0.90
        except Exception:
            pcr_supportive = None

        try:
            chain = intelligence_snapshot.chain
            strike = float(position.get("strike") or 0.0)
            match = chain[
                pd.to_numeric(
                    chain["strike"],
                    errors="coerce",
                ) == strike
            ]
            if not match.empty:
                chain_row = match.iloc[0]
                call_change = float(
                    chain_row.get("call_oi_change") or 0.0
                )
                put_change = float(
                    chain_row.get("put_oi_change") or 0.0
                )
                if option_type == "CE":
                    oi_supportive = put_change >= call_change
                elif option_type == "PE":
                    oi_supportive = call_change >= put_change
        except Exception:
            oi_supportive = None

    try:
        if paper_market is not None:
            key = (
                f"{position.get('exchange')}:"
                f"{position.get('tradingsymbol')}"
            )
            quote = paper_market.quote([key]).get(key) or {}
            delta = abs(float(quote.get("delta") or 0.0))
            gamma = float(quote.get("gamma") or 0.0)
            iv = float(quote.get("iv") or 0.0)
            if delta or gamma or iv:
                greeks_supportive = (
                    0.30 <= delta <= 0.70
                    and gamma > 0
                    and 5.0 <= iv <= 60.0
                )
    except Exception:
        greeks_supportive = None

    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    exit_health = PaperExitEngine().evaluate(
        position=position,
        option_candle=option_candle,
        signal=signal,
        current_underlying=current_underlying,
        opposite_red_bar_confirmed=opposite_confirmed,
        pcr_supportive=pcr_supportive,
        oi_supportive=oi_supportive,
        greeks_supportive=greeks_supportive,
        eod_due=now_ist.time() >= time(15, 25),
    )

    st.markdown("### Paper Exit Engine")
    st.caption(
        "Operational exit authority: premium protection, completed NIFTY "
        "5-minute EMA10 trend exit, EOD, NIFTY thesis, opposite Red Bar "
        "and option technical health. Fixed profit targets are informational "
        "only and have no exit authority. PCR/OI/Greeks remain SHADOW EXIT "
        "evidence only."
    )

    entry = float(position.get("entry_price") or 0.0)
    current = float(position.get("current_price") or entry)
    quantity = int(position.get("quantity") or 0)
    pnl = float(position.get("unrealized_pnl") or 0.0)

    try:
        entry_time = datetime.fromisoformat(
            str(position.get("entry_timestamp"))
        )
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(
                tzinfo=ZoneInfo("Asia/Kolkata")
            )
        holding_seconds = max(
            0,
            int(
                (
                    datetime.now(ZoneInfo("Asia/Kolkata"))
                    - entry_time
                ).total_seconds()
            ),
        )
        holding_text = (
            f"{holding_seconds // 60}m "
            f"{holding_seconds % 60}s"
        )
    except Exception:
        holding_text = "—"

    # Friendly action wording for the operator.
    action_display = {
        "HOLD": "HOLD",
        "HOLD / PROTECT": "PROTECT PROFIT",
        "HOLD / TRAIL": "HOLD / TRAIL",
        "TIGHTEN": "TIGHTEN STOP",
        "EXIT": "EXIT NOW",
    }.get(exit_health.action, exit_health.action)

    action_tone = (
        "fail"
        if exit_health.action == "EXIT"
        else "warning"
        if exit_health.action in {
            "TIGHTEN",
            "HOLD / PROTECT",
        }
        else "pass"
    )

    exit_pressure = max(
        0.0,
        min(100.0, 100.0 - exit_health.health_score),
    )

    # Operational/additional confirmations are shown together, but only
    # hard_exit_reason has actual exit authority.
    confirmations = []
    if exit_health.nifty_thesis == "INVALID":
        confirmations.append("NIFTY thesis invalidated")
    if exit_health.opposite_red_bar == "YES":
        confirmations.append("Opposite Red Bar confirmed")
    if exit_health.option_vwap == "FAIL":
        confirmations.append("Option below VWAP")
    if exit_health.option_ema == "FAIL":
        confirmations.append("EMA9 below EMA21")
    if exit_health.option_momentum == "FAIL":
        confirmations.append("Momentum negative")
    if exit_health.volume_health == "WEAK":
        confirmations.append("Volume weakening")

    if exit_health.hard_exit_reason:
        combined_exit_reason = " + ".join(
            dict.fromkeys(
                [exit_health.hard_exit_reason]
                + [
                    item.upper().replace(" ", "_")
                    for item in confirmations
                ]
            )
        )
    else:
        combined_exit_reason = "NONE"

    # ==============================================================
    # Three-column exit workstation
    # ==============================================================
    left, middle, right = st.columns(3)

    with left:
        st.markdown("#### POSITION & PROTECTION")
        st.metric(
            "Position",
            position.get("tradingsymbol") or "—",
        )

        p1, p2 = st.columns(2)
        p1.metric("Entry", f"₹{entry:.2f}")
        p2.metric("Current", f"₹{current:.2f}")

        p3, p4 = st.columns(2)
        p3.metric("Peak", f"₹{exit_health.peak_price:.2f}")
        p4.metric(
            "P&L",
            f"₹{pnl:+,.2f}",
            delta=f"{exit_health.pnl_pct:+.2f}%",
        )
        st.caption(
            f"Quantity {quantity} · Holding {holding_text}"
        )

        def _protection_row(
            label: str,
            value: str,
            state: str,
            tone: str,
        ) -> None:
            cols = st.columns([1.4, 1.2, 1.0])
            cols[0].markdown(f"**{label}**")
            cols[1].markdown(value)
            cols[2].markdown(
                _decision_badge_html(state, tone),
                unsafe_allow_html=True,
            )

        _protection_row(
            "Initial SL",
            (
                f"₹{exit_health.initial_stop:.2f}"
                if exit_health.initial_stop is not None
                else "—"
            ),
            "ACTIVE",
            "pass",
        )

        _protection_row(
            "Breakeven",
            (
                f"₹{exit_health.breakeven_price:.2f}"
                if exit_health.breakeven_price is not None
                else "—"
            ),
            "ARMED" if exit_health.breakeven_armed else "WAIT",
            "pass" if exit_health.breakeven_armed else "warning",
        )

        _protection_row(
            "Trailing Stop",
            (
                f"₹{exit_health.trailing_stop:.2f}"
                if exit_health.trailing_stop is not None
                else "—"
            ),
            "ACTIVE" if exit_health.trailing_active else "WAIT",
            "pass" if exit_health.trailing_active else "info",
        )

        _protection_row(
            "Effective Stop",
            (
                f"₹{exit_health.effective_stop:.2f}"
                if exit_health.effective_stop is not None
                else "—"
            ),
            "ACTIVE",
            "pass",
        )

        ema10_value = (
            (
                f"5m Close {exit_health.underlying_5m_close:.2f} · "
                f"EMA10 {exit_health.underlying_ema10:.2f}"
            )
            if (
                exit_health.underlying_5m_close is not None
                and exit_health.underlying_ema10 is not None
            )
            else "Awaiting completed 5m EMA10 data"
        )
        ema10_state = str(exit_health.ema10_trend or "UNKNOWN").upper()
        ema10_tone = (
            "fail"
            if ema10_state == "LOST"
            else "pass"
            if ema10_state == "VALID"
            else "info"
        )
        _protection_row(
            "NIFTY 5m EMA10",
            ema10_value,
            ema10_state,
            ema10_tone,
        )

    with middle:
        st.markdown("#### EXIT HEALTH")

        def _health_row(
            label: str,
            state: str,
            authority: str,
        ) -> None:
            normalized = str(state or "UNKNOWN").upper()

            if label == "Opposite Red Bar":
                tone = "fail" if normalized == "YES" else "pass"
            elif normalized in {
                "VALID",
                "PASS",
                "HEALTHY",
                "SUPPORTIVE",
                "NO",
            }:
                tone = "pass"
            elif normalized in {
                "INVALID",
                "FAIL",
            }:
                tone = "fail"
            elif normalized in {
                "WEAK",
                "WARNING",
            }:
                tone = "warning"
            else:
                tone = "info"

            auth_tone = (
                "shadow"
                if authority == "SHADOW"
                else "warning"
                if authority == "ADVISORY"
                else "info"
            )

            cols = st.columns([1.4, 1.0, 1.0])
            cols[0].markdown(f"**{label}**")
            cols[1].markdown(
                _decision_badge_html(normalized, tone),
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                _decision_badge_html(authority, auth_tone),
                unsafe_allow_html=True,
            )

        _health_row(
            "NIFTY Thesis",
            exit_health.nifty_thesis,
            "OPERATIONAL",
        )
        _health_row(
            "5m EMA10 Trend",
            exit_health.ema10_trend,
            "OPERATIONAL",
        )
        _health_row(
            "Opposite Red Bar",
            exit_health.opposite_red_bar,
            "OPERATIONAL",
        )
        _health_row(
            "Option VWAP",
            exit_health.option_vwap,
            "OPERATIONAL",
        )
        _health_row(
            "Option EMA",
            exit_health.option_ema,
            "OPERATIONAL",
        )
        _health_row(
            "Momentum",
            exit_health.option_momentum,
            "OPERATIONAL",
        )
        _health_row(
            "Volume",
            exit_health.volume_health,
            "ADVISORY",
        )
        _health_row(
            "OI / PCR",
            exit_health.shadow_oi_pcr,
            "SHADOW",
        )
        _health_row(
            "Greeks",
            exit_health.shadow_greeks,
            "SHADOW",
        )

        st.metric(
            "Technical Failures",
            f"{exit_health.technical_failures}/3",
        )
        st.caption(
            "Hard/operational conditions can exit. "
            "Advisory and Shadow conditions cannot exit by themselves."
        )

    with right:
        st.markdown("#### EXIT DECISION")
        st.markdown(
            _decision_badge_html(
                action_display,
                action_tone,
            ),
            unsafe_allow_html=True,
        )

        d1, d2 = st.columns(2)
        d1.metric(
            "Trade Health",
            f"{exit_health.health_score:.0f}/100",
        )
        d2.metric(
            "Exit Pressure",
            f"{exit_pressure:.0f}/100",
        )

        st.progress(
            max(
                0.0,
                min(
                    1.0,
                    exit_health.health_score / 100.0,
                ),
            )
        )

        st.markdown("**Primary Reason**")
        st.markdown(
            _decision_badge_html(
                exit_health.hard_exit_reason or "NO HARD EXIT",
                "fail"
                if exit_health.hard_exit_reason
                else "pass",
            ),
            unsafe_allow_html=True,
        )

        if confirmations:
            st.markdown("**Additional Confirmation**")
            for item in confirmations:
                st.write(f"• {item}")
        else:
            st.caption(
                "No additional deterioration confirmations."
            )

        st.markdown("**Exit Reason Code**")
        st.code(combined_exit_reason)

        st.markdown("**Decision Reasons**")
        for reason in exit_health.reasons:
            st.write(f"• {reason}")

        st.markdown("**Next Trigger**")
        st.info(exit_health.next_trigger)

        if exit_health.action == "EXIT":
            st.error(
                "EXIT condition is active. The background paper monitor "
                "will close the virtual position on its next cycle."
            )
        elif exit_health.trailing_active:
            st.success(
                "Profit protection active: trailing stop is following "
                "the highest option premium."
            )
        elif exit_health.breakeven_armed:
            st.success(
                "Profit protection active: breakeven is armed."
            )
        elif exit_health.action == "TIGHTEN":
            st.warning(
                "Trade health is weakening. Protection should tighten."
            )
        else:
            st.success(
                "HOLD: no operational exit trigger is active."
            )

    # ==============================================================
    # Exit timeline / replay
    # ==============================================================
    with st.expander("Exit Timeline", expanded=False):
        events = (
            database.read_execution_state_events(
                signal_id=signal_id,
                limit=150,
            )
            if signal_id else []
        )

        timeline_states = {
            "OPEN",
            "BREAKEVEN_ARMED",
            "TRAILING_ACTIVATED",
            "TRAIL_UPDATED",
            "EXIT_MONITOR",
            "EXIT_TRIGGERED",
            "CLOSED",
        }

        timeline_events = [
            row
            for row in reversed(events)
            if str(row.get("state") or "") in timeline_states
            and (
                not order_id
                or not row.get("order_id")
                or str(row.get("order_id")) == order_id
            )
        ]

        if timeline_events:
            timeline_rows = []
            for row in timeline_events:
                state = str(row.get("state") or "")
                display_state = {
                    "OPEN": "ENTRY",
                    "BREAKEVEN_ARMED": "+15% · BREAKEVEN ARMED",
                    "TRAILING_ACTIVATED": "+20% · TRAILING ACTIVE",
                    "TRAIL_UPDATED": "TRAIL UPDATED",
                    "EXIT_MONITOR": "MONITOR",
                    "EXIT_TRIGGERED": "EXIT TRIGGERED",
                    "CLOSED": "EXIT / CLOSED",
                }.get(state, state)

                timestamp = row.get("timestamp")
                display_time = timestamp
                try:
                    parsed = pd.Timestamp(timestamp)
                    if parsed.tzinfo is None:
                        parsed = parsed.tz_localize("Asia/Kolkata")
                    else:
                        parsed = parsed.tz_convert("Asia/Kolkata")
                    display_time = parsed.strftime("%H:%M:%S")
                except Exception:
                    pass

                timeline_rows.append(
                    {
                        "Time": display_time,
                        "Event": display_state,
                        "Detail": row.get("detail"),
                    }
                )

            st.dataframe(
                _arrow_safe_rows(timeline_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption(
                "ENTRY, breakeven, trailing updates and final exit "
                "will appear here as the position evolves."
            )



def _render_paper_exit_engine_idle_panel() -> None:
    """Display the configured Paper Exit Engine while no trade is open."""
    st.markdown("### Paper Exit Engine — IDLE")
    st.info(
        "No open virtual paper position. The exit engine is READY and will "
        "switch automatically to live position management when a CE/PE "
        "paper trade opens."
    )

    left, middle, right = st.columns(3)

    with left:
        st.markdown("#### PROTECTION RULES")
        protection_rows = [
            {
                "Protection": "Initial Premium SL",
                "Trigger": "-15% from entry",
                "State": "READY",
            },
            {
                "Protection": "Breakeven",
                "Trigger": "+15% peak",
                "State": "READY",
            },
            {
                "Protection": "Trailing Activation",
                "Trigger": "+20% peak",
                "State": "READY",
            },
            {
                "Protection": "Trailing Distance",
                "Trigger": "10% below peak",
                "State": "READY",
            },
            {
                "Protection": "5m EMA10 Trend Exit",
                "Trigger": "Bullish: close < EMA10 · Bearish: close > EMA10",
                "State": "READY",
            },
        ]
        st.dataframe(
            _arrow_safe_rows(protection_rows),
            width="stretch",
            hide_index=True,
        )

    with middle:
        st.markdown("#### EXIT AUTHORITY")
        exit_rows = [
            {
                "Condition": "Hard / Effective Stop",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
            {
                "Condition": "5m EMA10 Trend Exit",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
            {
                "Condition": "15:25 EOD",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
            {
                "Condition": "NIFTY Thesis Invalidation",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
            {
                "Condition": "Opposite Red Bar",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
            {
                "Condition": "Option Technical Breakdown",
                "Authority": "OPERATIONAL",
                "State": "READY",
            },
        ]
        st.dataframe(
            _arrow_safe_rows(exit_rows),
            width="stretch",
            hide_index=True,
        )

    with right:
        st.markdown("#### SHADOW / ADVISORY")
        advisory_rows = [
            {
                "Evidence": "Volume Health",
                "Role": "ADVISORY",
                "Exit Authority": "NO",
            },
            {
                "Evidence": "OI / PCR",
                "Role": "SHADOW",
                "Exit Authority": "NO",
            },
            {
                "Evidence": "Greeks",
                "Role": "SHADOW",
                "Exit Authority": "NO",
            },
        ]
        st.dataframe(
            _arrow_safe_rows(advisory_rows),
            width="stretch",
            hide_index=True,
        )
        i1, i2, i3 = st.columns(3)
        i1.metric("Engine", "READY")
        i2.metric("Position", "NONE")
        i3.metric("Action", "WAIT")

    st.caption(
        "When an open paper position exists, this IDLE preview is replaced "
        "by the live Position & Protection / Exit Health / Exit Decision "
        "workstation and Exit Timeline."
    )



def _render_paper_monitor_status(database) -> None:
    """Read live paper-monitor state directly from SQLite.

    Intentionally NOT cached: the monitor updates heartbeat, P&L and order
    state every few seconds.
    """
    monitor_status = database.read_paper_monitor_status()
    monitor_online = False
    heartbeat_age = None

    if monitor_status and monitor_status.get("heartbeat_at"):
        try:
            heartbeat_ts = datetime.fromisoformat(
                str(monitor_status["heartbeat_at"])
            )
            if heartbeat_ts.tzinfo is None:
                heartbeat_ts = heartbeat_ts.replace(
                    tzinfo=ZoneInfo("Asia/Kolkata")
                )
            heartbeat_age = (
                datetime.now(ZoneInfo("Asia/Kolkata"))
                - heartbeat_ts
            ).total_seconds()
            monitor_online = heartbeat_age <= 20
        except Exception:
            heartbeat_age = None

    open_rows = database.read_open_paper_execution_orders("PAPER-STD")
    total_unrealized = sum(
        float(row.get("unrealized_pnl") or 0.0)
        for row in open_rows
    )

    st.markdown("### Paper Automation Status")
    mon_cols = st.columns(6)
    mon_cols[0].metric(
        "Background Monitor",
        "RUNNING" if monitor_online else "OFFLINE / STALE",
    )
    mon_cols[1].metric(
        "Heartbeat",
        (
            f"{heartbeat_age:.0f}s ago"
            if heartbeat_age is not None
            else "NO HEARTBEAT"
        ),
    )
    mon_cols[2].metric(
        "Current State",
        (
            monitor_status.get("current_state") or "UNKNOWN"
            if monitor_status else "NOT STARTED"
        ),
    )
    mon_cols[3].metric("Open Positions", len(open_rows))
    mon_cols[4].metric("Open P&L", f"₹{total_unrealized:+,.2f}")
    mon_cols[5].metric(
        "Last Decision",
        (
            monitor_status.get("last_decision") or "—"
            if monitor_status else "—"
        ),
    )

    if monitor_status:
        st.caption(
            f"Last scan: {monitor_status.get('last_scan_at') or '—'} · "
            f"Opened: {int(monitor_status.get('orders_opened') or 0)} · "
            f"Closed: {int(monitor_status.get('orders_closed') or 0)} · "
            f"Signal: {monitor_status.get('last_signal_id') or '—'} · "
            f"Reason: {monitor_status.get('last_reason') or '—'}"
        )
        if monitor_status.get("last_error"):
            st.warning(
                f"Monitor error: {monitor_status.get('last_error')}"
            )
    else:
        st.warning(
            "No paper-monitor heartbeat exists yet. Start the platform "
            "with start_red_bar_platform.ps1 or run "
            "run_paper_monitor.ps1 in a separate PowerShell window."
        )


@st.fragment(run_every="5s")
def _render_paper_live_status_fragment(database) -> None:
    """Refresh only live monitor/P&L status; never reload the full page."""
    _render_paper_monitor_status(database)


__all__ = [name for name in globals() if not name.startswith("__")]
