from red_bar_lab.ui._shared import *


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    try:
        historical = _historical_service(token, layout)
        dates = historical.available_dates(instrument_key, interval_minutes=1)
    except MissingAccessToken:
        historical = None
        dates = ()

    st.subheader("Level Explorer")
    if not dates:
        st.info(
            "Enter the Upstox token and download 1-minute historical data first. "
            "At least 11 completed trading days are recommended."
        )
    else:
        selected_date = st.selectbox(
            "Trading date", dates, index=len(dates) - 1, key="levels_date"
        )
        if st.button("Build Reference Levels", type="primary"):
            count = _build_and_store_levels(
                database, historical, instrument_key, selected_date, dates
            )
            st.success(f"Stored {count} reference level(s).")

        stored = database.read_reference_levels(
            instrument_key, selected_date.isoformat()
        )
        if stored:
            st.dataframe(stored, width="stretch")
        else:
            st.caption("No stored levels for this date yet.")
