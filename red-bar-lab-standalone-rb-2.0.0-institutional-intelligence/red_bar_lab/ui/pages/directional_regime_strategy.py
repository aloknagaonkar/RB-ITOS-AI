from red_bar_lab.ui._shared import *


def _read_cached_candles(layout, instrument_key, trading_date):
    path = layout.candle_path("upstox", instrument_key, 1, trading_date)
    if not path.exists():
        return path, pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except Exception:
        return path, pd.DataFrame()
    return path, frame


def _resample_five_minute(candles):
    required = {"timestamp", "open", "high", "low", "close"}
    if candles.empty or not required.issubset(candles.columns):
        return pd.DataFrame()
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    if frame.empty:
        return pd.DataFrame()
    aggregations = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in frame.columns:
        aggregations["volume"] = "sum"
    return (
        frame.set_index("timestamp")
        .resample("5min")
        .agg(aggregations)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Directional Regime Intelligence")
    st.caption(
        "Section 1 · Data & Feature Preparation. Read-only visibility into the "
        "multi-timeframe and directional inputs prepared before regime classification."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="directional_regime_strategy_date"
    )
    trading_date = selected_date.isoformat()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)

    required_columns = {"timestamp", "open", "high", "low", "close"}
    columns_ready = required_columns.issubset(candles.columns)
    one_minute_count = int(len(candles)) if columns_ready else 0
    five_minute = _resample_five_minute(candles) if columns_ready else pd.DataFrame()
    five_minute_count = int(len(five_minute))
    volume_ready = bool("volume" in candles.columns and pd.to_numeric(
        candles.get("volume"), errors="coerce"
    ).notna().any()) if not candles.empty else False
    structure_ready = five_minute_count >= 3
    indicator_window_ready = five_minute_count >= 14
    readiness = "READY" if structure_ready and indicator_window_ready else (
        "PARTIAL" if columns_ready else "NOT READY"
    )

    st.markdown("### 1. Data & Feature Preparation")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Input readiness", readiness)
    a2.metric("1-minute candles", one_minute_count)
    a3.metric("5-minute candles", five_minute_count)
    a4.metric("Volume input", "READY" if volume_ready else "UNAVAILABLE")

    st.markdown("#### Post-collection preparation flow")
    st.code(
        "Price and volume collected\n"
        "→ 1-minute candles normalized\n"
        "→ 5-minute candles aligned\n"
        "→ Market structure inputs prepared\n"
        "→ EMA slope / acceleration windows prepared\n"
        "→ DMI / ADX and ATR windows prepared\n"
        "→ Directional regime feature set made available",
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
            "detail": f"{one_minute_count} rows",
        },
        {
            "stage": "5-minute alignment",
            "status": "READY" if five_minute_count else "NOT READY",
            "detail": f"{five_minute_count} completed/resampled rows",
        },
        {
            "stage": "Price-structure window",
            "status": "READY" if structure_ready else "PARTIAL",
            "detail": "Requires multiple completed 5-minute candles",
        },
        {
            "stage": "Indicator lookback window",
            "status": "READY" if indicator_window_ready else "PARTIAL",
            "detail": "EMA, DMI/ADX and ATR preparation requires sufficient history",
        },
        {
            "stage": "Volume context",
            "status": "READY" if volume_ready else "UNAVAILABLE",
            "detail": "Collected volume column present and populated" if volume_ready else "No populated volume input",
        },
    ]
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)

    if readiness == "READY":
        st.success("Directional feature inputs are prepared for regime classification.")
    elif readiness == "PARTIAL":
        st.warning(
            "Base candles are available, but additional completed 5-minute history is needed for all directional features."
        )
    else:
        st.error("Directional input preparation cannot start until cached 1-minute OHLC data is available.")

    st.info(
        "This page does not classify a regime, create native DRI signals, or change execution authority."
    )