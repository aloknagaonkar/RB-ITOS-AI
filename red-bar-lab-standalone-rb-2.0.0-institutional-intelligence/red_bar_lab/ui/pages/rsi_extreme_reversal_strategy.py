from red_bar_lab.ui._shared import *
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_input_preparation import (
    latest_wilder_rsi,
    prepare_completed_one_minute,
)
from red_bar_lab.ui.strategy_setup_detection import build_rsi_setup_state


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
    st.subheader("RSI Extreme Reversal")
    st.caption(
        "Section 1 - Data & Feature Preparation. Read-only visibility into the candle, "
        "RSI, structure and option-behaviour inputs prepared before reversal evaluation."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="rsi_strategy_date"
    )
    trading_date = selected_date.isoformat()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    prepared_candles = prepare_completed_one_minute(candles, trading_date)
    option_context = build_option_behaviour_snapshot(
        database, instrument_key, trading_date
    )

    required_columns = {"timestamp", "open", "high", "low", "close"}
    columns_ready = required_columns.issubset(candles.columns)
    raw_candle_count = int(len(candles)) if columns_ready else 0
    candle_count = int(len(prepared_candles))
    rsi_period = 7
    oversold = 20
    overbought = 80
    latest_rsi = latest_wilder_rsi(prepared_candles, rsi_period)
    rsi_ready = latest_rsi is not None
    structure_ready = candle_count >= 2
    readiness = "READY" if rsi_ready and structure_ready else (
        "PARTIAL" if columns_ready else "NOT READY"
    )

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

    st.markdown("#### Post-collection preparation flow")
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
            "stage": "RSI calculation",
            "status": "READY" if rsi_ready else "NOT READY",
            "detail": f"Wilder period={rsi_period}; latest={latest_rsi if latest_rsi is not None else 'unavailable'}; completed_rows={candle_count}; raw_rows={raw_candle_count}",
        },
        {
            "stage": "Extreme thresholds",
            "status": "CONFIGURED",
            "detail": f"Oversold <= {oversold}; Overbought >= {overbought}",
        },
        {
            "stage": "Price-structure inputs",
            "status": "READY" if structure_ready else "NOT READY",
            "detail": "Current OHLC plus previous completed candle high/low",
        },
        {
            "stage": "Confirmation policy",
            "status": "CONFIGURED",
            "detail": "Cross-back + candle direction + structure reclaim + no fresh adverse extreme",
        },
    ]
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)

    st.markdown("#### Option Behaviour Inputs")
    st.caption(
        "Option-chain evidence helps judge whether a possible reversal is supported, "
        "neutral or opposed by market positioning. Price confirmation remains mandatory."
    )
    option_rows = option_context.get("rows") or []
    if option_rows:
        st.dataframe(_arrow_safe_rows(option_rows), width="stretch", hide_index=True)
    else:
        st.warning(str(option_context.get("detail") or "Option context is unavailable."))

    if readiness == "READY":
        st.success("RSI and structure inputs are prepared for extreme/reversal evaluation.")
    elif readiness == "PARTIAL":
        st.warning("Candle data exists, but RSI or previous-candle structure inputs are incomplete.")
    else:
        st.error("RSI input preparation cannot start until cached 1-minute OHLC data is available.")

    setup = build_rsi_setup_state(
        prepared_candles,
        instrument_key,
        option_bias=option_context.get("directional_bias"),
    )
    st.markdown("### 2. Strategy State & Setup Detection")
    st.caption(
        "Read-only trace using the production RSI detector: extreme arm, cross-back, "
        "candle direction, structure reclaim and adverse-extreme protection."
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
        "This page does not create RSI signals, fetch new option data, submit orders, or change the reversal engine."
    )
