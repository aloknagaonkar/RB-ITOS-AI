from red_bar_lab.ui._shared import *
from red_bar_lab.execution.rsi_extreme_reversal import RsiExtremeReversalEngine


def _read_cached_candles(layout, instrument_key, trading_date):
    path = layout.candle_path("upstox", instrument_key, 1, trading_date)
    if not path.exists():
        return path, pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except Exception:
        return path, pd.DataFrame()
    return path, frame


def _latest_rsi(candles, period=7):
    if candles.empty or "close" not in candles.columns:
        return None
    close = pd.to_numeric(candles["close"], errors="coerce").dropna()
    if len(close) <= period:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    value = 100 - (100 / (1 + rs))
    latest = value.dropna()
    return float(latest.iloc[-1]) if not latest.empty else None


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("RSI Extreme Reversal")
    st.caption(
        "Section 1 · Data & Feature Preparation. Read-only visibility into the candle, "
        "RSI and structure inputs prepared before extreme and reversal evaluation."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="rsi_strategy_date"
    )
    trading_date = selected_date.isoformat()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)

    required_columns = {"timestamp", "open", "high", "low", "close"}
    columns_ready = required_columns.issubset(candles.columns)
    candle_count = int(len(candles)) if columns_ready else 0
    rsi_period = 7
    oversold = 20
    overbought = 80
    latest_rsi = _latest_rsi(candles, rsi_period) if columns_ready else None
    rsi_ready = latest_rsi is not None
    structure_ready = bool(columns_ready and candle_count >= 2)
    readiness = "READY" if rsi_ready and structure_ready else (
        "PARTIAL" if columns_ready else "NOT READY"
    )

    st.markdown("### 1. Data & Feature Preparation")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Input readiness", readiness)
    a2.metric("1-minute candles", candle_count)
    a3.metric("Latest RSI(7)", f"{latest_rsi:.2f}" if latest_rsi is not None else "—")
    a4.metric("Structure inputs", "READY" if structure_ready else "NOT READY")

    st.markdown("#### Post-collection preparation flow")
    st.code(
        "1-minute candles collected\n"
        "→ OHLC data normalized\n"
        "→ RSI(7) series calculated\n"
        "→ Oversold / overbought state prepared\n"
        "→ Previous-candle high/low prepared\n"
        "→ Reversal confirmation inputs made available",
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
            "detail": f"Period={rsi_period}; latest={latest_rsi if latest_rsi is not None else 'unavailable'}",
        },
        {
            "stage": "Extreme thresholds",
            "status": "CONFIGURED",
            "detail": f"Oversold ≤ {oversold}; Overbought ≥ {overbought}",
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

    if readiness == "READY":
        st.success("RSI and structure inputs are prepared for extreme/reversal evaluation.")
    elif readiness == "PARTIAL":
        st.warning("Candle data exists, but RSI or previous-candle structure inputs are incomplete.")
    else:
        st.error("RSI input preparation cannot start until cached 1-minute OHLC data is available.")

    st.info(
        "This page does not create RSI signals, submit orders, or change the reversal engine."
    )