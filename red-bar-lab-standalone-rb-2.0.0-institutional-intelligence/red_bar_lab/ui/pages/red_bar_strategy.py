from red_bar_lab.ui._shared import *
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_input_preparation import prepare_completed_one_minute
from red_bar_lab.ui.strategy_setup_detection import build_red_bar_setup_state
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


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Red Bar Strategy")
    st.caption(
        "Section 1 - Data & Feature Preparation. Read-only visibility into the inputs "
        "prepared after collection and before Red Bar setup detection."
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
    option_rows = option_context.get("rows") or []

    with st.expander("View candle and feature preparation details"):
        st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)

    with st.expander("View option behaviour details"):
        if option_rows:
            st.dataframe(_arrow_safe_rows(option_rows), width="stretch", hide_index=True)
        else:
            st.warning(str(option_context.get("detail") or "Option context is unavailable."))

    with st.expander("View refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 1 preparation",
                refreshed_at=section1_refreshed,
                prepared_ms=section1_ms,
            )),
            width="stretch",
            hide_index=True,
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
    setup = build_red_bar_setup_state(
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
        "Read-only trace of reference creation, midpoint crossing and confirmation. "
        "The first unmet condition explains why the strategy has not advanced."
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
            )),
            width="stretch",
            hide_index=True,
        )

    st.info(
        "This page does not run detection, alter reference levels, fetch new option data, or change execution behavior."
    )
