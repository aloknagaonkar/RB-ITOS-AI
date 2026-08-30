from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter as _perf_counter
from typing import Any

import streamlit as st

StepRenderer = Callable[[Any, "LifecycleContext"], None]
StepExpanderChoice = str  # "open" | "closed"


@dataclass(frozen=True)
class LifecycleStep:
    step_id: str
    title: str
    description: str
    renderer: StepRenderer
    timing_mode: str = "wrapped"  # "wrapped" | "raw"


@dataclass
class LifecycleContext:
    """Per-page state passed to every step renderer.

    Attributes:
        settings: The RedBarSettings instance.
        layout: The ArtifactLayout instance.
        database: The RedBarDatabase facade.
        token: The Upstox access token (paper-only, never persisted).
        underlying_name: Display name of the selected underlying.
        instrument_key: Provider-side instrument key.
        interval: Selected candle interval.
        trading_date: ISO date string the user selected.
        signal_id: The currently selected signal (may be None).
    """

    settings: Any
    layout: Any
    database: Any
    token: str
    underlying_name: str
    instrument_key: str
    interval: int
    trading_date: str
    signal_id: str | None


STEPPER_STATE_KEY = "lifecycle_stepper_index"
ALL_PAGE_ANCHOR_PREFIX = "lifecycle_section_"


def _step_button_key(stepper_key: str, suffix: str) -> str:
    return f"{stepper_key}_{suffix}"


def _safe_run_step(st: Any, step: LifecycleStep, context: LifecycleContext) -> None:
    try:
        step.renderer(st, context)
    except Exception as exc:  # noqa: BLE001 - the page must stay usable
        st.error(
            f"Section '{step.step_id}' raised an exception: "
            f"{type(exc).__name__}: {exc}"
        )


def step_timing_label(st: Any, step: LifecycleStep) -> str:
    """Read the latest timing for this step from session state."""
    from red_bar_lab.ui.live_cadence import (
        STEP_TIMINGS_KEY,
        format_timing_caption,
    )

    timings = st.session_state.get(STEP_TIMINGS_KEY) or {}
    timing = timings.get(step.step_id)
    return format_timing_caption(timing)


def _run_step_with_timing(
    st: Any, step: LifecycleStep, context: LifecycleContext
) -> None:
    """Run a step's renderer with read+render timing.

    The render is captured with ``perf_counter`` and stored in
    ``st.session_state[STEP_TIMINGS_KEY][step.step_id]``. The total
    wall-clock time of the renderer is what we measure — read time
    is included in the render time, because most renderers do both
    in one function call.
    """
    from time import perf_counter

    from red_bar_lab.ui.live_cadence import (
        STEP_TIMINGS_KEY,
        record_step_timing,
    )

    started = perf_counter()
    try:
        step.renderer(st, context)
    except Exception as exc:  # noqa: BLE001 - never break the page
        st.error(
            f"Section '{step.step_id}' raised an exception: "
            f"{type(exc).__name__}: {exc}"
        )
    finally:
        elapsed_ms = (perf_counter() - started) * 1000.0
        record_step_timing(st, step.step_id, read_ms=0.0, render_ms=elapsed_ms)
        # Touch the session_state key so the timing probe is visible
        # to tests even if no other widget interaction happens.
        _ = st.session_state.get(STEP_TIMINGS_KEY)


def render_lifecycle(
    steps: list[LifecycleStep],
    context: LifecycleContext,
    *,
    stepper_key: str,
    banner_renderer: Callable[[Any, LifecycleContext], None] | None = None,
) -> None:
    """Render a 12-step lifecycle page with prev/next navigation.

    Each call mutates ``st.session_state[stepper_key]`` to the current
    step index, so the user can navigate back and forth without losing
    their place on a Streamlit rerun.
    """
    if not steps:
        st.error("Lifecycle page has no steps configured.")
        return

    total = len(steps)
    if stepper_key not in st.session_state:
        st.session_state[stepper_key] = 0
    current = int(st.session_state[stepper_key])
    if current < 0:
        current = 0
        st.session_state[stepper_key] = 0
    if current >= total:
        current = total - 1
        st.session_state[stepper_key] = current

    if banner_renderer is not None:
        banner_renderer(st, context)

    _render_progress_bar(st, current=current, total=total)
    _render_step_header(st, step=steps[current], index=current, total=total)
    _render_navigation(st, steps=steps, current=current, stepper_key=stepper_key)
    _safe_run_step(st, steps[current], context)


def render_lifecycle_all(
    steps: list[LifecycleStep],
    context: LifecycleContext,
    *,
    page_key: str,
    banner_renderer: Callable[[Any, LifecycleContext], None] | None = None,
    expander_default: StepExpanderChoice = "open",
    show_anchors: bool = True,
    show_timings: bool = False,
    process_name: str | None = None,
    database: Any | None = None,
    run_id: str | None = None,
) -> None:
    """Render all steps on a single scrollable page.

    Each step is rendered as a numbered subheader with an optional
    ``st.expander`` wrapper. The user can collapse sections they don't
    need. No prev/next buttons.

    Args:
        steps: The full ordered list of steps to render.
        context: The lifecycle context.
        page_key: Unique key prefix for session state — keep it stable
            per page so a Streamlit rerun preserves collapse state.
        banner_renderer: Optional banner renderer (title, warnings, date
            picker, signal selector). The framework does not render
            any banner of its own.
        expander_default: "open" (default) or "closed" — controls
            whether each section starts expanded or collapsed.
        show_anchors: If true, an anchor id is added above each
            section so it can be linked to via query params.
        show_timings: If true, each step's renderer is wrapped in a
            perf_counter probe and the read+render time is shown
            next to the section header. Times are stored in
            ``st.session_state[STEP_TIMINGS_KEY]`` (managed by
            ``red_bar_lab.ui.live_cadence``).
        process_name: If set, each step render is wrapped in a
            ``with_step_evidence`` so it shows up in the
            ``process_evidence`` table. Defaults to None (no
            evidence). Set to e.g. ``"v2_lifecycle_render"``.
        database: The RedBarDatabase used as the evidence target.
            Required when ``process_name`` is set.
        run_id: The run_id shared with the upstream collector. When
            set, all 12 lifecycle step evidence rows share the same
            run_id so the user can see "this page render corresponds
            to upstream run R-001".
    """
    if not steps:
        st.error("Lifecycle page has no steps configured.")
        return

    if banner_renderer is not None:
        banner_renderer(st, context)

    if expander_default not in {"open", "closed"}:
        expander_default = "open"

    _render_overview(st, steps=steps, page_key=page_key, show_anchors=show_anchors)
    st.divider()

    # Resolve evidence instrumentation once per render.
    evidence_writer = _build_evidence_writer(database) if process_name else None

    for index, step in enumerate(steps):
        label = f"{index + 1}. {step.title}"
        if show_timings:
            timing_label = step_timing_label(st, step)
            if timing_label:
                label = f"{label}  ·  {timing_label}"
        if show_anchors:
            st.markdown(
                f"<a id='{ALL_PAGE_ANCHOR_PREFIX}{step.step_id}'></a>",
                unsafe_allow_html=True,
            )
        with st.expander(label, expanded=(expander_default == "open")):
            st.caption(step.description)
            _run_step_with_evidence(
                st,
                step,
                context,
                process_name=process_name,
                evidence_writer=evidence_writer,
                run_id=run_id,
                show_timings=show_timings,
            )


def _build_evidence_writer(database: Any) -> Callable[..., Any] | None:
    """Build a per-page evidence writer, or None if the database
    doesn't expose the right interface."""
    if database is None or not hasattr(database, "write_step_evidence"):
        return None
    from red_bar_lab.observability.evidence import ProcessEvidenceWriter

    return ProcessEvidenceWriter(database)


def _run_step_with_evidence(
    st: Any,
    step: LifecycleStep,
    context: LifecycleContext,
    *,
    process_name: str | None,
    evidence_writer: Callable[..., Any] | None,
    run_id: str | None,
    show_timings: bool,
) -> None:
    """Run a step with optional evidence instrumentation.

    If ``evidence_writer`` is None (i.e. process_name wasn't passed), this
    is identical to the original behavior. Otherwise, the step's render
    call is wrapped in a ``with_step_evidence`` so it lands in
    ``process_evidence`` and shows up in the cadence panel's run
    timeline.
    """
    if evidence_writer is None or process_name is None:
        if show_timings:
            _run_step_with_timing(st, step, context)
        else:
            _safe_run_step(st, step, context)
        return
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = _perf_counter()
    try:
        if show_timings:
            _run_step_with_timing(st, step, context)
        else:
            _safe_run_step(st, step, context)
        duration_ms = (_perf_counter() - started_perf) * 1000.0
        try:
            evidence_writer(
                process_name=process_name,
                run_id=run_id or "no-run",
                step_name=f"step:{step.step_id}",
                parent_step=process_name,
                started_at=started_at,
                status="OK",
                duration_ms=duration_ms,
                artifacts={"title": step.title},
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        duration_ms = (_perf_counter() - started_perf) * 1000.0
        try:
            evidence_writer(
                process_name=process_name,
                run_id=run_id or "no-run",
                step_name=f"step:{step.step_id}",
                parent_step=process_name,
                started_at=started_at,
                status="ERROR",
                duration_ms=duration_ms,
                error_message=f"{type(exc).__name__}: {exc}"[:500],
                artifacts={"title": step.title},
            )
        except Exception:  # noqa: BLE001
            pass
        raise


def _render_progress_bar(st: Any, *, current: int, total: int) -> None:
    progress = (current + 1) / total if total else 0.0
    st.progress(min(max(progress, 0.0), 1.0), text=f"Step {current + 1} of {total}")


def _render_step_header(st: Any, *, step: LifecycleStep, index: int, total: int) -> None:
    st.subheader(f"{index + 1}. {step.title}")
    st.caption(step.description)


def _render_navigation(
    st: Any,
    *,
    steps: list[LifecycleStep],
    current: int,
    stepper_key: str,
) -> None:
    cols = st.columns([1, 1, 6])
    prev_disabled = current == 0
    next_disabled = current == len(steps) - 1
    prev_key = _step_button_key(stepper_key, "prev")
    next_key = _step_button_key(stepper_key, "next")
    with cols[0]:
        if st.button("◀ Previous", key=prev_key, disabled=prev_disabled):
            st.session_state[stepper_key] = current - 1
            st.rerun()
    with cols[1]:
        if st.button("Next ▶", key=next_key, disabled=next_disabled):
            st.session_state[stepper_key] = current + 1
            st.rerun()
    with cols[2]:
        st.caption(
            f"{steps[current].title} · "
            f"{current + 1}/{len(steps)}"
        )


def _render_overview(
    st: Any,
    *,
    steps: list[LifecycleStep],
    page_key: str,
    show_anchors: bool,
) -> None:
    """Render a small table-of-contents / section index at the top of the page."""
    st.markdown("##### Sections on this page")
    jump_cols = st.columns(min(len(steps), 4))
    for index, step in enumerate(steps):
        column = jump_cols[index % len(jump_cols)]
        with column:
            if show_anchors:
                if st.button(
                    f"{index + 1}. {step.title}",
                    key=f"{page_key}_jump_{step.step_id}",
                    use_container_width=True,
                ):
                    st.query_params["section"] = step.step_id
                    st.rerun()
            else:
                column.caption(f"{index + 1}. {step.title}")


def make_step(
    *,
    step_id: str,
    title: str,
    description: str,
    renderer: StepRenderer,
) -> LifecycleStep:
    return LifecycleStep(
        step_id=step_id,
        title=title,
        description=description,
        renderer=renderer,
    )


def signal_selector(
    st: Any,
    database: Any,
    *,
    instrument_key: str,
    trading_date: str,
    selectbox_key: str,
) -> str | None:
    """Render a signal selector for the lifecycle page. Returns the selected signal_id."""
    rows = _safe_read(
        st,
        lambda: database.read_signal_attempts(instrument_key, trading_date),
        default=[],
    )
    if not rows:
        st.info("No signals are stored for this date yet.")
        return None
    ordered = sorted(
        rows,
        key=lambda row: str(row.get("confirmation_timestamp") or ""),
        reverse=True,
    )
    options: dict[str, str | None] = {}
    for row in ordered:
        signal_id = row.get("signal_id")
        if not signal_id:
            continue
        label = (
            f"{signal_id} · {row.get('direction')} · "
            f"{row.get('level_type')} · "
            f"{row.get('confirmation_timestamp')}"
        )
        options[label] = str(signal_id)
    if not options:
        st.info("No signal attempts with a signal_id are available yet.")
        return None
    selected_label = st.selectbox(
        "Select signal",
        list(options.keys()),
        key=selectbox_key,
    )
    return options[selected_label]


def _safe_read(st: Any, reader: Callable[[], Any], *, default: Any) -> Any:
    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 - never break the page
        st.warning(
            f"Database read failed: {type(exc).__name__}: {exc}. "
            "Showing empty state."
        )
        return default


def safe_read(reader: Callable[[], Any], *, default: Any) -> Any:
    try:
        return reader()
    except Exception:  # noqa: BLE001
        return default
