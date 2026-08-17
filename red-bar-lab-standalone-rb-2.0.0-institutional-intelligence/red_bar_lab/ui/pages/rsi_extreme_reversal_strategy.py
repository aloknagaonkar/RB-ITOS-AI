from red_bar_lab.ui._shared import *
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_input_preparation import (
    latest_wilder_rsi,
    prepare_completed_one_minute,
)
from red_bar_lab.ui.strategy_setup_detection import build_rsi_setup_state
from red_bar_lab.ui.strategy_signal_resolution import build_rsi_signal_resolution
from red_bar_lab.ui.strategy_section_summary import (
    elapsed_ms,
    latest_frame_timestamp,
    latest_timestamp,
    render_option_positioning_summary,
    render_timing_caption,
    section_timer,
    timing_rows,
)


def _read_cached_candles(layout, instrument_key, trading_date):
    path = layout.candle_path("upstox", instrument_key, 1, trading_date)
    if not path.exists():
        return path, pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except Exception:
        return path, pd.DataFrame()
    return path, frame


def _trace_display(value, digits=2):
    if value in (None, ""):
        return "Unavailable"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(number):
        return "Unavailable"
    return f"{number:,.{digits}f}"


def _render_rows(rows, empty_message):
    if rows:
        st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    else:
        st.info(empty_message)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("RSI Extreme Reversal")
    st.caption(
        "Independent RSI strategy observability. Sections 1-3 are read-only and do not "
        "create signals, bundles, contracts, orders or positions."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="rsi_strategy_date"
    )
    trading_date = selected_date.isoformat()

    section1_started = section_timer()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    prepared_candles = prepare_completed_one_minute(candles, trading_date)
    option_context = build_option_behaviour_snapshot(database, instrument_key, trading_date)

    required_columns = {"timestamp", "open", "high", "low", "close"}
    columns_ready = required_columns.issubset(candles.columns)
    raw_candle_count = int(len(candles)) if columns_ready else 0
    candle_count = int(len(prepared_candles))
    latest_rsi = latest_wilder_rsi(prepared_candles, 7)
    rsi_ready = latest_rsi is not None
    structure_ready = candle_count >= 2
    readiness = "READY" if rsi_ready and structure_ready else (
        "PARTIAL" if columns_ready else "NOT READY"
    )
    section1_refreshed = latest_timestamp(
        latest_frame_timestamp(prepared_candles),
        option_context.get("latest_timestamp"),
    )
    section1_ms = elapsed_ms(section1_started)

    st.markdown("### 1. Data & Feature Preparation")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Detection readiness", readiness)
    a2.metric("Market behaviour", option_context.get("directional_bias") or "UNAVAILABLE")
    a3.metric("Option inputs", option_context.get("status") or "NOT READY")
    a4.metric("Contract safeguards", option_context.get("execution_status") or "NOT EVALUATED")

    st.markdown("#### Core strategy inputs")
    c1, c2, c3 = st.columns(3)
    c1.metric("1-minute candles", candle_count)
    c2.metric("Latest RSI(7)", f"{latest_rsi:.2f}" if latest_rsi is not None else "-")
    c3.metric("Structure inputs", "READY" if structure_ready else "NOT READY")

    render_option_positioning_summary(st, option_context.get("directional_bias"))
    render_timing_caption(st, refreshed_at=section1_refreshed, prepared_ms=section1_ms)

    preparation_rows = [
        {"stage": "Collected candle file", "status": "AVAILABLE" if candle_path.exists() else "MISSING", "detail": str(candle_path)},
        {"stage": "Required OHLC columns", "status": "READY" if columns_ready else "MISSING", "detail": ", ".join(sorted(required_columns))},
        {"stage": "RSI calculation", "status": "READY" if rsi_ready else "NOT READY", "detail": f"Wilder period=7; latest={latest_rsi if latest_rsi is not None else 'unavailable'}; completed_rows={candle_count}; raw_rows={raw_candle_count}"},
        {"stage": "Extreme thresholds", "status": "CONFIGURED", "detail": "Oversold <= 20; Overbought >= 80"},
        {"stage": "Price-structure inputs", "status": "READY" if structure_ready else "NOT READY", "detail": "Current OHLC plus previous completed candle high/low"},
        {"stage": "Confirmation policy", "status": "CONFIGURED", "detail": "Cross-back + candle direction + structure reclaim/break + no fresh adverse extreme"},
    ]

    with st.expander("View candle and feature preparation details"):
        st.dataframe(_arrow_safe_rows(preparation_rows), width="stretch", hide_index=True)
    with st.expander("View option behaviour details"):
        _render_rows(option_context.get("rows") or [], str(option_context.get("detail") or "Option context is unavailable."))
    with st.expander("View refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 1 preparation",
                refreshed_at=section1_refreshed,
                prepared_ms=section1_ms,
            )), width="stretch", hide_index=True,
        )
    with st.expander("View preparation flow"):
        st.code(
            "1-minute candles collected\n"
            "-> OHLC data normalized\n"
            "-> RSI(7) series calculated\n"
            "-> Oversold / overbought state prepared\n"
            "-> Previous-candle high/low prepared\n"
            "-> Reversal confirmation inputs made available\n"
            "-> Stored option behaviour added as supporting evidence",
            language=None,
        )

    if readiness == "READY":
        st.success("RSI and structure inputs are prepared for extreme/reversal evaluation.")
    elif readiness == "PARTIAL":
        st.warning("Candle data exists, but RSI or previous-candle structure inputs are incomplete.")
    else:
        st.error("RSI input preparation cannot start until cached 1-minute OHLC data is available.")

    section2_started = section_timer()
    setup = build_rsi_setup_state(
        prepared_candles,
        instrument_key,
        option_bias=option_context.get("directional_bias"),
    )
    section2_refreshed = latest_timestamp(latest_frame_timestamp(prepared_candles))
    section2_ms = elapsed_ms(section2_started)

    st.markdown("### 2. Strategy State & Setup Detection")
    st.caption(
        "Read-only trace using the production RSI detector: extreme arm, cross-back, "
        "candle direction, structure reclaim/break and adverse-extreme protection."
    )
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Engine state", setup["status"])
    s2.metric("Direction", setup["direction"])
    s3.metric("Setup ID", setup["setup_id"])
    s4.metric("Option alignment", setup["option_alignment"])
    st.write(f"**Waiting for:** {setup['waiting_for']}")
    st.write(f"**Current blocker:** {setup['blocker']}")
    render_timing_caption(st, refreshed_at=section2_refreshed, prepared_ms=section2_ms)

    with st.expander("View condition-by-condition trace"):
        st.dataframe(_arrow_safe_rows(setup["rows"]), width="stretch", hide_index=True)

    trace = setup.get("decision_trace") or {}
    with st.expander("How was the current RSI decision made?", expanded=False):
        if not trace or not trace.get("checks"):
            st.info(str(trace.get("first_unmet_condition") or "Sufficient completed candle and RSI data is unavailable."))
            st.write(f"**Next step:** {trace.get('next_step') or 'Wait for enough completed 1-minute candles.'}")
        else:
            previous_candle = trace.get("previous_candle") or {}
            current_candle = trace.get("current_candle") or {}
            recent_extreme = trace.get("recent_extreme") or {}
            st.caption(f"Evaluation timestamp: {trace.get('evaluation_timestamp') or 'Unavailable'}")
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Evaluated path", trace.get("path") or "UNDECIDED")
            e2.metric("Previous RSI", _trace_display(previous_candle.get("rsi")))
            e3.metric("Current RSI", _trace_display(current_candle.get("rsi")))
            e4.metric("Final outcome", trace.get("final_outcome") or "Unavailable")
            candle_rows = []
            for label, candle in (("Previous", previous_candle), ("Current", current_candle)):
                candle_rows.append({
                    "candle": label,
                    "timestamp": str(candle.get("timestamp") or "Unavailable"),
                    "open": _trace_display(candle.get("open")),
                    "high": _trace_display(candle.get("high")),
                    "low": _trace_display(candle.get("low")),
                    "close": _trace_display(candle.get("close")),
                    "rsi": _trace_display(candle.get("rsi")),
                })
            st.dataframe(_arrow_safe_rows(candle_rows), width="stretch", hide_index=True)
            st.caption(
                f"Recent RSI window: {int(recent_extreme.get('window_candles') or 0)} candles · "
                f"lowest={_trace_display(recent_extreme.get('lowest_rsi'))} · "
                f"highest={_trace_display(recent_extreme.get('highest_rsi'))}"
            )
            st.dataframe(_arrow_safe_rows(trace.get("checks") or []), width="stretch", hide_index=True)
            st.write(f"**First unmet condition:** {trace.get('first_unmet_condition') or 'Unavailable'}")
            st.write(f"**Final outcome:** {trace.get('final_outcome') or 'Unavailable'}")
            st.write(f"**Next step:** {trace.get('next_step') or 'Unavailable'}")

    with st.expander("View Section 2 refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 2 setup trace",
                refreshed_at=section2_refreshed,
                prepared_ms=section2_ms,
            )), width="stretch", hide_index=True,
        )

    section3_started = section_timer()
    resolution = build_rsi_signal_resolution(
        candles=prepared_candles,
        database=database,
        settings=settings,
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    section3_ms = elapsed_ms(section3_started)

    st.markdown("### 3. RSI Signal Normalization & Bundle Lifecycle")
    st.caption(
        "The bundle contains only RSI Extreme Reversal evidence. Red Bar and DRI signals, "
        "bundles, cooldowns and consumption states do not affect this RSI-owned lifecycle."
    )
    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Signal state", resolution["signal_state"])
    n2.metric("Normalized intent", resolution["normalized_intent"])
    n3.metric("Bundle state", resolution["bundle_state"])
    n4.metric("Final result", resolution["final_outcome"])

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Strategy owner", resolution["strategy_owner"])
    b2.metric("Bundle ID", resolution["bundle_id"])
    b3.metric("Signal age", resolution["signal_age"])
    b4.metric("Entry capacity", resolution["entry_capacity"])

    st.write(f"**Decision reason:** {resolution['decision_reason']}")
    st.write(f"**Applied lifecycle rule:** {resolution['applied_rule']}")
    st.write(f"**Next architectural step:** {resolution['next_step']}")
    render_timing_caption(st, refreshed_at=resolution.get("refreshed_at"), prepared_ms=section3_ms)

    with st.expander("View raw RSI signal"):
        _render_rows(resolution["raw_rows"], "No confirmed RSI signal is available for the selected date.")
    with st.expander("View normalized RSI trading intention"):
        _render_rows(resolution["normalization_rows"], "Normalization is waiting for a confirmed RSI signal.")
    with st.expander("View RSI freshness and duplicate checks"):
        _render_rows(resolution["freshness_rows"], "Freshness cannot be evaluated without an RSI signal.")
    with st.expander("View RSI bundle"):
        _render_rows(resolution["bundle_rows"], "No RSI bundle can be built until the complete confirmation chain passes.")
    with st.expander("View RSI entry-slot lifecycle"):
        _render_rows(resolution["lifecycle_rows"], "No persisted RSI execution events were found; entry capacity remains unconsumed.")
    with st.expander("How was this RSI bundle created?"):
        st.write(f"**Strategy owner:** {resolution['strategy_owner']}")
        st.write(f"**Signal ID:** {resolution['signal_id']}")
        st.write(f"**Bundle ID:** {resolution['bundle_id']}")
        st.write(f"**Normalized intention:** {resolution['normalized_intent']}")
        st.write(f"**Entry capacity:** {resolution['entry_capacity']}")
        st.write(f"**Applied rule:** {resolution['applied_rule']}")
        st.write(f"**Outcome:** {resolution['final_outcome']}")
        st.write(f"**Reason:** {resolution['decision_reason']}")
        st.write(f"**Next step:** {resolution['next_step']}")
    with st.expander("View Section 3 refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 3 RSI bundle lifecycle",
                refreshed_at=resolution.get("refreshed_at"),
                prepared_ms=section3_ms,
            )), width="stretch", hide_index=True,
        )

    st.info(
        "Sections 1-3 are read-only. The displayed bundle is constructed in memory for "
        "observability; opening this page does not persist, forward, consume or execute it."
    )
