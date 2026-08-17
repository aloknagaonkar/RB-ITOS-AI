from red_bar_lab.ui._shared import *
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_input_preparation import prepare_completed_one_minute
from red_bar_lab.ui.strategy_red_bar_bundle import build_red_bar_bundle_resolution
from red_bar_lab.ui.strategy_red_bar_setup import build_red_bar_owned_setup_state
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


def _render_rows(rows, empty_message):
    if rows:
        st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    else:
        st.info(empty_message)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Red Bar Strategy")
    st.caption(
        "Independent Red Bar strategy observability. Sections 1-3 are read-only and do "
        "not create signals, bundles, contracts, orders or positions."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="red_bar_strategy_date"
    )
    trading_date = selected_date.isoformat()

    section1_started = section_timer()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    prepared_candles = prepare_completed_one_minute(candles, trading_date)
    levels = database.read_reference_levels(instrument_key, trading_date)
    option_context = build_option_behaviour_snapshot(database, instrument_key, trading_date)
    red_refs = [
        row for row in levels
        if str(row.get("level_type") or "") == "NEXT_RED_CANDLE"
    ]
    red_ref = red_refs[-1] if red_refs else {}

    required_columns = {"timestamp", "open", "high", "low", "close"}
    candle_columns_ready = required_columns.issubset(candles.columns)
    raw_candle_count = int(len(candles)) if candle_columns_ready else 0
    candle_count = int(len(prepared_candles))
    normalized_ready = bool(candle_count)
    reference_ready = bool(red_ref)
    readiness = "READY" if normalized_ready and reference_ready else (
        "PARTIAL" if normalized_ready else "NOT READY"
    )
    section1_refreshed = latest_timestamp(
        latest_frame_timestamp(prepared_candles),
        option_context.get("latest_timestamp"),
        red_ref.get("source_timestamp"),
        red_ref.get("updated_at"),
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
    c2.metric("OHLC normalized", "YES" if normalized_ready else "NO")
    c3.metric("Red Bar reference", "READY" if reference_ready else "PENDING")

    render_option_positioning_summary(st, option_context.get("directional_bias"))
    render_timing_caption(st, refreshed_at=section1_refreshed, prepared_ms=section1_ms)

    rows = [
        {"stage": "Collected candle file", "status": "AVAILABLE" if candle_path.exists() else "MISSING", "detail": str(candle_path)},
        {"stage": "Required OHLC columns", "status": "READY" if candle_columns_ready else "MISSING", "detail": ", ".join(sorted(required_columns))},
        {"stage": "Session candle normalization", "status": "READY" if normalized_ready else "NOT READY", "detail": f"raw={raw_candle_count}; completed_valid={candle_count}"},
        {"stage": "NEXT_RED_CANDLE reference", "status": "READY" if reference_ready else "PENDING", "detail": str(red_ref.get("source_timestamp") or "Not detected/persisted")},
        {
            "stage": "Reference geometry",
            "status": "READY" if reference_ready else "PENDING",
            "detail": (
                f"High={red_ref.get('source_high')}, Low={red_ref.get('source_low')}, "
                f"Midpoint={red_ref.get('level_value') or red_ref.get('midpoint')}"
                if reference_ready else "Awaiting Red Bar reference"
            ),
        },
    ]

    with st.expander("View candle and feature preparation details"):
        st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
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
            "-> Session candles normalized\n"
            "-> Opening and previous-session context loaded\n"
            "-> Red candle candidates evaluated\n"
            "-> NEXT_RED_CANDLE reference calculated\n"
            "-> High, low and midpoint persisted\n"
            "-> Stored option behaviour added as supporting evidence",
            language=None,
        )

    if readiness == "READY":
        st.success("Red Bar strategy inputs are prepared for setup detection.")
    elif readiness == "PARTIAL":
        st.warning("Candle inputs are available, but the NEXT_RED_CANDLE reference is not yet persisted.")
    else:
        st.error("Red Bar input preparation cannot start until cached 1-minute OHLC data is available.")

    section2_started = section_timer()
    setup = build_red_bar_owned_setup_state(
        database,
        instrument_key,
        trading_date,
        reference=red_ref,
        option_bias=option_context.get("directional_bias"),
    )
    section2_refreshed = latest_timestamp(
        red_ref.get("source_timestamp"),
        red_ref.get("updated_at"),
        *[
            row.get("observed")
            for row in setup.get("rows", [])
            if row.get("observed") not in (None, "", "Not persisted", "Unavailable", "Not detected", "Not confirmed")
        ],
    )
    section2_ms = elapsed_ms(section2_started)

    st.markdown("### 2. Strategy State & Setup Detection")
    st.caption(
        "Read-only trace of Red Bar-owned reference creation, midpoint crossing and confirmation. "
        "RSI and DRI signal attempts are excluded."
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
    with st.expander("View Section 2 refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 2 setup trace",
                refreshed_at=section2_refreshed,
                prepared_ms=section2_ms,
            )), width="stretch", hide_index=True,
        )

    section3_started = section_timer()
    bundle = build_red_bar_bundle_resolution(
        database=database,
        instrument_key=instrument_key,
        trading_date=trading_date,
        reference=red_ref,
    )
    section3_ms = elapsed_ms(section3_started)

    st.markdown("### 3. Red Bar Signal Normalization & Bundle Lifecycle")
    st.caption(
        "The bundle contains only Red Bar reference, midpoint-cross and confirmation evidence. "
        "RSI and DRI signals, cooldowns and consumption states do not affect it."
    )
    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Signal state", bundle["signal_state"])
    n2.metric("Normalized intent", bundle["normalized_intent"])
    n3.metric("Bundle state", bundle["bundle_state"])
    n4.metric("Final result", bundle["final_outcome"])

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Strategy owner", bundle["strategy_owner"])
    b2.metric("Bundle ID", bundle["bundle_id"])
    b3.metric("Signal age", bundle["signal_age"])
    b4.metric("Entry capacity", bundle["entry_capacity"])

    st.write(f"**Decision reason:** {bundle['decision_reason']}")
    st.write(f"**Applied lifecycle rule:** {bundle['applied_rule']}")
    st.write(f"**Next architectural step:** {bundle['next_step']}")
    render_timing_caption(st, refreshed_at=bundle.get("refreshed_at"), prepared_ms=section3_ms)

    with st.expander("View confirmed Red Bar event"):
        _render_rows(bundle["signal_rows"], "No confirmed Red Bar event is available for the selected date.")
    with st.expander("View Red Bar bundle"):
        _render_rows(bundle["bundle_rows"], "No Red Bar bundle can be built until reference, cross and confirmation are complete.")
    with st.expander("View Red Bar consumption lifecycle"):
        _render_rows(bundle["lifecycle_rows"], "No strategy-and-bundle-scoped Red Bar execution events were found.")
    with st.expander("How was this Red Bar bundle created?"):
        st.write(f"**Strategy owner:** {bundle['strategy_owner']}")
        st.write(f"**Signal ID:** {bundle['signal_id']}")
        st.write(f"**Bundle ID:** {bundle['bundle_id']}")
        st.write(f"**Normalized intention:** {bundle['normalized_intent']}")
        st.write(f"**Entry capacity:** {bundle['entry_capacity']}")
        st.write(f"**Applied rule:** {bundle['applied_rule']}")
        st.write(f"**Outcome:** {bundle['final_outcome']}")
        st.write(f"**Reason:** {bundle['decision_reason']}")
        st.write(f"**Next step:** {bundle['next_step']}")
    with st.expander("View Section 3 refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 3 Red Bar bundle lifecycle",
                refreshed_at=bundle.get("refreshed_at"),
                prepared_ms=section3_ms,
            )), width="stretch", hide_index=True,
        )

    st.info(
        "Sections 1-3 are read-only. The displayed Red Bar bundle is constructed in memory "
        "for observability; opening this page does not persist, forward, consume or execute it."
    )
