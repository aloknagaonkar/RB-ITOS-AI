"""The Red Bar V2 entry ladder: one candidate's walk down 21 checkpoints.

Observational only. Every number on this page is read back from what the
strategy already recorded -- the page runs no gate and writes no row.

The screen answers one question per candidate: how far down the entry path did
it get, and which checkpoint stopped it. A checkpoint the candidate never
reached says so rather than showing a verdict, because a boolean recorded for a
gate that was never consulted is stale data, not a decision.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from red_bar_lab.services.red_bar_v2_entry_ladder_catalog import (
    ADMISSION_PHASE,
    ORDER_PATH_PHASE,
)
from red_bar_lab.services.red_bar_v2_entry_ladder_view import (
    STATE_FAIL,
    STATE_NOT_APPLICABLE,
    STATE_NOT_REACHED,
    STATE_OK,
    EntryLadderView,
    LadderSignal,
    build_entry_ladder_view,
)
from red_bar_lab.ui._shared import *  # noqa: F401,F403  (follows established ui/pages convention)

IST = ZoneInfo("Asia/Kolkata")
DATE_KEY = "v2_entry_ladder_date"
SIGNAL_KEY = "v2_entry_ladder_signal"
RUNS_KEY = "v2_entry_ladder_max_runs"

#: How each verdict reads on the row. Formatting helpers stay local to the page
#: rather than moving into ``ui/_shared.py``: a star import skips names that
#: begin with an underscore, so a shared ``_fmt_time`` would not arrive here.
_MARKERS = {
    STATE_OK: "🟢",
    STATE_FAIL: "🔴",
    STATE_NOT_REACHED: "⚪",
    STATE_NOT_APPLICABLE: "➖",
}

_VERDICTS = {
    STATE_OK: "ok",
    STATE_FAIL: "FAIL",
    STATE_NOT_REACHED: "not reached",
    STATE_NOT_APPLICABLE: "n/a on this path",
}

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
    if isinstance(value, bool):
        return "yes" if value else "no"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_value(value: object) -> str:
    """One detail value as it should read on a ladder row.

    Timestamps shorten to a clock time, numbers get separators, everything else
    passes through -- the page shows the recorded value, never a derived one.
    """
    if isinstance(value, str) and _parse(value) is not None and "-" in value:
        return _fmt_time(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _fmt_number(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value in (None, ""):
        return "—"
    return str(value)


def _detail_text(detail: Any) -> str:
    if not detail:
        return ""
    return " · ".join(
        f"{key} {_fmt_value(value)}" for key, value in dict(detail).items()
    )


def _headline(signal: LadderSignal) -> str:
    """One sentence naming where this candidate stopped."""
    stopped = signal.stopped_at
    if stopped is not None:
        code = f" ({stopped.code})" if stopped.code else ""
        return (
            f"Stopped at checkpoint {stopped.number} — {stopped.title}{code}. "
            f"Checkpoints above it were never evaluated."
        )
    if signal.reached_number >= 21:
        return "Cleared all 21 entry checkpoints — the position opened."
    return (
        f"No checkpoint refused this candidate. The record answers "
        f"{signal.reached_number} of 21 checkpoints; the rest were not reached."
    )

def _render_cycle_strip(view: EntryLadderView) -> None:
    """The thin strip: what the newest completed cycle saw."""
    cycle = dict(view.cycle or {})
    cols = st.columns([1, 1, 1, 1])
    with cols[0]:
        st.metric("Cycle evaluated", _fmt_time(cycle.get("evaluated_at")))
    with cols[1]:
        st.metric("Candidates seen", _fmt_number(cycle.get("candidate_count"), 0))
    with cols[2]:
        st.metric("Direction", str(cycle.get("direction") or "—"))
    with cols[3]:
        st.metric(
            "Active trades", _fmt_number(cycle.get("active_trade_count"), 0)
        )
    caption = [
        f"Reference {cycle.get('governing_reference') or '—'}",
        f"red bar {_fmt_time(cycle.get('reference_timestamp'))}",
        f"context {_fmt_time(cycle.get('context_timestamp'))}",
        f"trade state {cycle.get('trade_state') or '—'}",
    ]
    if cycle.get("admission_code"):
        caption.append(f"admission {cycle.get('admission_code')}")
    st.caption(" · ".join(caption))


def _render_ladder(signal: LadderSignal) -> None:
    """The 21 checkpoints in the order the candidate walked them."""
    if signal.stopped_at is not None:
        st.warning(_headline(signal))
    elif signal.reached_number >= 21:
        st.success(_headline(signal))
    else:
        st.info(_headline(signal))

    for phase, heading in (
        (ADMISSION_PHASE, "ADMISSION — checkpoints 1-12"),
        (ORDER_PATH_PHASE, "ORDER PATH — checkpoints 13-21"),
    ):
        st.markdown(f"**{heading}**")
        lines: list[str] = []
        for row in signal.rows:
            if row.phase != phase:
                continue
            marker = _MARKERS.get(row.state, "⚪")
            verdict = _VERDICTS.get(row.state, row.state)
            if row.state == STATE_FAIL and row.code:
                verdict = f"FAIL {row.code}"
            detail = _detail_text(row.detail)
            tail = f" — {detail}" if detail else ""
            lines.append(
                f"- {marker} **{row.number} · {row.title}** — {verdict}{tail}"
            )
        st.markdown("\n".join(lines))


def _render_evidence_only(signal: LadderSignal) -> None:
    """What was recorded and given no authority over this entry."""
    st.markdown("**EVIDENCE ONLY — recorded, does not block**")
    if not signal.evidence_only:
        st.caption("Nothing was recorded outside the gates for this candidate.")
        return
    lines = []
    for note in signal.evidence_only:
        detail = f" — {note.detail}" if note.detail else ""
        stamp = f" · {_fmt_time(note.recorded_at)}" if note.recorded_at else ""
        lines.append(f"- `{note.code}`{detail}{stamp}")
    st.markdown("\n".join(lines))
    st.caption(
        "These were evaluated and deliberately given no authority over the "
        "entry. None of them can produce a FAIL above."
    )


def _render_risk_plan(signal: LadderSignal) -> None:
    cols = st.columns([1, 1, 1, 1])
    with cols[0]:
        st.metric("Entry type", str(signal.entry_type or "—"))
    with cols[1]:
        st.metric("Stop price", _fmt_number(signal.risk_stop_price))
    with cols[2]:
        st.metric("Risk points", _fmt_number(signal.risk_points, 1))
    with cols[3]:
        st.metric("Option side", str(signal.option_side or "—"))
    st.caption(
        f"Governing reference {signal.governing_reference or '—'} · "
        f"midpoint {_fmt_number(signal.governing_midpoint)} · "
        f"stop trigger {signal.risk_stop_trigger or '—'} · "
        f"risk plan {signal.risk_plan_code or '—'} · "
        f"signal {signal.signal_id or '—'} · run {signal.run_id or '—'}"
    )

def _render_raw(signal: LadderSignal) -> None:
    """The rows the ladder was assembled from, unedited."""
    with st.expander("Recorded gate evidence (raw)", expanded=False):
        rows = [
            {
                "step": str(row.get("step_name") or ""),
                "status": str(row.get("status") or ""),
                "at": _fmt_time(row.get("started_at")),
                "artifacts": str(row.get("artifacts") or ""),
            }
            for row in signal.evidence_rows
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.caption("No process evidence rows for this run.")
    with st.expander("Order path events (raw)", expanded=False):
        rows = [
            {
                "at": _fmt_time(event.get("timestamp")),
                "state": str(event.get("state") or ""),
                "detail": str(event.get("detail") or ""),
            }
            for event in signal.state_events
        ]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.caption(
                "No lifecycle events for this candidate — it never reached the "
                "order path."
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
    st.title("V2 Entry Ladder")
    st.info(
        "OBSERVATIONAL ONLY — this page reads back the gate evidence, signal "
        "attempts and lifecycle events the strategy already recorded. It never "
        "influences gates, signals, or paper orders."
    )
    cols = st.columns([1, 1, 1])
    with cols[0]:
        selected_date = st.date_input("Trading date", value=date.today(), key=DATE_KEY)
    with cols[1]:
        max_runs = int(st.number_input("Max cycles read", 10, 400, 60, 10, key=RUNS_KEY))
    with cols[2]:
        st.metric("Underlying", underlying_name)

    trading_date = selected_date.isoformat()
    view = build_entry_ladder_view(
        database,
        trading_date=trading_date,
        instrument_key=instrument_key,
        max_runs=max_runs,
    )
    if not view.signals:
        st.info(
            f"No Red Bar V2 candidate was recorded for {trading_date}. Gate "
            "evidence is written once per candidate the strategy evaluates, so "
            "an empty day means no reference produced a candidate — or the "
            "market was closed."
        )
        _render_cycle_strip(view)
        return

    labels = [signal.label for signal in view.signals]
    choice = st.selectbox("Candidate", labels, index=0, key=SIGNAL_KEY)
    signal = view.signals[labels.index(choice)] if choice in labels else view.signals[0]

    _render_cycle_strip(view)
    st.markdown("---")
    _render_risk_plan(signal)
    st.markdown("---")
    _render_ladder(signal)
    st.markdown("---")
    _render_evidence_only(signal)
    st.markdown("---")
    _render_raw(signal)
    st.caption(
        f"{len(view.signals)} candidate(s) recorded on {trading_date} for "
        f"{instrument_key}."
    )

