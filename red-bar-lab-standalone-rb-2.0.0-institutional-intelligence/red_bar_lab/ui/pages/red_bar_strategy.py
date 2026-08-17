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


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Red Bar Strategy")
    st.caption(
        "Section 1 · Data & Feature Preparation. Read-only visibility into the inputs "
        "prepared after collection and before Red Bar setup detection."
    )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="red_bar_strategy_date"
    )
    trading_date = selected_date.isoformat()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    levels = database.read_reference_levels(instrument_key, trading_date)
    red_refs = [
        row for row in levels
        if str(row.get("level_type") or "") == "NEXT_RED_CANDLE"
    ]
    red_ref = red_refs[-1] if red_refs else {}

    required_columns = {"timestamp", "open", "high", "low", "close"}
    candle_columns_ready = required_columns.issubset(candles.columns)
    candle_count = int(len(candles)) if candle_columns_ready else 0
    normalized_ready = bool(candle_count and candle_columns_ready)
    reference_ready = bool(red_ref)
    readiness = "READY" if normalized_ready and reference_ready else (
        "PARTIAL" if normalized_ready else "NOT READY"
    )

    st.markdown("### 1. Data & Feature Preparation")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Input readiness", readiness)
    a2.metric("1-minute candles", candle_count)
    a3.metric("OHLC normalized", "YES" if normalized_ready else "NO")
    a4.metric("Red Bar reference", "READY" if reference_ready else "PENDING")

    st.markdown("#### Post-collection preparation flow")
    st.code(
        "1-minute candles collected\n"
        "→ Session candles normalized\n"
        "→ Opening and previous-session context loaded\n"
        "→ Red candle candidates evaluated\n"
        "→ NEXT_RED_CANDLE reference calculated\n"
        "→ High, low and midpoint persisted",
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
            "status": "READY" if candle_columns_ready else "MISSING",
            "detail": ", ".join(sorted(required_columns)),
        },
        {
            "stage": "Session candle normalization",
            "status": "READY" if normalized_ready else "NOT READY",
            "detail": f"{candle_count} usable rows",
        },
        {
            "stage": "NEXT_RED_CANDLE reference",
            "status": "READY" if reference_ready else "PENDING",
            "detail": str(red_ref.get("source_timestamp") or "Not detected/persisted"),
        },
        {
            "stage": "Reference geometry",
            "status": "READY" if reference_ready else "PENDING",
            "detail": (
                f"High={red_ref.get('source_high')}, "
                f"Low={red_ref.get('source_low')}, "
                f"Midpoint={red_ref.get('level_value') or red_ref.get('midpoint')}"
                if reference_ready else "Awaiting Red Bar reference"
            ),
        },
    ]
    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)

    if readiness == "READY":
        st.success("Red Bar strategy inputs are prepared for setup detection.")
    elif readiness == "PARTIAL":
        st.warning(
            "Candle inputs are available, but the NEXT_RED_CANDLE reference is not yet persisted."
        )
    else:
        st.error("Red Bar input preparation cannot start until cached 1-minute OHLC data is available.")

    st.info(
        "This page does not run detection, alter reference levels, or change execution behavior."
    )