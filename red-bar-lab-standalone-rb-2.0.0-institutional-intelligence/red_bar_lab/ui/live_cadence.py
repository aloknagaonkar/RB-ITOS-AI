"""Live cadence and per-step timing helpers for the lifecycle pages.

This module is the live-monitoring layer on top of the static
``lifecycle_stepper`` framework. It provides:

- A poller that watches the upstream paper monitor, the background
  pipeline orchestrator, and tracks the page's own poll cadence.
- A timing wrapper that records the read + render time of each
  lifecycle step renderer and exposes the timing to the section
  header.
- A "follow live signal" trigger that snaps the page to a new
  signal_id as soon as the upstream paper monitor sees it.

State is kept in ``st.session_state`` only. The user is responsible
for choosing a polling interval; 2s–30s is supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any


POLL_INTERVAL_KEY = "live_cadence_poll_interval_seconds"
LAST_POLL_AT_KEY = "live_cadence_last_poll_at"
POLLS_SINCE_START_KEY = "live_cadence_polls_since_start"
LAST_SEEN_SIGNAL_ID_KEY = "live_cadence_last_seen_signal_id"
LAST_FOLLOWED_SIGNAL_ID_KEY = "live_cadence_last_followed_signal_id"
LAST_ERROR_KEY = "live_cadence_last_error"
STEP_TIMINGS_KEY = "live_cadence_step_timings"
PAGE_STARTED_AT_KEY = "live_cadence_page_started_at"
LAST_FOLLOW_FLASH_KEY = "live_cadence_last_follow_flash"

POLL_INTERVAL_OPTIONS: tuple[tuple[str, int], ...] = (
    ("2 seconds (fastest)", 2),
    ("3 seconds", 3),
    ("5 seconds (matches paper monitor)", 5),
    ("10 seconds", 10),
    ("30 seconds (lightest)", 30),
)

DEFAULT_POLL_INTERVAL_SECONDS = 3

STALE_HEARTBEAT_SECONDS = 30.0


@dataclass(frozen=True)
class UpstreamCadenceStatus:
    """Snapshot of one upstream cadence at a single point in time."""

    name: str
    cadence_label: str
    last_heartbeat_at: str | None
    seconds_since_heartbeat: float | None
    is_stale: bool
    last_signal_id: str | None
    last_decision: str | None
    last_error: str | None
    total_ms: float | None
    stages: dict[str, float]
    last_success_at: str | None = None
    last_success_decision: str | None = None
    last_success_signal_id: str | None = None
    last_success_total_ms: float | None = None
    last_success_stages: dict[str, float] | None = None
    seconds_since_last_success: float | None = None
    last_success_underlying_status: str | None = None
    last_success_readiness_ms: float | None = None
    last_success_futures_status: str | None = None
    last_success_candle_timestamp: str | None = None
    last_success_candle_age_seconds: float | None = None
    last_success_bridge_alignment: str | None = None
    last_success_readiness_reason: str | None = None
    # Orchestrator-specific summary fields
    run_duration_ms: float | None = None
    confirmed_count: int | None = None
    core_eligible_count: int | None = None
    hybrid_eligible_count: int | None = None
    started_at: str | None = None
    # Visual flow indicators
    dependency: str | None = None  # upstream-of | downstream-of | self-paced
    dependency_label: str | None = None  # "5s upstream" | "1m upstream" | "user-config"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _seconds_since(iso_timestamp: str | None, *, now_epoch: float) -> float | None:
    if not iso_timestamp:
        return None
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0.0, now_epoch - parsed.timestamp())


def _parse_stage_timings(row: dict[str, object] | None) -> dict[str, float]:
    if not row:
        return {}
    candidates = (
        "cycle_timings_ms",
        "stage_timings_ms",
        "last_cycle_timings_ms",
    )
    for key in candidates:
        value = row.get(key)
        if not value:
            continue
        if isinstance(value, dict):
            return {str(k): float(v) for k, v in value.items() if v is not None}
        if isinstance(value, str) and value.strip().startswith("{"):
            import json

            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return {str(k): float(v) for k, v in parsed.items() if v is not None}
    return {}


def _parse_success_stages(row: dict[str, object] | None) -> dict[str, float] | None:
    """Parse the JSON-encoded stage map for the last successful cycle."""
    if not row:
        return None
    raw = row.get("last_success_stages_json")
    if not raw:
        return None
    import json

    if isinstance(raw, dict):
        return {str(k): float(v) for k, v in raw.items() if v is not None}
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, dict):
            return {
                str(k): float(v) for k, v in parsed.items() if v is not None
            }
    return None


def read_paper_monitor_cadence(
    database: Any,
    *,
    monitor_id: str = "PAPER-MONITOR",
) -> UpstreamCadenceStatus:
    """Read the paper monitor's heartbeat, last signal, and stage timings."""
    import time as _time

    now_epoch = _time.time()
    row = safe_db_read(
        lambda: database.read_paper_monitor_status(monitor_id), default=None
    )
    heartbeat = (
        str(row.get("heartbeat_at"))
        if row is not None and row.get("heartbeat_at") is not None
        else None
    )
    seconds_since = _seconds_since(heartbeat, now_epoch=now_epoch)
    stages = _parse_stage_timings(row)
    total_ms = float(stages.get("total", 0.0)) if stages else None
    last_success_at = (
        str(row.get("last_success_at"))
        if row is not None and row.get("last_success_at") is not None
        else None
    )
    last_success_decision = (
        str(row.get("last_success_decision"))
        if row is not None and row.get("last_success_decision")
        else None
    )
    last_success_signal_id = (
        str(row.get("last_success_signal_id"))
        if row is not None and row.get("last_success_signal_id")
        else None
    )
    last_success_total_raw = (
        row.get("last_success_total_ms") if row is not None else None
    )
    last_success_total_ms = (
        float(last_success_total_raw)
        if last_success_total_raw is not None
        else None
    )
    last_success_stages = _parse_success_stages(row)
    seconds_since_last_success = _seconds_since(last_success_at, now_epoch=now_epoch)
    last_success_underlying_status = (
        str(row.get("last_success_underlying_status"))
        if row is not None and row.get("last_success_underlying_status")
        else None
    )
    last_success_readiness_raw = (
        row.get("last_success_readiness_ms") if row is not None else None
    )
    last_success_readiness_ms = (
        float(last_success_readiness_raw)
        if last_success_readiness_raw is not None
        else None
    )
    last_success_futures_status = (
        str(row.get("last_success_futures_status"))
        if row is not None and row.get("last_success_futures_status")
        else None
    )
    last_success_candle_timestamp = (
        str(row.get("last_success_candle_timestamp"))
        if row is not None and row.get("last_success_candle_timestamp")
        else None
    )
    last_success_candle_age_raw = (
        row.get("last_success_candle_age_seconds") if row is not None else None
    )
    last_success_candle_age_seconds = (
        float(last_success_candle_age_raw)
        if last_success_candle_age_raw is not None
        else None
    )
    last_success_bridge_alignment = (
        str(row.get("last_success_bridge_alignment"))
        if row is not None and row.get("last_success_bridge_alignment")
        else None
    )
    last_success_readiness_reason = (
        str(row.get("last_success_readiness_reason"))
        if row is not None and row.get("last_success_readiness_reason")
        else None
    )
    return UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at=heartbeat,
        seconds_since_heartbeat=seconds_since,
        is_stale=(
            seconds_since is not None and seconds_since > STALE_HEARTBEAT_SECONDS
        ),
        last_signal_id=(
            str(row.get("last_signal_id"))
            if row is not None and row.get("last_signal_id")
            else None
        ),
        last_decision=(
            str(row.get("last_decision"))
            if row is not None and row.get("last_decision")
            else None
        ),
        last_error=(
            str(row.get("last_error"))
            if row is not None and row.get("last_error")
            else None
        ),
        total_ms=total_ms,
        stages=stages,
        last_success_at=last_success_at,
        last_success_decision=last_success_decision,
        last_success_signal_id=last_success_signal_id,
        last_success_total_ms=last_success_total_ms,
        last_success_stages=last_success_stages,
        seconds_since_last_success=seconds_since_last_success,
        last_success_underlying_status=last_success_underlying_status,
        last_success_readiness_ms=last_success_readiness_ms,
        last_success_futures_status=last_success_futures_status,
        last_success_candle_timestamp=last_success_candle_timestamp,
        last_success_candle_age_seconds=last_success_candle_age_seconds,
        last_success_bridge_alignment=last_success_bridge_alignment,
        last_success_readiness_reason=last_success_readiness_reason,
        # Visual flow
        dependency="upstream-of:orchestrator",
        dependency_label="5s upstream loop · feeds orchestrator",
    )


def read_orchestrator_cadence(
    database: Any,
    *,
    instrument_key: str,
    trading_date: str,
) -> UpstreamCadenceStatus:
    """Read the background pipeline orchestrator's most recent run status.

    The orchestrator writes one row per (instrument, trading_date) at the
    end of each pipeline run. The "today's date" filter only matters for
    a fresh row written in the current session — we always want the most
    recent run on the card, even if the latest successful run is from
    yesterday (e.g. the orchestrator runs after market close).
    """
    import time as _time

    now_epoch = _time.time()
    today_row = safe_db_read(
        lambda: database.read_pipeline_run_status(instrument_key, trading_date),
        default=None,
    )
    latest_row = safe_db_read(
        lambda: _read_latest_pipeline_run_status(database, instrument_key),
        default=None,
    )
    primary = today_row or latest_row
    heartbeat = (
        str(primary.get("updated_at"))
        if primary is not None and primary.get("updated_at") is not None
        else None
    )
    seconds_since = _seconds_since(heartbeat, now_epoch=now_epoch)
    # The orchestrator runs after market close (typically once per day).
    # A row from yesterday is normal, not a failure — only mark stale if
    # the most recent run is older than 24h.
    is_stale = (
        seconds_since is not None and seconds_since > (60 * 60 * 24.0)
    )
    decision = (
        str(primary.get("status"))
        if primary is not None and primary.get("status")
        else None
    )
    message = (
        str(primary.get("message"))
        if primary is not None and primary.get("message")
        else None
    )
    primary_date = (
        str(primary.get("trading_date"))
        if primary is not None and primary.get("trading_date")
        else None
    )
    run_duration_raw = primary.get("run_duration_ms") if primary else None
    run_duration_ms = (
        float(run_duration_raw) if run_duration_raw is not None else None
    )
    confirmed_count = (
        int(primary.get("confirmed_count"))
        if primary is not None and primary.get("confirmed_count") is not None
        else None
    )
    core_eligible_count = (
        int(primary.get("core_eligible_count"))
        if primary is not None and primary.get("core_eligible_count") is not None
        else None
    )
    hybrid_eligible_count = (
        int(primary.get("hybrid_eligible_count"))
        if primary is not None and primary.get("hybrid_eligible_count") is not None
        else None
    )
    started_at = (
        str(primary.get("started_at"))
        if primary is not None and primary.get("started_at")
        else None
    )
    # Subtitle: show the run's trading date prominently so the user can
    # answer "is this fresh?" without reading the full caption.
    subtitle = (
        f"last run on {primary_date}"
        if primary_date
        else "no run recorded yet"
    )
    return UpstreamCadenceStatus(
        name="Background Orchestrator",
        cadence_label=subtitle,
        last_heartbeat_at=heartbeat,
        seconds_since_heartbeat=seconds_since,
        is_stale=is_stale,
        last_signal_id=None,
        last_decision=decision,
        last_error=None,  # orchestrator's "message" is a status summary, not an error
        total_ms=run_duration_ms,
        stages={},
        last_success_at=heartbeat,
        last_success_decision=decision,
        last_success_signal_id=None,
        last_success_total_ms=run_duration_ms,
        last_success_stages=None,
        seconds_since_last_success=seconds_since,
        last_success_underlying_status=primary_date,
        last_success_readiness_ms=None,
        last_success_futures_status=None,
        last_success_candle_timestamp=None,
        last_success_candle_age_seconds=None,
        last_success_bridge_alignment=message,
        last_success_readiness_reason=(
            "today's run has not started yet"
            if today_row is None and latest_row is not None
            else None
        ),
        # Orchestrator-specific fields
        run_duration_ms=run_duration_ms,
        confirmed_count=confirmed_count,
        core_eligible_count=core_eligible_count,
        hybrid_eligible_count=hybrid_eligible_count,
        started_at=started_at,
        # The orchestrator runs inside the market_collector process
        dependency="downstream-of:paper-monitor",
        dependency_label="1m upstream of market_collector",
    )


def _read_latest_pipeline_run_status(database: Any, instrument_key: str):
    """Return the most recent pipeline run row for an instrument, any date.

    Falls back to None if the database has no helper for this. We try a
    few common method names so the panel works without forcing a new
    repository method.
    """
    for method_name in (
        "read_latest_pipeline_run_status",
        "read_latest_intelligence_pipeline_run",
        "read_pipeline_run_status_for_instrument",
    ):
        method = getattr(database, method_name, None)
        if callable(method):
            try:
                return method(instrument_key)
            except Exception:  # noqa: BLE001
                return None
    return None


def render_upstream_cadence_panel(
    st: Any,
    *,
    cadences: list[UpstreamCadenceStatus],
    page_poll_interval_seconds: int,
    page_polls_since_start: int,
    page_last_poll_at: str | None,
    page_started_at: str | None,
    instrument_key: str | None = None,
    trading_date: str | None = None,
    account_id: str | None = None,
) -> None:
    """Render the cadence panel at the top of the live page.

    Two-tier view, controlled by an "Advanced diagnostics" checkbox:

    - Default = Trading view. 3 sections: latest signal, today's
      activity, attention-needed (only if non-empty). Designed for the
      9am open-the-app user.
    - Advanced = Diagnostic view. Adds the cross-process correlation
      panel, the per-step evidence panel, and the run timeline. Used
      when something is wrong and the user needs to dig in.

    The trading view is the default because the detailed view's
    30+ log rows are noise to a trader who just wants to know "is
    there a signal to enter on, and did the system act on it?"
    """
    st.markdown("##### Upstream Cadences")
    _render_error_banner(st)
    _render_dependency_strip(st)
    cols = st.columns(3)
    for index, cadence in enumerate(cadences[:3]):
        column = cols[index] if index < len(cols) else cols[-1]
        with column:
            _render_single_cadence(st, cadence)

    # Trading view: always rendered. Shows the actionable signal and
    # today's activity, in trading-relevant terms.
    _render_trading_view(
        st,
        instrument_key=instrument_key,
        trading_date=trading_date,
        account_id=account_id,
    )

    # Diagnostic view: gated behind a checkbox so the panel doesn't
    # fill up with log noise during normal trading.
    advanced = st.checkbox(
        "Advanced diagnostics",
        value=False,
        key="live_cadence_advanced_diagnostics",
        help=(
            "Show the per-step evidence timeline, run correlation, "
            "and full run timeline. Useful for debugging when "
            "something is wrong. Off for normal trading."
        ),
    )
    if advanced:
        _render_run_correlation_panel(st)
        _render_step_evidence_panel(st)

    st.caption(
        f"Page poll cadence: {page_poll_interval_seconds}s · "
        f"polls since session start: {page_polls_since_start} · "
        f"last poll: {page_last_poll_at or '—'} · "
        f"page opened: {page_started_at or '—'}"
    )


def _render_trading_view(
    st: Any,
    *,
    instrument_key: str | None,
    trading_date: str | None,
    account_id: str | None,
) -> None:
    """Render the trading-relevant view: latest signal, today's
    activity, and any attention-needed banner.

    Designed to answer three questions in one glance:

    - Is there a confirmed signal right now, and what does the
      canonical V2 think of it?
    - What has the system done today — entries, exits, errors?
    - Is there anything I need to act on?
    """
    st.markdown("##### Trading view")
    database = _get_database_handle(st)
    if database is None:
        st.caption("No database handle — trading view unavailable.")
        return
    if not instrument_key or not trading_date:
        st.caption("No instrument or trading date set — pick a date above.")
        return
    # Section 1: Latest confirmed signal.
    _render_latest_signal_section(
        st,
        database=database,
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    # Section 2: Today's activity.
    _render_today_activity_section(
        st,
        database=database,
        trading_date=trading_date,
        account_id=account_id or "PAPER-STD",
    )


def _render_latest_signal_section(
    st: Any,
    *,
    database: Any,
    instrument_key: str,
    trading_date: str,
) -> None:
    """Show the most recent confirmed signal with its Section 1/2/3
    verdict. The single most actionable piece of information on the
    page."""
    try:
        signal = database.read_latest_signal_for_trading(
            instrument_key=instrument_key, trading_date=trading_date
        )
    except Exception:  # noqa: BLE001
        signal = None
    st.markdown("**Latest signal**")
    if signal is None:
        st.caption(
            "No confirmed signal for this date yet. "
            "The market_collector is running — a new signal will "
            "appear when the strategy's admission conditions are met."
        )
        return
    # Header line: time, side, level, score.
    ts = (
        signal.get("confirmation_timestamp")
        or signal.get("created_at")
        or "—"
    )
    level = signal.get("level") or "—"
    direction = signal.get("direction") or "—"
    score = signal.get("score")
    score_str = f" · score {score}" if score is not None else ""
    st.markdown(
        f"`{ts}`  **{direction} {level}**{score_str}"
    )
    # Section 1 / 2 / 3 verdict from the shadow observation.
    shadow = signal.get("shadow_observation") or {}
    s1 = shadow.get("section_1_outcome") or "—"
    s2 = shadow.get("section_2_outcome") or "—"
    bundle_id = shadow.get("bundle_id")
    st.caption(
        f"Section 1: **{s1}**  ·  Section 2: **{s2}**"
        + (f"  ·  bundle: `{bundle_id}`" if bundle_id else "")
    )
    # Pipeline status (eligibility for paper trading).
    status = signal.get("pipeline_status") or {}
    if status:
        core = bool(status.get("core_eligible"))
        hybrid = bool(status.get("hybrid_eligible"))
        verdict = "core eligible" if core else ("hybrid only" if hybrid else "blocked")
        st.caption(f"Pipeline: {verdict}")


def _render_today_activity_section(
    st: Any,
    *,
    database: Any,
    trading_date: str,
    account_id: str,
) -> None:
    """Show today's signal/entry/exit counts and last trade."""
    st.markdown("**Today's activity**")
    try:
        counts = database.read_today_signal_counts(
            instrument_key="NSE_INDEX|Nifty 50", trading_date=trading_date
        )
    except Exception:  # noqa: BLE001
        counts = {}
    try:
        activity = database.read_today_paper_activity(
            account_id=account_id, trading_date=trading_date
        )
    except Exception:  # noqa: BLE001
        activity = {
            "entered": 0,
            "closed": 0,
            "open": 0,
            "last_entry": None,
            "last_close": None,
            "realized_pnl": 0.0,
        }
    confirmed = counts.get("CONFIRMED", 0)
    pending = counts.get("PENDING", 0)
    entered = activity["entered"]
    closed = activity["closed"]
    open_count = activity["open"]
    realized = activity["realized_pnl"]
    st.caption(
        f"Signals: **{confirmed}** confirmed  ·  **{pending}** pending"
        f"  ·  Paper: **{entered}** entered, **{closed}** closed, "
        f"**{open_count}** open  ·  P&L (closed): **{realized:+.2f}**"
    )
    last_entry = activity.get("last_entry")
    if last_entry is not None:
        direction = last_entry.get("direction") or "—"
        option_type = last_entry.get("option_type") or ""
        strike = last_entry.get("strike_price") or "—"
        entry_price = last_entry.get("entry_price") or "—"
        entry_ts = last_entry.get("entry_timestamp") or "—"
        st.caption(
            f"Last entry: {direction} {strike}{option_type} @ {entry_price}"
            f"  ·  {entry_ts}"
        )
    last_close = activity.get("last_close")
    if last_close is not None:
        exit_price = last_close.get("exit_price") or "—"
        exit_ts = last_close.get("exit_timestamp") or "—"
        reason = last_close.get("exit_reason") or "—"
        st.caption(
            f"Last close: @ {exit_price}  ·  {exit_ts}  ·  {reason}"
        )


def _render_step_evidence_panel(st: Any) -> None:
    """Render the per-step evidence timeline for the three components.

    Reads ``process_evidence`` and shows the most recent run for each
    (process, step) so the user can see "last run at HH:MM:SS, took N ms".
    Also offers a per-run-id timeline view that shows all steps for a
    single run.
    """
    reader = _get_step_evidence_reader(st)
    if reader is None:
        return
    st.markdown("##### Per-step evidence (last 5 runs per step)")
    try:
        timelines = reader(limit_per_step=5)
    except Exception:  # noqa: BLE001
        st.caption("process_evidence read failed (DB unavailable?)")
        return
    if not timelines:
        st.caption("No step evidence recorded yet.")
        return
    for key in sorted(timelines.keys()):
        rows = timelines[key]
        if not rows:
            continue
        latest = rows[0]
        status = str(latest.get("status", "—"))
        duration = latest.get("duration_ms")
        started = latest.get("started_at", "—")
        step_label = latest.get("step_name", key)
        process_label = latest.get("process_name", "—")
        run_id = latest.get("run_id", "—")
        duration_str = (
            f"{float(duration):.0f} ms"
            if isinstance(duration, (int, float))
            else "—"
        )
        # Status icon
        status_icon = {
            "OK": "✓",
            "ERROR": "✗",
            "RUNNING": "…",
        }.get(status, "?")
        st.caption(
            f"{status_icon} **{process_label} :: {step_label}** — "
            f"{status} · {duration_str} · last: {started} · run: `{run_id}`"
        )
        if status == "ERROR" and latest.get("error_message"):
            st.caption(f"  error: {latest['error_message'][:200]}")

    # Per-run timeline selector.
    _render_run_timeline_section(st)


def render_pipeline_sub_status(
    st: Any,
    *,
    section_id: str,
    run_id: str | None,
) -> None:
    """Render a compact red/green mini-checklist for one of the 12
    V2 Lifecycle sections, based on the ``paper_trading_pipeline``
    process_evidence rows for ``run_id``.

    Each of the 8 sections that participates in the pipeline gets a
    1-3 row checklist above the existing section content. The user
    can scan the page and immediately see "section 4 is red because
    the committee rejected the signal" without expanding anything.

    The function is best-effort: if the database doesn't have the rows
    for this run_id, the checklist is omitted silently.
    """
    if not run_id:
        return
    database = _get_database_handle(st)
    if database is None or not hasattr(database, "read_run_evidence"):
        return
    try:
        rows = database.read_run_evidence(run_id=run_id)
    except Exception:  # noqa: BLE001
        return
    pipeline_rows = [
        r
        for r in rows
        if str(r.get("process_name") or "") == "paper_trading_pipeline"
    ]
    if not pipeline_rows:
        return
    # Per-section checklist. Keys are section_id, values are the list
    # of step_names that belong to that section. The order here is
    # the order they render top-to-bottom.
    #
    # ONLY includes stages that the paper monitor / canonical shadow
    # actually write to ``process_evidence``. We removed the
    # ``portfolio_risk``, ``mark_update``, and ``exit_decision``
    # placeholders because no audit calls exist for them in
    # ``execution/automation.py`` or ``paper_monitor.py``; surfacing
    # them would have shown permanently-empty sub-statuses and looked
    # like a bug. The portfolio risk module is currently observational
    # anyway (see ``portfolio_manager.py:admit``), so it isn't a real
    # gate the user can fail.
    section_checklists = {
        "lifecycle_eligibility": ["lifecycle_check"],
        "decision": [
            "lifecycle_check",
            "directional_regime",
            "execution_committee",
        ],
        "decision_post_committee": [
            "lifecycle_check",
            "directional_regime",
            "score_candidates",
            "execution_committee",
        ],
        "scoring_selection": ["score_candidates", "execution_committee"],
        "risk_gates": [
            "score_candidates",
            "execution_committee",
        ],
        "queue": [
            "lifecycle_check",
            "directional_regime",
            "score_candidates",
            "execution_committee",
        ],
        "entry": [
            "lifecycle_check",
            "directional_regime",
            "score_candidates",
            "execution_committee",
            "opportunity_extension",
            "order_placement",
        ],
    }
    checklist = section_checklists.get(section_id, [])
    relevant = [
        r
        for r in pipeline_rows
        if str(r.get("step_name") or "") in checklist
    ]
    if not relevant:
        return
    st.caption("Pipeline status for this section:")
    for row in relevant:
        _render_pipeline_status_row(st, row)


def _render_pipeline_status_row(st: Any, row: dict[str, object]) -> None:
    step = str(row.get("step_name") or "—")
    status = str(row.get("status") or "—")
    artifacts = row.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        artifacts = {}
    icon = "✓" if status == "OK" else ("✗" if status == "ERROR" else "?")
    label = step.replace("_", " ").title()
    detail = ""
    if step == "lifecycle_check":
        detail = f"state={artifacts.get('state', '—')}"
    elif step == "directional_regime":
        detail = f"regime={artifacts.get('regime', '—')}"
    elif step == "score_candidates":
        detail = (
            f"best={artifacts.get('best_candidate', '—')}, "
            f"score={artifacts.get('best_score', '—')}, "
            f"min={artifacts.get('minimum_score', '—')}, "
            f"ok={artifacts.get('score_ok', '—')}"
        )
    elif step == "execution_committee":
        # This is the most important row: when status=ERROR, the user
        # needs the reason text to know *why* the committee said no.
        # We split it out as a separate caption so it's prominent.
        reason = artifacts.get("reason") or "—"
        prob = artifacts.get("execution_probability_pct")
        prob_str = (
            f"{prob:.1f}%" if isinstance(prob, (int, float)) else "—"
        )
        if status == "ERROR":
            st.caption(f"  ✗ **Execution Committee** — {status}  ·  {reason}")
        else:
            st.caption(
                f"  ✓ **Execution Committee** — {status}  ·  "
                f"prob={prob_str}  ·  reason={reason}"
            )
        return
    elif step == "order_placement":
        detail = (
            f"order_id={artifacts.get('order_id', '—')}, "
            f"symbol={artifacts.get('symbol', '—')}, "
            f"fill={artifacts.get('fill_price', '—')}"
        )
    elif step == "exit_decision":
        reason = artifacts.get("reason") or "—"
        detail = f"reason={reason}"
    elif step == "mark_update":
        detail = f"ltp={artifacts.get('ltp', '—')}"
    st.caption(f"  {icon} **{label}** — {status}  ·  {detail}")


def render_strategy_engine_audit(st: Any, *, run_id: str | None) -> None:
    """Render the Red Bar V2 strategy engine's most recent sub-checks.

    Shown as a sub-block inside section 1 of the V2 Lifecycle pages
    ("Reference Readiness" / "Signal Discovery"). The user sees what
    the strategy actually did this cycle:

    - The 5 boolean gates (reference_ready, rsi_aligned, vwap_aligned,
      midpoint_aligned, context_fresh)
    - The candidate scan count
    - The latest admission decision (event_type, direction, entry_type,
      trend_strength, score, reason)

    Plus a "Why this signal fired" panel that shows the booleans as
    checkmarks the user can read in 1 second.

    Reads ``process_evidence`` rows with
    ``process_name='red_bar_v2_strategy'`` filtered to the most-recent
    run_id that the page knows about. Best-effort: if the database
    doesn't have the rows, the sub-block is omitted silently.
    """
    if not run_id:
        return
    database = _get_database_handle(st)
    if database is None or not hasattr(database, "read_run_evidence"):
        return
    try:
        rows = database.read_run_evidence(run_id=run_id)
    except Exception:  # noqa: BLE001
        return
    strategy_rows = [
        r
        for r in rows
        if str(r.get("process_name") or "") == "red_bar_v2_strategy"
    ]
    if not strategy_rows:
        return
    # "Why this signal fired" — a compact checklist of the 5 gates.
    check_rows = [
        r
        for r in strategy_rows
        if str(r.get("step_name") or "").startswith("check:")
    ]
    admission_row = next(
        (
            r
            for r in strategy_rows
            if str(r.get("step_name") or "") == "admission_decision"
        ),
        None,
    )
    if check_rows or admission_row is not None:
        _render_why_this_signal_fired(
            st, check_rows=check_rows, admission_row=admission_row
        )
    with st.expander("Strategy Engine Audit (raw sub-step rows)", expanded=False):
        st.caption(
            f"All red_bar_v2_strategy sub-step rows for run `{run_id}` "
            f"({len(strategy_rows)} rows)"
        )
        for row in strategy_rows:
            _render_strategy_audit_row(st, row)


def _render_why_this_signal_fired(
    st: Any,
    *,
    check_rows: list[dict[str, object]],
    admission_row: dict[str, object] | None,
) -> None:
    """Render a compact "Why this signal fired" panel inside section 1.

    Shows the 5 boolean gates as checkmarks + the admission decision
    header (event type, direction, entry type, trend strength, reason).
    """
    # Show the admission header first, if any.
    if admission_row is not None:
        artifacts = admission_row.get("artifacts") or {}
        if not isinstance(artifacts, dict):
            artifacts = {}
        event_type = artifacts.get("event_type") or "—"
        direction = artifacts.get("direction") or "—"
        option_side = artifacts.get("option_side")
        entry_type = artifacts.get("entry_type") or "—"
        trend_strength = artifacts.get("trend_strength") or "—"
        score = artifacts.get("candidate_score")
        reason = artifacts.get("reason") or "—"
        score_str = f" · score {score}" if score is not None else ""
        side_str = f" {option_side}" if option_side else ""
        st.markdown(
            f"**Why this signal fired**  \n"
            f"Trigger: **{event_type}** · **{direction}{side_str}** · "
            f"entry: **{entry_type}** · trend: **{trend_strength}**"
            f"{score_str}  \n"
            f"Reason: {reason}"
        )
    # Show the gates as a checklist. Note: "midpoint_aligned" is now
    # relabelled as "RedBar reference aligned" in the UI (the
    # underlying boolean is unchanged).
    if check_rows:
        gate_labels = {
            "check:reference_ready": "Reference ready (Section 1 OK)",
            "check:context_fresh": "Context fresh (candle < 120s old)",
            "check:redbar_vwap_aligned": (
                "RedBar + VWAP combined (both in same direction)"
            ),
            "check:vwap_aligned": "VWAP aligned (close vs VWAP)",
            "check:midpoint_aligned": (
                "RedBar reference aligned (close vs ref midpoint)"
            ),
            "check:rsi_informational": (
                "RSI (informational) — does not block admission"
            ),
            "check:pcr_informational": (
                "PCR (informational) — current vs morning"
            ),
        }
        # Order shown to the user. We render all rows that exist in
        # the database; the order list is just the priority for
        # display.
        order = [
            "check:reference_ready",
            "check:context_fresh",
            "check:redbar_vwap_aligned",
            "check:vwap_aligned",
            "check:midpoint_aligned",
            "check:rsi_informational",
            "check:pcr_informational",
        ]
        rows_by_name = {
            str(r.get("step_name") or ""): r for r in check_rows
        }
        st.caption("**Gates that fired:**")
        for name in order:
            row = rows_by_name.get(name)
            if row is None:
                continue
            artifacts = row.get("artifacts") or {}
            if not isinstance(artifacts, dict):
                artifacts = {}
            passed = bool(artifacts.get("passed"))
            status = str(row.get("status") or "—")
            # Informational rows are always "✓" (just shown, not gating)
            is_info = name in {
                "check:rsi_informational",
                "check:pcr_informational",
            }
            icon = "✓" if (is_info or (passed and status == "OK")) else "✗"
            label = gate_labels.get(name, name)
            extra = ""
            if "state" in artifacts:
                extra = f"  · state={artifacts['state']}"
            st.caption(f"  {icon} {label}{extra}")
        # Render mid-session 12:45 rule if active.
        for name in ("check:mid_session", "check:mid_session_1245"):
            row = rows_by_name.get(name)
            if row is None:
                continue
            artifacts = row.get("artifacts") or {}
            if not isinstance(artifacts, dict):
                artifacts = {}
            passed = bool(artifacts.get("passed"))
            status = str(row.get("status") or "—")
            icon = "✓" if passed and status == "OK" else "✗"
            reason = artifacts.get("reason") or ""
            st.caption(
                f"  {icon} Mid-session 12:45 (active in 12:45-1:15 window) — "
                f"{reason}"
            )
        # Render re-entry validation state.
        reentry = rows_by_name.get("check:reentry_validation")
        if reentry is not None:
            artifacts = reentry.get("artifacts") or {}
            if not isinstance(artifacts, dict):
                artifacts = {}
            state = artifacts.get("state") or "unknown"
            if state in {"validated"}:
                st.caption(
                    "  ✓ Re-entry validated — 5m candle touched both "
                    "RedBar reference and VWAP in same direction"
                )
            elif state in {"failed"}:
                st.caption(
                    "  ✗ Re-entry validation failed — next 5m candle did "
                    "not confirm direction"
                )
            else:
                st.caption(
                    f"  ⓳ Re-entry waiting — last touch at "
                    f"{artifacts.get('touch_candle', '?')}, "
                    f"waiting for next-candle VWAP confirm"
                )


def _render_strategy_audit_row(st: Any, row: dict[str, object]) -> None:
    step = str(row.get("step_name") or "—")
    status = str(row.get("status") or "—")
    artifacts = row.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        artifacts = {}
    status_icon = {"OK": "✓", "ERROR": "✗", "RUNNING": "…"}.get(status, "?")
    label = step.replace("_", " ").title()
    # Build a compact one-line description of the most useful
    # artifacts. Keeps the panel dense without hiding detail.
    if step == "latest_completed_1m_candle":
        close = artifacts.get("candle_close")
        rsi = artifacts.get("candle_rsi_14")
        ts = artifacts.get("candle_timestamp")
        st.caption(
            f"{status_icon} **Latest 1m candle** — "
            f"close={close} · rsi_14={rsi} · {ts}"
        )
    elif step == "candidate_scan":
        count = artifacts.get("candidate_count", 0)
        types = ", ".join(artifacts.get("candidate_event_types") or []) or "—"
        st.caption(
            f"{status_icon} **Candidate scan** — {count} candidate(s) · "
            f"event types: {types}"
        )
    elif step == "admission_decision":
        event_type = artifacts.get("event_type") or "—"
        direction = artifacts.get("direction") or "—"
        option_side = artifacts.get("option_side") or "—"
        entry_type = artifacts.get("entry_type") or "—"
        trend_strength = artifacts.get("trend_strength") or "—"
        score = artifacts.get("candidate_score")
        reason = artifacts.get("reason") or "—"
        score_str = f" · score {score}" if score is not None else ""
        st.caption(
            f"{status_icon} **Admission** — "
            f"event={event_type} · dir={direction} · side={option_side} · "
            f"entry={entry_type} · trend={trend_strength} · "
            f"allowed={artifacts.get('outcome')}{score_str}  \n"
            f"  reason: {reason}"
        )
    elif step.startswith("check:"):
        passed = bool(artifacts.get("passed"))
        icon = "✓" if passed and status == "OK" else "✗"
        st.caption(f"{icon} **{label}** — {status}")
    else:
        st.caption(f"{status_icon} **{label}** — {status}")
        if artifacts:
            st.caption(f"  details: {artifacts}")


def _render_run_timeline_section(st: Any) -> None:
    """Render a selector that lets the user pick a run_id and see all
    evidence rows for that run, in chronological order."""
    database = _get_database_handle(st)
    if database is None or not hasattr(database, "read_run_evidence"):
        return
    # Collect the most recent run_ids across all processes.
    if not hasattr(database, "read_all_process_run_correlations"):
        return
    try:
        correlations = database.read_all_process_run_correlations()
    except Exception:  # noqa: BLE001
        return
    if not correlations:
        return
    # Build a unique list of run_ids (newest first).
    seen: set[str] = set()
    run_ids: list[str] = []
    for row in correlations:
        rid = str(row.get("run_id") or "")
        if rid and rid not in seen:
            seen.add(rid)
            run_ids.append(rid)
    if not run_ids:
        return
    st.markdown("##### Run timeline")
    selected = st.selectbox(
        "Pick a run_id to see all its evidence rows in order",
        options=run_ids,
        key="live_cadence_run_id_select",
    )
    if not selected:
        return
    try:
        rows = database.read_run_evidence(run_id=selected)
    except Exception:  # noqa: BLE001
        st.caption("read_run_evidence failed (DB unavailable?)")
        return
    if not rows:
        st.caption(f"No evidence rows found for run_id `{selected}`.")
        return
    for row in rows:
        _render_run_evidence_row(st, row)


def _render_run_evidence_row(st: Any, row: dict[str, object]) -> None:
    process = row.get("process_name", "—")
    step = row.get("step_name", "—")
    parent = row.get("parent_step") or "—"
    started = row.get("started_at", "—")
    status = row.get("status", "—")
    duration = row.get("duration_ms")
    duration_str = (
        f"{float(duration):.0f} ms"
        if isinstance(duration, (int, float))
        else "—"
    )
    status_icon = {
        "OK": "✓",
        "ERROR": "✗",
        "RUNNING": "…",
    }.get(str(status), "?")
    st.caption(
        f"{status_icon} **{process} :: {step}** "
        f"(parent: {parent}) — {status} · {duration_str} · {started}"
    )
    artifacts = row.get("artifacts") or {}
    if artifacts and isinstance(artifacts, dict):
        for key, value in list(artifacts.items())[:4]:
            st.caption(f"  · {key}: {value}")


def _get_database_handle(st: Any):
    try:
        return st.session_state.get("step_evidence_database")
    except Exception:  # noqa: BLE001
        return None


def _read_active_paper_config(database: Any) -> dict[str, object]:
    """Read the active strategy + exit policy + score thresholds.

    Looks at the most-recent ``paper_execution_orders`` row to discover
    which ``execution_strategy_source`` and ``exit_mode`` were used
    today. Falls back to the Red Bar V2 defaults if no orders exist
    yet. The score thresholds come from the configured automation
    service; we surface the last-known values from
    ``process_run_correlation`` if available.
    """
    if database is None or not hasattr(database, "read_paper_execution_orders"):
        return {}
    out: dict[str, object] = {}
    try:
        rows = database.read_paper_execution_orders("PAPER-STD")
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        latest = rows[0]
        out["strategy_source"] = str(
            latest.get("execution_strategy_source")
            or latest.get("signal_source")
            or "RED_BAR_V2"
        )
        out["exit_mode"] = str(latest.get("exit_mode") or "STANDARD_MULTI_FACTOR")
        out["stop_loss_pct"] = latest.get("stop_loss_pct")
        out["target_pct"] = latest.get("target_pct")
        out["entry_mode"] = latest.get("entry_mode")
        out["last_order_id"] = latest.get("order_id")
        out["last_entry_timestamp"] = latest.get("entry_timestamp")
    else:
        out["strategy_source"] = "RED_BAR_V2"
        out["exit_mode"] = "STANDARD_MULTI_FACTOR"
    return out


# Read-only constants for the headers. These match the defaults in
# execution_policy.py / automation.py / opportunity_engine.py. Surfaced
# to the UI so the user knows what the system is configured for.
DEFAULT_PAPER_CONFIG: dict[str, object] = {
    "strategy_source": "RED_BAR_V2",
    "exit_mode": "STANDARD_MULTI_FACTOR",
    "minimum_candidate_score": 65.0,
    "minimum_opportunity_score": 85.0,
    "minimum_execution_probability_pct": 70.0,
    "minimum_module_samples": 10,
    "opportunity_extension_enabled": True,
    "portfolio_risk_observational": True,
    "directional_regime_observational": True,
}


def render_active_paper_config(st: Any) -> None:
    """Render a one-line "active strategy / exit policy / thresholds"
    header above the strategy and paper-trading pages.

    The user opens the page and immediately sees the system is
    configured for:
      - strategy:    RED_BAR_V2
      - exit policy: STANDARD_MULTI_FACTOR
      - thresholds:  min_score=65, min_opp=85, min_prob=70%, min_samples=10
      - extensions:  opportunity extension ON, portfolio risk OBSERVATIONAL

    Best-effort: if the database has live order rows, the strategy and
    exit_mode are inferred from the most-recent order. Otherwise the
    defaults are shown.
    """
    database = _get_database_handle(st)
    live = _read_active_paper_config(database) if database is not None else {}

    strategy = str(
        live.get("strategy_source")
        or DEFAULT_PAPER_CONFIG["strategy_source"]
    )
    exit_mode = str(
        live.get("exit_mode")
        or DEFAULT_PAPER_CONFIG["exit_mode"]
    )
    last_order = live.get("last_order_id")

    st.caption(
        f"**Active strategy:** `{strategy}`  ·  "
        f"**Exit policy:** `{exit_mode}`  ·  "
        f"**Min candidate score:** {DEFAULT_PAPER_CONFIG['minimum_candidate_score']:.0f}  ·  "
        f"**Min opportunity score (extension):** "
        f"{DEFAULT_PAPER_CONFIG['minimum_opportunity_score']:.0f}  ·  "
        f"**Min execution probability:** "
        f"{DEFAULT_PAPER_CONFIG['minimum_execution_probability_pct']:.0f}%  ·  "
        f"**Opportunity extension:** "
        f"{'ON' if DEFAULT_PAPER_CONFIG['opportunity_extension_enabled'] else 'OFF'}  ·  "
        f"**Portfolio risk:** "
        f"{'OBSERVATIONAL' if DEFAULT_PAPER_CONFIG['portfolio_risk_observational'] else 'BLOCKING'}"
    )
    if last_order:
        st.caption(
            f"Last paper order: `{last_order}`  ·  "
            f"entry at `{live.get('last_entry_timestamp', '—')}`  ·  "
            f"stop_loss={live.get('stop_loss_pct', '—')}%  ·  "
            f"target={live.get('target_pct', '—')}%  ·  "
            f"entry_mode={live.get('entry_mode', '—')}"
        )


def _render_run_correlation_panel(st: Any) -> None:
    """Render the cross-process run correlation panel.

    Shows the most-recent run_id per process so the user can see "the
    market_collector last ran R-001, the paper_monitor last ran P-004,
    the canonical_shadow last ran R-001 (same as the collector)". This
    is the one-place-to-see "are these cycles talking to each other?"
    panel.
    """
    reader = _get_correlation_reader(st)
    if reader is None:
        return
    st.markdown("##### Cross-process run correlation")
    try:
        rows = reader()
    except Exception:  # noqa: BLE001
        st.caption("process_run_correlation read failed (DB unavailable?)")
        return
    if not rows:
        st.caption("No process correlations recorded yet.")
        return
    for row in rows:
        process = row.get("process_name", "—")
        run_id = row.get("run_id", "—")
        started = row.get("started_at", "—")
        artifacts = row.get("artifacts") or {}
        extra = ""
        correlated = artifacts.get("correlated_collector_run_id")
        if correlated:
            extra = f" · correlated with collector `{correlated}`"
        st.caption(
            f"**{process}** · run: `{run_id}` · last: {started}{extra}"
        )


def _get_correlation_reader(st: Any):
    """Same indirection as ``_get_step_evidence_reader`` but for
    ``read_all_process_run_correlations``."""
    try:
        database = st.session_state.get("step_evidence_database")
        if database is not None and hasattr(
            database, "read_all_process_run_correlations"
        ):
            return lambda: database.read_all_process_run_correlations()
    except Exception:  # noqa: BLE001
        pass
    return None


def _get_step_evidence_reader(st: Any):
    """Return a callable that reads step timelines, or None if unavailable.

    The cadence panel is invoked by the legacy and canonical V2 lifecycle
    pages. They each pass their own `database` object via the
    `_step_evidence_reader` session_state key (preferred), or via a
    ``read_step_timelines`` attribute on the layout.

    This indirection keeps the cadence panel decoupled from how the
    page acquires its database connection.
    """
    # 1) The page may have stashed a reader in session_state.
    try:
        reader = st.session_state.get("step_evidence_reader")
        if callable(reader):
            return reader
    except Exception:  # noqa: BLE001
        pass
    # 2) The page may have stored a database in session_state.
    try:
        database = st.session_state.get("step_evidence_database")
        if database is not None and hasattr(database, "read_step_timelines"):
            return lambda limit_per_step=5: database.read_step_timelines(
                limit_per_step=limit_per_step
            )
    except Exception:  # noqa: BLE001
        pass
    return None


# Fixed render order for the dependency strip. The order is meaningful:
# Paper Monitor is the upstream-most signal, the Background Orchestrator
# consumes the data the collector produces, and the Page Polling card
# reflects the user's own live-poll cadence on top of both.
_FLOW_ORDER: tuple[str, ...] = (
    "Paper Monitor",
    "Background Orchestrator",
    "Page Polling",
)


def _render_dependency_strip(st: Any) -> None:
    """Render a one-line flow indicator above the three cards.

    The strip shows the order in which data flows between the three
    components and a short label for the link between each pair. It is
    intentionally compact — it lives in a single row above the cards.
    """
    flow_cols = st.columns([1, 1, 1])
    for index, name in enumerate(_FLOW_ORDER):
        with flow_cols[index]:
            label = (
                f"**{index + 1}. {name}**"
                if index == 0
                else f"{name}"
            )
            st.markdown(label, help=_FLOW_HELP.get(name))
            # Arrow between adjacent cards
            if index < len(_FLOW_ORDER) - 1:
                next_name = _FLOW_ORDER[index + 1]
                st.caption(
                    f"↓ feeds → {next_name} · "
                    f"{_FLOW_LINKS.get((name, next_name), '?')}"
                )


def _render_error_banner(st: Any) -> None:
    """Surface a per-process "this has been failing for N minutes" banner
    at the top of the cadence panel, so a 9am user can tell at a glance
    whether a process is currently broken vs transiently red."""
    database = _get_database_handle(st)
    if database is None or not hasattr(database, "read_latest_error_per_process"):
        return
    try:
        rows = database.read_latest_error_per_process()
    except Exception:  # noqa: BLE001
        return
    if not rows:
        return
    for row in rows:
        process = row.get("process_name", "—")
        step = row.get("step_name", "—")
        age = float(row.get("error_age_seconds") or 0.0)
        message = row.get("error_message") or "(no error message recorded)"
        if age < 60:
            duration_str = f"{age:.0f}s"
        elif age < 3600:
            duration_str = f"{age / 60:.0f}m"
        else:
            duration_str = f"{age / 3600:.1f}h"
        st.error(
            f"**{process}** :: {step} — failing for **{duration_str}** · "
            f"{message[:200]}"
        )


_FLOW_HELP: dict[str, str] = {
    "Paper Monitor": (
        "5s upstream loop that checks the underlying (NIFTY 50) candle feed, "
        "runs a paper cycle, and writes a status row each iteration. Feeds "
        "the Background Orchestrator indirectly via the candle store."
    ),
    "Background Orchestrator": (
        "Runs after the market_collector completes each cycle. Processes "
        "confirmed signals into core/hybrid eligibility and writes a status "
        "row per (instrument, trading_date)."
    ),
    "Page Polling": (
        "This page's own poll loop. The interval is user-configurable (2-30s). "
        "Reads both upstreams on each iteration to surface their latest state."
    ),
}


_FLOW_LINKS: dict[tuple[str, str], str] = {
    ("Paper Monitor", "Background Orchestrator"): (
        "via candle store (indirect)"
    ),
    ("Background Orchestrator", "Page Polling"): (
        "via intelligence_pipeline_run_status table"
    ),
}


def _render_single_cadence(st: Any, cadence: UpstreamCadenceStatus) -> None:
    status, reason, hint = _resolve_status_and_reason(cadence)
    details = _build_detail_lines(cadence)
    last_success = _build_last_success_lines(cadence)
    if status == "NO DATA":
        st.metric(
            cadence.name,
            status,
            help=cadence.cadence_label,
            delta="—",
            delta_color="off",
        )
        st.caption(reason)
        return
    if status == "STALE":
        st.metric(
            cadence.name,
            status,
            delta=(
                f"{cadence.seconds_since_heartbeat:.0f}s since heartbeat"
                if cadence.seconds_since_heartbeat is not None
                else "—"
            ),
            delta_color="inverse",
        )
        st.caption(reason)
        for line in details:
            st.caption(line)
        for line in last_success:
            st.caption(line)
        return
    if status == "SUSPENDED":
        st.metric(
            cadence.name,
            "SUSPENDED",
            delta=(
                f"{cadence.seconds_since_heartbeat:.0f}s ago"
                if cadence.seconds_since_heartbeat is not None
                else "—"
            ),
            delta_color="inverse",
        )
        st.caption(reason)
        if hint:
            st.caption(hint)
        for line in details:
            st.caption(line)
        # "Last known good feed" line — shows the last time the
        # underlying feed was actually healthy, even if the most
        # recent successful cycle was a different decision.
        if (
            cadence.last_success_underlying_status
            and not cadence.last_success_underlying_status.startswith("FAIL")
            and not last_success
        ):
            since = (
                f" ({cadence.seconds_since_last_success:.0f}s ago)"
                if cadence.seconds_since_last_success is not None
                else ""
            )
            st.caption(
                f"Last known good feed: {cadence.last_success_at}{since} "
                f"({cadence.last_success_underlying_status})"
            )
        for line in last_success:
            st.caption(line)
        return
    if status == "FAILED":
        st.metric(
            cadence.name,
            status,
            delta="last cycle errored",
            delta_color="inverse",
        )
        st.caption(reason)
        if hint:
            st.caption(hint)
        for line in details:
            st.caption(line)
        for line in last_success:
            st.caption(line)
        if cadence.last_error:
            st.caption(f"Error: {cadence.last_error[:200]}")
        return
    # RUNNING / BLOCK / OK / HEALTHY: live, fresh heartbeat.
    st.metric(
        cadence.name,
        cadence.last_decision or "RUNNING",
        delta=(
            f"{cadence.seconds_since_heartbeat:.1f}s ago"
            if cadence.seconds_since_heartbeat is not None
            else "—"
        ),
    )
    st.caption(reason)
    for line in details:
        st.caption(line)
    st.caption(f"{cadence.cadence_label} · heartbeat: {cadence.last_heartbeat_at}")
    if cadence.last_signal_id:
        st.caption(f"Last signal: `{cadence.last_signal_id}`")
    if cadence.total_ms is not None:
        st.caption(f"Last cycle: {cadence.total_ms:.0f} ms")
        for stage_name, stage_ms in sorted(cadence.stages.items()):
            if stage_name == "total":
                continue
            st.caption(f"  · {stage_name}: {stage_ms:.0f} ms")


# Human-friendly names for the paper-monitor stage keys, sourced from
# red_bar_lab/execution/paper_monitor.py. Stages we don't know are
# left as-is so future stages are still visible.
_STAGE_LABELS: dict[str, str] = {
    "futures_resolution": "futures resolution",
    "v2_evaluation": "v2 evaluation",
    "exit_management": "exit management",
    "signal_publication": "signal publication",
    "readiness": "readiness (underlying + futures feed)",
    "automation": "automation (open/close orders)",
    "global_readiness": "global readiness write-back",
    "total": "total",
}


def _format_last_check(cadence: UpstreamCadenceStatus) -> str | None:
    """One-line summary of when the last feed was checked."""
    if not cadence.last_heartbeat_at:
        return None
    return f"Last feed check: {cadence.last_heartbeat_at}"


def _format_stage_timings(cadence: UpstreamCadenceStatus) -> list[str]:
    """One caption per stage, e.g. '· readiness: 12 ms (underlying + futures feed)'."""
    if not cadence.stages:
        return []
    out: list[str] = []
    for stage_name, stage_ms in sorted(cadence.stages.items()):
        if stage_name == "total":
            continue
        label = _STAGE_LABELS.get(stage_name, stage_name)
        out.append(f"  · {label}: {stage_ms:.0f} ms")
    return out


def _format_total_with_breakdown(cadence: UpstreamCadenceStatus) -> str | None:
    """One-line summary of total cycle time vs. the sum of its stages."""
    if cadence.total_ms is None:
        return None
    breakdown = sum(
        ms for stage, ms in cadence.stages.items() if stage != "total"
    )
    if breakdown:
        return f"Last cycle: {cadence.total_ms:.0f} ms total · {breakdown:.0f} ms in stages"
    return f"Last cycle: {cadence.total_ms:.0f} ms total"


def _build_detail_lines(cadence: UpstreamCadenceStatus) -> list[str]:
    """Build the standard 'when was the last check' + 'how long did each
    stage take' lines, used in SUSPENDED, FAILED, STALE, and healthy states.
    """
    lines: list[str] = []
    last_check = _format_last_check(cadence)
    if last_check:
        lines.append(last_check)
    total = _format_total_with_breakdown(cadence)
    if total:
        lines.append(total)
    lines.extend(_format_stage_timings(cadence))
    return lines


def _build_last_success_lines(cadence: UpstreamCadenceStatus) -> list[str]:
    """Build the 'last successful cycle' block.

    Only used when the *current* cycle is in trouble (SUSPENDED/FAILED/
    STALE), so the user can compare what went wrong vs. the most recent
    good cycle. Returns an empty list when no successful cycle is on
    record.
    """
    if not cadence.last_success_at:
        return []
    since = (
        f" ({cadence.seconds_since_last_success:.0f}s ago)"
        if cadence.seconds_since_last_success is not None
        else ""
    )
    lines: list[str] = [
        f"Last successful cycle: {cadence.last_success_at}{since}"
    ]
    if cadence.last_success_decision:
        lines.append(f"  decision: {cadence.last_success_decision}")
    if cadence.last_success_signal_id:
        lines.append(f"  signal: `{cadence.last_success_signal_id}`")
    if cadence.last_success_underlying_status and not (
        cadence.name == "Background Orchestrator"
    ):
        bridge = (
            f" · bridge {cadence.last_success_bridge_alignment}"
            if cadence.last_success_bridge_alignment
            else ""
        )
        reason = (
            f" · reason '{cadence.last_success_readiness_reason}'"
            if cadence.last_success_readiness_reason
            else ""
        )
        lines.append(
            f"  underlying feed: {cadence.last_success_underlying_status}"
            f"{bridge}{reason}"
        )
    if cadence.last_success_futures_status:
        lines.append(
            f"  futures feed: {cadence.last_success_futures_status}"
        )
    if cadence.name == "Background Orchestrator":
        if cadence.last_success_underlying_status:
            lines.append(
                f"  last run trading date: {cadence.last_success_underlying_status}"
            )
        if cadence.last_success_bridge_alignment:
            lines.append(
                f"  last run summary: {cadence.last_success_bridge_alignment}"
            )
        # Orchestrator-specific: run duration + counts in one compact line
        if (
            cadence.run_duration_ms is not None
            or cadence.confirmed_count is not None
        ):
            duration = (
                f"{cadence.run_duration_ms / 1000.0:.1f}s"
                if cadence.run_duration_ms is not None
                else "—"
            )
            confirmed = (
                str(cadence.confirmed_count)
                if cadence.confirmed_count is not None
                else "—"
            )
            core = (
                str(cadence.core_eligible_count)
                if cadence.core_eligible_count is not None
                else "—"
            )
            hybrid = (
                str(cadence.hybrid_eligible_count)
                if cadence.hybrid_eligible_count is not None
                else "—"
            )
            lines.append(
                f"  ran for {duration} · {confirmed} confirmed · "
                f"{core} core · {hybrid} hybrid"
            )
        if cadence.started_at:
            lines.append(f"  started at: {cadence.started_at}")
    if cadence.last_success_futures_status:
        lines.append(
            f"  futures feed: {cadence.last_success_futures_status}"
        )
    if cadence.last_success_candle_timestamp:
        age = (
            f" (was {cadence.last_success_candle_age_seconds:.1f}s old at fetch)"
            if cadence.last_success_candle_age_seconds is not None
            else ""
        )
        lines.append(
            f"  latest underlying candle fetched: "
            f"{cadence.last_success_candle_timestamp}{age}"
        )
    if cadence.last_success_readiness_ms is not None:
        lines.append(
            f"  readiness check: {cadence.last_success_readiness_ms:.0f} ms"
        )
    if cadence.last_success_total_ms is not None:
        stages = cadence.last_success_stages or {}
        breakdown = sum(
            ms for stage, ms in stages.items() if stage != "total"
        )
        if breakdown:
            lines.append(
                f"  total: {cadence.last_success_total_ms:.0f} ms · "
                f"{breakdown:.0f} ms in stages"
            )
        else:
            lines.append(f"  total: {cadence.last_success_total_ms:.0f} ms")
    for stage_name, stage_ms in sorted(
        (cadence.last_success_stages or {}).items()
    ):
        if stage_name == "total":
            continue
        label = _STAGE_LABELS.get(stage_name, stage_name)
        lines.append(f"  · {label}: {stage_ms:.0f} ms")
    return lines


# Decisions that are intentional "I refused to act this cycle" states,
# not failures. The monitor is doing its job, just conservatively.
_SUSPENDED_DECISIONS: frozenset[str] = frozenset(
    {
        "ENTRY_SUSPENDED",
        "ENTRY_HALTED",
        "PAUSED",
        "CIRCUIT_OPEN",
        "RISK_GATE",
        "RISK_BLOCKED",
        "BLOCK",
        "MARKET_CLOSED",
        "OUTSIDE_AUTOMATIC_ENTRY_HOURS",
    }
)

# Decision → human-readable hint explaining what each circuit-breaker
# state means in plain English. Sourced from the actual paper-monitor
# logic in red_bar_lab/execution/paper_monitor.py.
_SUSPENDED_REASON_HINTS: dict[str, str] = {
    "UNDERLYING_FEED_MISSING": (
        "Underlying (NIFTY 50) candle feed is missing or stale — "
        "monitor will resume on its own once the feed is healthy again"
    ),
    "PROCESS_OWNERSHIP_UNAVAILABLE": (
        "Another process owns the run — only one paper monitor may run at a time"
    ),
    "MARKET_DATA_INCOMPLETE": (
        "One or more market data inputs are missing this cycle"
    ),
    "CIRCUIT_COOLDOWN": (
        "Circuit breaker is cooling down after recent failures"
    ),
    "MARKET_CLOSED": (
        "Market is closed — this is the expected state outside trading "
        "hours, no action needed"
    ),
    "OUTSIDE_AUTOMATIC_ENTRY_HOURS": (
        "Outside automatic entry hours — this is the expected state "
        "outside the configured trading window, no action needed"
    ),
}

# Same hints, but for the case where no successful readiness check has
# ever been recorded since the monitor started. Slightly stronger
# wording makes it clear the feed has not been seen yet.
_SUSPENDED_REASON_HINTS_NEVER_SEEN: dict[str, str] = {
    "UNDERLYING_FEED_MISSING": (
        "Underlying (NIFTY 50) candle feed is missing or stale — "
        "no successful feed check has been recorded yet"
    ),
    "PROCESS_OWNERSHIP_UNAVAILABLE": (
        "Another process owns the run — no successful feed check has been "
        "recorded yet (waiting for ownership to be released)"
    ),
    "MARKET_DATA_INCOMPLETE": (
        "One or more market data inputs are missing — no successful feed "
        "check has been recorded yet"
    ),
    "CIRCUIT_COOLDOWN": (
        "Circuit breaker is cooling down — no successful feed check has "
        "been recorded yet"
    ),
    "MARKET_CLOSED": (
        "Market is closed — no successful feed check has been recorded "
        "in this session yet (expected outside trading hours)"
    ),
    "OUTSIDE_AUTOMATIC_ENTRY_HOURS": (
        "Outside automatic entry hours — no successful feed check has "
        "been recorded in this session yet (expected before the "
        "configured trading window opens)"
    ),
}


def _classify_error(error: str | None) -> str | None:
    """Return one of 'suspended', 'failed', or None.

    The paper monitor encodes its circuit-breaker reasons as
    ``<DECISION>:<REASON>`` strings. Those are *expected* states,
    not errors, and should not show up as FAILED.
    """
    if not error:
        return None
    upper = error.upper()
    for decision in _SUSPENDED_DECISIONS:
        if upper.startswith(decision):
            return "suspended"
    return "failed"


def _extract_suspension_reason(error: str | None) -> str | None:
    """Pull the ``<REASON>`` out of an ``ENTRY_SUSPENDED:<REASON>`` string."""
    if not error:
        return None
    upper = error.upper()
    for decision in _SUSPENDED_DECISIONS:
        prefix = decision + ":"
        if upper.startswith(prefix):
            return error[len(prefix):] or None
    return None


def _resolve_status_and_reason(
    cadence: UpstreamCadenceStatus,
) -> tuple[str, str, str | None]:
    """Map a cadence snapshot to a (status, reason, hint) triple.

    status — the big number the user sees
    reason — one-line explanation under the metric
    hint   — optional extra line (e.g. the upstream reason code)
    """
    if cadence.last_heartbeat_at is None:
        return (
            "NO DATA",
            f"{cadence.cadence_label} · no heartbeat received yet "
            f"(waiting for upstream to start)",
            None,
        )
    if cadence.is_stale:
        since = (
            f"{cadence.seconds_since_heartbeat:.0f}s"
            if cadence.seconds_since_heartbeat is not None
            else "—"
        )
        return (
            "STALE",
            f"Upstream is silent · last heartbeat was {since} ago, "
            f"expected at least one every {cadence.cadence_label}",
            None,
        )
    error_class = _classify_error(cadence.last_error)
    if error_class == "suspended":
        reason_code = _extract_suspension_reason(cadence.last_error)
        if reason_code is None and cadence.last_decision in _SUSPENDED_DECISIONS:
            reason_code = "—"
        never_seen = cadence.last_success_at is None
        hints_map = (
            _SUSPENDED_REASON_HINTS_NEVER_SEEN if never_seen else _SUSPENDED_REASON_HINTS
        )
        hint = None
        if reason_code and reason_code in hints_map:
            hint = (
                f"Reason ({reason_code}): {hints_map[reason_code]}"
            )
        elif reason_code:
            hint = f"Reason: {reason_code}"
        if never_seen:
            reason = (
                "Monitor is intentionally not entering this cycle — "
                "no successful readiness check has been recorded yet"
            )
        else:
            reason = (
                "Monitor is intentionally not entering this cycle — "
                "a circuit-breaker tripped to protect against bad data or risk"
            )
        return (
            "SUSPENDED",
            reason,
            hint,
        )
    if error_class == "failed":
        return (
            "FAILED",
            f"Last cycle reported an error · "
            f"decision was '{cadence.last_decision or '—'}' before failing",
            None,
        )
    if cadence.last_decision in {"MARKET_CLOSED", "OUTSIDE_AUTOMATIC_ENTRY_HOURS"}:
        never_seen = cadence.last_success_at is None
        hints_map = (
            _SUSPENDED_REASON_HINTS_NEVER_SEEN if never_seen else _SUSPENDED_REASON_HINTS
        )
        reason_code = cadence.last_decision
        hint = (
            f"Reason ({reason_code}): {hints_map[reason_code]}"
            if reason_code in hints_map
            else None
        )
        return (
            "SUSPENDED",
            "Upstream is intentionally idle — "
            + (
                "no successful readiness check has been recorded yet"
                if never_seen
                else "market state does not require action"
            ),
            hint,
        )
    # Orchestrator-specific: the "today's run has not started yet" case
    # is normal on weekends/holidays, not a fault.
    if (
        cadence.name == "Background Orchestrator"
        and cadence.last_success_readiness_reason
        == "today's run has not started yet"
    ):
        return (
            cadence.last_decision or "HEALTHY",
            (
                f"Upstream's most recent run was on "
                f"{cadence.last_success_underlying_status} · "
                "today's run has not started yet (expected on "
                "weekends/holidays or before the trading window opens)"
            ),
            None,
        )
    if cadence.last_decision in {"BLOCK", "BLOCKED", "REJECTED", "DENIED"}:
        return (
            cadence.last_decision,
            "Upstream ran but could not act · "
            "this is the most recent upstream decision, not a page fault",
            None,
        )
    if cadence.last_decision in {"OPEN", "FILLED", "EXECUTED"}:
        return (
            cadence.last_decision,
            "Upstream acted on a signal · page should auto-follow the "
            "new signal id shown below",
            None,
        )
    if cadence.last_decision in {"HEALTHY", "OK", "RUNNING"}:
        return (
            cadence.last_decision,
            "Upstream is healthy · no action needed",
            None,
        )
    if cadence.last_decision:
        return (
            cadence.last_decision,
            f"Upstream's most recent decision was '{cadence.last_decision}'",
            None,
        )
    return (
        "RUNNING",
        "Upstream is alive but has not reported a decision yet",
        None,
    )


def safe_db_read(reader: Any, *, default: Any) -> Any:
    try:
        return reader()
    except Exception:  # noqa: BLE001
        return default


def init_live_session_state(st: Any) -> None:
    if POLL_INTERVAL_KEY not in st.session_state:
        st.session_state[POLL_INTERVAL_KEY] = DEFAULT_POLL_INTERVAL_SECONDS
    if POLLS_SINCE_START_KEY not in st.session_state:
        st.session_state[POLLS_SINCE_START_KEY] = 0
    if LAST_POLL_AT_KEY not in st.session_state:
        st.session_state[LAST_POLL_AT_KEY] = None
    if LAST_SEEN_SIGNAL_ID_KEY not in st.session_state:
        st.session_state[LAST_SEEN_SIGNAL_ID_KEY] = None
    if LAST_FOLLOWED_SIGNAL_ID_KEY not in st.session_state:
        st.session_state[LAST_FOLLOWED_SIGNAL_ID_KEY] = None
    if LAST_ERROR_KEY not in st.session_state:
        st.session_state[LAST_ERROR_KEY] = None
    if STEP_TIMINGS_KEY not in st.session_state:
        st.session_state[STEP_TIMINGS_KEY] = {}
    if PAGE_STARTED_AT_KEY not in st.session_state:
        st.session_state[PAGE_STARTED_AT_KEY] = _now_iso()


def record_poll_completed(st: Any) -> None:
    st.session_state[LAST_POLL_AT_KEY] = _now_iso()
    st.session_state[POLLS_SINCE_START_KEY] = (
        int(st.session_state.get(POLLS_SINCE_START_KEY, 0)) + 1
    )


def detect_new_signal(
    st: Any,
    *,
    current_signal_id: str | None,
) -> str | None:
    """Compare current upstream signal_id against the last-seen one.

    Returns the new signal_id if it changed; otherwise None.
    """
    previous = st.session_state.get(LAST_SEEN_SIGNAL_ID_KEY)
    if current_signal_id and current_signal_id != previous:
        st.session_state[LAST_SEEN_SIGNAL_ID_KEY] = current_signal_id
        return current_signal_id
    return None


def record_follow(st: Any, signal_id: str) -> None:
    st.session_state[LAST_FOLLOWED_SIGNAL_ID_KEY] = signal_id
    st.session_state[LAST_FOLLOW_FLASH_KEY] = _now_iso()


def record_step_timing(st: Any, step_id: str, *, read_ms: float, render_ms: float) -> None:
    timings = st.session_state.get(STEP_TIMINGS_KEY, {})
    timings[step_id] = {
        "read_ms": float(read_ms),
        "render_ms": float(render_ms),
        "total_ms": float(read_ms) + float(render_ms),
        "at": _now_iso(),
    }
    st.session_state[STEP_TIMINGS_KEY] = timings


def get_step_timing(st: Any, step_id: str) -> dict[str, float | str] | None:
    timings = st.session_state.get(STEP_TIMINGS_KEY, {})
    return timings.get(step_id)


def reset_step_timings(st: Any) -> None:
    st.session_state[STEP_TIMINGS_KEY] = {}


def render_poll_controls(
    st: Any,
    *,
    on_change: Any | None = None,
) -> int:
    """Render the polling interval selectbox. Returns the chosen interval."""
    init_live_session_state(st)
    current = int(st.session_state.get(POLL_INTERVAL_KEY, DEFAULT_POLL_INTERVAL_SECONDS))
    options = [option[1] for option in POLL_INTERVAL_OPTIONS]
    if current not in options:
        options.append(current)
        options.sort()
    labels_to_values = {label: value for label, value in POLL_INTERVAL_OPTIONS}
    values_to_labels = {value: label for label, value in POLL_INTERVAL_OPTIONS}
    current_label = values_to_labels.get(current, f"{current} seconds")
    labels = list(labels_to_values.keys()) + [
        label for label, value in POLL_INTERVAL_OPTIONS if label not in labels_to_values
    ]
    if current_label not in labels:
        labels.append(current_label)
    selected_label = st.selectbox(
        "Page poll interval",
        labels,
        index=labels.index(current_label) if current_label in labels else 0,
        key="live_cadence_poll_selectbox",
    )
    chosen = labels_to_values.get(selected_label, current)
    if chosen != current:
        st.session_state[POLL_INTERVAL_KEY] = chosen
        if on_change is not None:
            on_change(chosen)
    return int(st.session_state.get(POLL_INTERVAL_KEY, chosen))


def with_step_timing(st: Any, step_id: str, renderer: Any, context: Any) -> float:
    """Run ``renderer(st, context)`` while recording read+render time.

    The total wall-clock time of the renderer is returned (milliseconds).
    """
    started = perf_counter()
    try:
        renderer(st, context)
    finally:
        elapsed_ms = (perf_counter() - started) * 1000.0
        record_step_timing(st, step_id, read_ms=0.0, render_ms=elapsed_ms)
    return elapsed_ms


def format_timing_caption(timing: dict[str, float | str] | None) -> str:
    if not timing:
        return ""
    read_ms = float(timing.get("read_ms", 0.0) or 0.0)
    render_ms = float(timing.get("render_ms", 0.0) or 0.0)
    total_ms = read_ms + render_ms
    return f"⚡ {total_ms:.0f} ms (read {read_ms:.0f} ms · render {render_ms:.0f} ms)"
