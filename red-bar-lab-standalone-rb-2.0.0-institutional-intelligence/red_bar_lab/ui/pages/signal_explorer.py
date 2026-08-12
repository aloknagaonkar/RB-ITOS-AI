from red_bar_lab.ui._shared import *


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    try:
        historical = _historical_service(token, layout)
        dates = historical.available_dates(instrument_key, interval_minutes=1)
    except MissingAccessToken:
        historical = None
        dates = ()

    st.subheader("Signal Explorer")
    st.caption(
        "A completed 5-minute Candle A must cross and close beyond the level. "
        "The next five 1-minute candles are checked. The first 1-minute "
        "close beyond Candle A high/low makes the signal ACTIVE immediately; "
        "otherwise the attempt TIMEOUTs."
    )
    if not dates:
        st.info("Download 1-minute historical candles first.")
    else:
        selected_date = st.selectbox(
            "Trading date", dates, index=len(dates) - 1, key="signals_date"
        )
        stored_levels = database.load_reference_levels(
            instrument_key, selected_date.isoformat()
        )
        if not stored_levels:
            st.warning(
                "No reference levels are stored for this date. Build them in "
                "the Levels tab, or use the button below."
            )
            if st.button("Build Levels for Signal Replay"):
                _build_and_store_levels(
                    database, historical, instrument_key, selected_date, dates
                )
                st.rerun()
        else:
            if st.button("Run Signal Replay", type="primary"):
                candles = historical.read_day(
                    instrument_key, selected_date, interval_minutes=1
                )
                result = scan_reference_levels(candles, stored_levels)
                database.replace_signal_attempts(
                    "HISTORICAL_REPLAY",
                    instrument_key,
                    selected_date.isoformat(),
                    result.attempts,
                )
                st.success(
                    f"Signal replay complete: {len(result.active)} ACTIVE, "
                    f"{len(result.failed)} confirmation failed."
                )

            attempts = database.read_signal_attempts(
                instrument_key, selected_date.isoformat()
            )
            if attempts:
                active_count = sum(row["state"] == "ACTIVE" for row in attempts)
                failed_count = sum(
                    row["state"] == "CONFIRMATION_FAILED" for row in attempts
                )
                bullish_count = sum(
                    row["state"] == "ACTIVE" and row["direction"] == "BULLISH"
                    for row in attempts
                )
                bearish_count = sum(
                    row["state"] == "ACTIVE" and row["direction"] == "BEARISH"
                    for row in attempts
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("ACTIVE", active_count)
                c2.metric("Failed", failed_count)
                c3.metric("Bullish / CE", bullish_count)
                c4.metric("Bearish / PE", bearish_count)
                st.dataframe(attempts, width="stretch")
            else:
                st.caption("No signal replay results stored for this date yet.")
