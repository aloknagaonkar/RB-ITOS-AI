from red_bar_lab.ui._shared import *
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_setup_detection import build_dri_setup_state
from red_bar_lab.ui.strategy_input_preparation import (
    prepare_completed_five_minute,
    prepare_completed_one_minute,
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
    st.subheader("Directional Regime Intelligence")
    st.caption(
        "Section 1 - Data & Feature Preparation. Read-only visibility into the "
        "multi-timeframe, directional and option-behaviour inputs prepared before regime classification."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="directional_regime_strategy_date"
    )
    trading_date = selected_date.isoformat()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    one_minute = prepare_completed_one_minute(candles, trading_date)
    five_minute = prepare_completed_five_minute(one_minute, trading_date)
    option_context = build_option_behaviour_snapshot(
        database, instrument_key, trading_date
    )

    required_columns = {"timestamp", "open", "high", "low", "close"}
    columns_ready = required_columns.issubset(candles.columns)
    raw_one_minute_count = int(len(candles)) if columns_ready else 0
    one_minute_count = int(len(one_minute))
    five_minute_count = int(len(five_minute))
    volume_ready = bool("volume" in candles.columns and pd.to_numeric(
        candles.get("volume"), errors="coerce"
    ).notna().any()) if not candles.empty else False
    structure_ready = five_minute_count >= 35
    indicator_window_ready = one_minute_count >= 35 and five_minute_count >= 35
    readiness = "READY" if indicator_window_ready else (
        "PARTIAL" if columns_ready else "NOT READY"
    )

    st.markdown("### 1. Data & Feature Preparation")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Detection readiness", readiness)
    a2.metric("Market behaviour", option_context.get("directional_bias") or "UNAVAILABLE")
    a3.metric("Option inputs", option_context.get("status") or "NOT READY")
    a4.metric("Contract safeguards", option_context.get("execution_status") or "NOT EVALUATED")

    st.markdown("#### Core strategy inputs")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("1-minute candles", one_minute_count)
    c2.metric("5-minute candles", five_minute_count)
    c3.metric("Volume input", "READY" if volume_ready else "UNAVAILABLE")
    c4.metric("Indicator window", "READY" if indicator_window_ready else "PARTIAL")

    st.markdown("#### Post-collection preparation flow")
    st.code(
        "Price and volume collected\n"
        "-> 1-minute candles normalized\n"
        "-> 5-minute candles aligned\n"
        "-> Market structure inputs prepared\n"
        "-> EMA slope / acceleration windows prepared\n"
        "-> DMI / ADX and ATR windows prepared\n"
        "-> Stored option behaviour added as supporting evidence\n"
        "-> Directional regime feature set made available",
        language=None,
    )

    rows = [
        {
            "stage": "Collected candle file",
            "status": "AVAILABLE" if candle_path.exists() else "MISSING",
            "detail": str(candle_path),
        },
        {
            "stage": "Required OHLC columns",
            "status": "READY" if columns_ready else "MISSING",
            "detail": ", ".join(sorted(required_columns)),
        },
        {
            "stage": "1-minute normalization",
            "status": "READY" if one_minute_count else "NOT READY",
            "detail": f"raw={raw_one_minute_count}; completed_valid={one_minute_count}",
        },
        {
            "stage": "5-minute alignment",
            "status": "READY" if five_minute_count else "NOT READY",
            "detail": f"{five_minute_count} completed/resampled rows",
        },
        {
            "stage": "Price-structure window",
            "status": "READY" if structure_ready else "PARTIAL",
            "detail": f"Production requirement: 35 completed 5-minute candles; available={five_minute_count}",
        },
        {
            "stage": "Indicator lookback window",
            "status": "READY" if indicator_window_ready else "PARTIAL",
            "detail": f"Production requirement: 1m>=35 and 5m>=35; available={one_minute_count}/{five_minute_count}",
        },
        {
            "stage": "Volume context",
            "status": "READY" if volume_ready else "UNAVAILABLE",
            "detail": "Collected volume column present and populated" if volume_ready else "No populated volume input",
        },
    ]
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)

    st.markdown("#### Option Behaviour Inputs")
    st.caption(
        "Option positioning enriches the price regime with aggregate OI, change-in-OI and PCR evidence. "
        "DRI price/volume structure remains the primary directional authority."
    )
    option_rows = option_context.get("rows") or []
    if option_rows:
        st.dataframe(_arrow_safe_rows(option_rows), width="stretch", hide_index=True)
    else:
        st.warning(str(option_context.get("detail") or "Option context is unavailable."))

    if readiness == "READY":
        st.success("Directional feature inputs are prepared for regime classification.")
    elif readiness == "PARTIAL":
        st.warning(
            "Base candles are available, but additional completed 5-minute history is needed for all directional features."
        )
    else:
        st.error("Directional input preparation cannot start until cached 1-minute OHLC data is available.")

    setup = build_dri_setup_state(
        settings.runs_root,
        instrument_key,
        trading_date,
        option_bias=option_context.get("directional_bias"),
    )
    st.markdown("### 2. Strategy State & Setup Detection")
    st.caption(
        "Read-only trace of the persisted DRI lifecycle: regime snapshot, transition, "
        "fresh setup signal and setup bundle."
    )
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Engine state", setup["status"])
    s2.metric("Direction", setup["direction"])
    s3.metric("Setup ID", setup["setup_id"])
    s4.metric("Option alignment", setup["option_alignment"])
    st.write(f"**Waiting for:** {setup['waiting_for']}")
    st.write(f"**Current blocker:** {setup['blocker']}")
    st.dataframe(_arrow_safe_rows(setup["rows"]), width="stretch", hide_index=True)

    st.info(
        "This page does not classify a regime, fetch new option data, create native DRI signals, or change execution authority."
    )
