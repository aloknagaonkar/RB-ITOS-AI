from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from red_bar_lab.services.red_bar_v2_cycle_evaluation_store import (
    read_red_bar_v2_cycle_evaluations,
)
from red_bar_lab.ui._shared import *  # noqa: F401,F403  (follows established ui/pages convention)

IST = ZoneInfo("Asia/Kolkata")
DATE_KEY = "v2_evaluation_monitor_date"
LIMIT_KEY = "v2_evaluation_monitor_limit"


def _parse(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=IST)
    return stamp.astimezone(IST)


def _fmt_time(value: object) -> str:
    stamp = _parse(value)
    return stamp.strftime("%H:%M:%S") if stamp else "—"


def _fmt_number(value: object, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _age_label(value: object) -> str:
    stamp = _parse(value)
    if stamp is None:
        return "unknown age"
    age = (datetime.now(IST) - stamp).total_seconds()
    if age < 90:
        return f"{age:.0f}s old"
    if age < 3600:
        return f"{age / 60:.1f}m old"
    return f"{age / 3600:.1f}h old"


def _status_color(status: str) -> str:
    text = str(status or "").upper()
    if text in {"READY", "PUBLISHED", "OPEN", "ALIGNED"}:
        return "🟢"
    if text in {"DEGRADED", "WAITING", "NO_SIGNAL", "SUSPENDED"}:
        return "🟡"
    if text in {"NOT_APPLICABLE", "UNAVAILABLE", ""}:
        return "⚪"
    return "🔴"


def _render_latest_cycle(row: dict[str, Any]) -> None:
    observed = _parse(row.get("observed_at"))
    cols = st.columns(5)
    cols[0].metric(
        "Cycle",
        f"{_status_color(row.get('cycle_status'))} {row.get('cycle_status') or '—'}",
    )
    cols[1].metric(
        "Context",
        f"{_status_color(row.get('context_status'))} {row.get('context_status') or '—'}",
    )
    cols[2].metric(
        "Publication",
        f"{_status_color(row.get('bridge_status'))} {row.get('bridge_status') or '—'}",
    )
    cols[3].metric(
        "Readiness",
        f"{_status_color(row.get('readiness_status'))} {row.get('readiness_status') or '—'}",
    )
    cols[4].metric("Observed", _fmt_time(observed), delta=_age_label(observed), delta_color="off")
    reasons = [
        text
        for text in (
            row.get("cycle_reason"),
            row.get("context_reason"),
            row.get("bridge_reason"),
            row.get("readiness_reason"),
        )
        if text
    ]
    if reasons:
        st.caption("Reasons: " + " · ".join(dict.fromkeys(reasons)))
    st.caption(f"Run `{row.get('run_id')}` · authority OBSERVATIONAL_ONLY")


def _render_data_collection(row: dict[str, Any]) -> None:
    st.markdown("#### 1 · Data collection")
    evidence = row.get("candle_evidence") or []
    if evidence:
        rows = []
        for item in evidence:
            rows.append(
                {
                    "Dataset": item.get("dataset"),
                    "Status": item.get("status"),
                    "Rows": item.get("row_count"),
                    "Pull ms": (
                        f"{float(item.get('duration_ms')):.0f}"
                        if item.get("duration_ms") is not None
                        else "—"
                    ),
                    "Latest candle": _fmt_time(item.get("latest_timestamp")),
                    "Expected completed": _fmt_time(
                        item.get("expected_completed_timestamp")
                    ),
                    "Freshness s": (
                        f"{float(item.get('freshness_seconds')):.0f}"
                        if item.get("freshness_seconds") is not None
                        else "—"
                    ),
                    "Missing intervals": item.get("missing_intervals"),
                    "Duplicates": item.get("duplicate_timestamps"),
                }
            )
        st.dataframe(
            _arrow_safe_rows(rows), width="stretch", hide_index=True
        )
    cols = st.columns(4)
    cols[0].metric("Index rows", row.get("index_rows") or 0)
    cols[1].metric("Futures rows", row.get("futures_rows") or 0)
    cols[2].metric("Aligned rows", row.get("aligned_rows") or 0)
    cols[3].metric(
        "Alignment coverage",
        _fmt_number(row.get("alignment_coverage_pct"), 1) + "%",
    )
    st.caption(
        f"Index latest: {_fmt_time(row.get('index_timestamp'))} · "
        f"Futures latest: {_fmt_time(row.get('futures_timestamp'))} · "
        f"Last aligned: {_fmt_time(row.get('last_aligned_timestamp'))}"
    )


def _render_strategy_values(row: dict[str, Any]) -> None:
    st.markdown("#### 2 · Strategy context values")
    cols = st.columns(6)
    cols[0].metric("Index close", _fmt_number(row.get("index_close")))
    cols[1].metric("Index RSI-14", _fmt_number(row.get("index_rsi")))
    cols[2].metric("Futures close", _fmt_number(row.get("futures_close")))
    cols[3].metric("Futures VWAP", _fmt_number(row.get("futures_vwap")))
    cols[4].metric("Price vs VWAP", row.get("price_vs_vwap") or "—")
    cols[5].metric("Reference midpoint", _fmt_number(row.get("reference_midpoint")))
    futures_close = row.get("futures_close")
    futures_vwap = row.get("futures_vwap")
    if futures_close is not None and futures_vwap is not None:
        delta = float(futures_close) - float(futures_vwap)
        st.caption(
            f"Futures close is {delta:+.2f} pts vs session VWAP "
            f"({row.get('price_vs_vwap') or 'n/a'})."
        )


def _render_candidates(row: dict[str, Any]) -> None:
    st.markdown("#### 3 · Candidates & admission")
    cols = st.columns(4)
    cols[0].metric("Candidate events scanned", row.get("candidate_events_scanned") or 0)
    cols[1].metric("Admitted candidates", row.get("admitted_candidates") or 0)
    cols[2].metric("Direction", row.get("admission_direction") or "—")
    cols[3].metric("Admission code", row.get("admission_code") or "—")
    if row.get("admission_reason"):
        st.caption(f"Admission reason: {row['admission_reason']}")
    elif not row.get("admitted_candidates"):
        st.caption(
            "No admitted candidate this cycle — the strategy saw no setup that "
            "passed all gating checks."
        )


def _render_rule_state(row: dict[str, Any]) -> None:
    st.markdown("#### 4 · Strategy rule state (every evaluation)")
    state = row.get("rule_state") or {}
    if not state:
        st.caption(
            "Rule state is not available for this cycle. Journal rows written "
            "before the per-rule summary was introduced do not carry it."
        )
        return

    reference = state.get("reference") or {}
    initial = state.get("initial") or {}
    reversal = state.get("reversal") or {}
    mid_session = state.get("mid_session") or {}
    upgrade = state.get("upgrade") or {}
    reentry = state.get("reentry") or {}
    admission = state.get("admission") or {}

    direction = state.get("current_direction")
    side = "CE" if direction == "BULLISH" else "PE" if direction == "BEARISH" else "—"
    cols = st.columns(5)
    cols[0].metric(
        "Current direction", f"{direction} ({side})" if direction else "FLAT"
    )
    cols[1].metric(
        "Rule 0 · Red bar",
        _fmt_time(reference.get("timestamp"))
        if reference.get("established")
        else "NOT SET",
    )
    cols[2].metric("Midpoint", _fmt_number(reference.get("midpoint")))
    cols[3].metric(
        "Ref high / low",
        f"{_fmt_number(reference.get('high'))} / {_fmt_number(reference.get('low'))}",
    )
    cols[4].metric("Evaluated as of", _fmt_time(state.get("as_of")))

    initial_status = str(initial.get("status") or "UNKNOWN")
    initial_detail = []
    if initial.get("direction"):
        initial_detail.append(f"direction {initial.get('direction')}")
    if initial.get("established_at"):
        initial_detail.append(f"established {_fmt_time(initial.get('established_at'))}")
    if initial.get("admitted") is True:
        initial_detail.append("first candidate admitted")
    elif initial.get("admitted") is False:
        initial_detail.append("first candidate BLOCKED")
    initial_detail.append(f"{int(initial.get('evaluations') or 0)} evaluations")
    if initial.get("last_evaluated_at"):
        initial_detail.append(
            f"last {_fmt_time(initial.get('last_evaluated_at'))} → "
            f"{initial.get('last_result') or '—'}"
        )

    reversal_detail = [
        f"5m evaluations {int(reversal.get('five_minute_evaluations') or 0)}",
        f"detections {int(reversal.get('detections') or 0)}",
    ]
    if reversal.get("last_detected_at"):
        aligned = (
            "confirmed" if reversal.get("last_midpoint_aligned") else "provisional"
        )
        reversal_detail.append(
            f"last {reversal.get('last_direction') or '—'} at "
            f"{_fmt_time(reversal.get('last_detected_at'))} ({aligned})"
        )
    if reversal.get("pending"):
        reversal_detail.append("PENDING")

    if mid_session.get("active"):
        mid_status = (
            "PASSED" if mid_session.get("passed") else "BLOCKING"
        )
        mid_detail = [mid_session.get("reason") or "—"]
        if mid_session.get("evaluated_at"):
            mid_detail.append(f"checked {_fmt_time(mid_session.get('evaluated_at'))}")
        blocked_count = int(mid_session.get("blocked_count") or 0)
        if blocked_count:
            mid_detail.append(f"{blocked_count} blocked alignment(s)")
    else:
        mid_status = "INACTIVE"
        mid_detail = ["Outside the 12:45–13:15 IST window (or not yet evaluated)."]

    upgrade_detail = [f"upgrades {int(upgrade.get('upgrades') or 0)}"]
    if upgrade.get("last_upgrade_at"):
        upgrade_detail.append(
            f"last {_fmt_time(upgrade.get('last_upgrade_at'))} "
            f"({upgrade.get('last_direction') or '—'})"
        )

    reentry_detail = [
        f"validated {int(reentry.get('validated') or 0)}",
        f"failed {int(reentry.get('failed') or 0)}",
    ]
    if reentry.get("last_outcome"):
        reentry_detail.append(
            f"last {reentry.get('last_outcome')} at "
            f"{_fmt_time(reentry.get('last_outcome_at'))}"
        )

    admission_detail = [
        f"admitted {int(admission.get('admitted') or 0)}",
        f"blocked {int(admission.get('blocked') or 0)}",
        f"active trades {int(admission.get('active_trade_count') or 0)}",
        f"trade state {admission.get('trade_state') or '—'}",
    ]
    if admission.get("last_admitted_at"):
        admission_detail.append(
            f"last admitted {_fmt_time(admission.get('last_admitted_at'))} "
            f"({admission.get('last_admission_code') or '—'})"
        )

    status_icon = {
        "ESTABLISHED": "🟢",
        "SCANNING": "🟡",
        "REFERENCE_PENDING": "⚪",
    }
    reentry_status = (
        f"WAITING ({reentry.get('touch_state') or 'touch'})"
        if reentry.get("waiting")
        else "NOT WAITING"
    )
    table_rows = [
        {
            "Rule": "1 · Initial entry (1m)",
            "Status": f"{status_icon.get(initial_status, '⚪')} {initial_status}",
            "Detail": " · ".join(initial_detail) or "—",
        },
        {
            "Rule": "2 · Reversal (5m)",
            "Status": (
                "🟢 MONITORING" if reversal.get("monitoring") else "⚪ IDLE"
            ),
            "Detail": " · ".join(reversal_detail) or "—",
        },
        {
            "Rule": "3 · Mid-session 12:45",
            "Status": (
                "🟢 PASSED"
                if mid_status == "PASSED"
                else "🔴 BLOCKING"
                if mid_status == "BLOCKING"
                else "⚪ INACTIVE"
            ),
            "Detail": " · ".join(mid_detail) or "—",
        },
        {
            "Rule": "4 · State upgrade",
            "Status": (
                f"🟡 {upgrade.get('provisional_state')}"
                if upgrade.get("provisional_state")
                else "⚪ NO PROVISIONAL STATE"
            ),
            "Detail": " · ".join(upgrade_detail) or "—",
        },
        {
            "Rule": "5 · Re-entry gate",
            "Status": (
                "🟡 " + reentry_status if reentry.get("waiting") else "⚪ " + reentry_status
            ),
            "Detail": " · ".join(reentry_detail) or "—",
        },
        {
            "Rule": "6 · Admission",
            "Status": (
                "🟢 TRADE ACTIVE"
                if int(admission.get("active_trade_count") or 0) > 0
                else "🟢 ADMITTING"
                if int(admission.get("admitted") or 0) > 0
                else "🟡 NO ADMISSION YET"
            ),
            "Detail": " · ".join(admission_detail) or "—",
        },
    ]
    st.dataframe(_arrow_safe_rows(table_rows), width="stretch", hide_index=True)

    if initial.get("last_reason"):
        st.caption(f"Last initial-evaluation result: {initial.get('last_reason')}")
    if admission.get("last_block_code"):
        st.caption(
            f"Last blocked candidate: {admission.get('last_block_code')} at "
            f"{_fmt_time(admission.get('last_block_at'))} — "
            f"{admission.get('last_block_reason') or 'no reason recorded'}"
        )


def _render_publication_readiness(row: dict[str, Any]) -> None:
    st.markdown("#### 5 · Publication & global readiness")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("##### Signal publication bridge")
        st.write(
            f"{_status_color(row.get('bridge_status'))} **{row.get('bridge_status') or '—'}**"
        )
        st.caption(row.get("bridge_reason") or "No bridge reason recorded.")
    with cols[1]:
        st.markdown("##### Global readiness")
        st.write(
            f"{_status_color(row.get('readiness_status'))} **{row.get('readiness_status') or '—'}**"
        )
        st.caption(row.get("readiness_reason") or "No readiness reason recorded.")
    blocking = row.get("blocking_reasons") or []
    advisory = row.get("advisory_reasons") or []
    execution = row.get("execution_reasons") or []
    if blocking:
        st.error("Blocking: " + ", ".join(blocking))
    if advisory:
        st.warning("Advisory: " + ", ".join(advisory))
    if execution:
        st.info("Execution policy: " + ", ".join(execution))


def _render_stage_timings(row: dict[str, Any]) -> None:
    timings = row.get("cycle_timings") or {}
    if not timings:
        return
    st.markdown("#### 6 · Cycle stage timings (ms)")
    rows = [
        {"Stage": str(stage), "Milliseconds": f"{float(value):,.0f}"}
        for stage, value in sorted(timings.items())
    ]
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)


def _render_timeline(rows: list[dict[str, Any]]) -> None:
    st.markdown("### Cycle timeline (newest first)")
    status_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("cycle_status") or "UNKNOWN")
        status_counts[key] = status_counts.get(key, 0) + 1
    summary = ", ".join(
        f"{status}: {count}" for status, count in sorted(status_counts.items())
    )
    st.caption(f"{len(rows)} cycles recorded today — {summary}")
    timeline_rows = []
    for row in rows:
        blocking = row.get("blocking_reasons") or []
        timeline_rows.append(
            {
                "IST time": _fmt_time(row.get("observed_at")),
                "Cycle": f"{_status_color(row.get('cycle_status'))} {row.get('cycle_status')}",
                "Cycle reason": row.get("cycle_reason") or "",
                "Candidates": row.get("candidate_events_scanned") or 0,
                "Admitted": row.get("admitted_candidates") or 0,
                "Direction": row.get("admission_direction") or "—",
                "Bridge": f"{_status_color(row.get('bridge_status'))} {row.get('bridge_status')}",
                "Bridge reason": row.get("bridge_reason") or "",
                "Readiness": (
                    f"{_status_color(row.get('readiness_status'))} "
                    f"{row.get('readiness_status')}"
                ),
                "Blocking": ", ".join(blocking) or "",
            }
        )
    st.dataframe(
        _arrow_safe_rows(timeline_rows), width="stretch", hide_index=True, height=420
    )


def render_page(
    settings: Any,
    layout: Any,
    database: Any,
    token: str,
    underlying_name: str,
    instrument_key: str,
    interval: int,
) -> None:
    st.title("V2 Evaluation Monitor")
    st.info(
        "OBSERVATIONAL ONLY — this page reads the per-cycle evaluation journal "
        "written by the paper monitor. It never influences gates, signals, or "
        "paper orders."
    )
    cols = st.columns([1, 1, 1])
    with cols[0]:
        selected = st.date_input(
            "Trading date", value=date.today(), key=DATE_KEY
        )
    with cols[1]:
        limit = int(st.number_input("Max cycles", 50, 3000, 600, 50, key=LIMIT_KEY))
    with cols[2]:
        st.metric("Underlying", underlying_name)

    rows = read_red_bar_v2_cycle_evaluations(
        settings.database_path,
        trading_date=selected.isoformat(),
        underlying_name=underlying_name,
        limit=limit,
    )
    if not rows:
        st.info(
            "No cycle evaluations are recorded for this date yet. One journal "
            "row is written per paper-monitor cycle (every ~15 seconds) while "
            "the monitor is running."
        )
        return

    latest = rows[0]
    _render_latest_cycle(latest)
    st.markdown("---")
    _render_data_collection(latest)
    _render_strategy_values(latest)
    _render_candidates(latest)
    _render_rule_state(latest)
    _render_publication_readiness(latest)
    _render_stage_timings(latest)
    st.markdown("---")
    _render_timeline(rows)
