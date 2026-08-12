from red_bar_lab.ui._shared import *
from red_bar_lab.services.red_bar_diagnostics import build_red_bar_lifecycle


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Red Bar Diagnostics")
    st.caption(
        "Read-only lifecycle visibility for NEXT_RED_CANDLE. This page does not "
        "change Red Bar detection, confirmation, Decision Engine, or execution rules."
    )

    selected_date = st.date_input("Trading date", value=date.today())
    trading_date = selected_date.isoformat()

    levels = database.read_reference_levels(instrument_key, trading_date)
    attempts = database.read_signal_attempts(instrument_key, trading_date)
    lifecycle = build_red_bar_lifecycle(levels, attempts)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lifecycle", str(lifecycle.get("status") or "—"))
    c2.metric(
        "Midpoint",
        f"{float(lifecycle['midpoint']):.2f}"
        if lifecycle.get("midpoint") is not None
        else "—",
    )
    c3.metric(
        "Reference persisted",
        "YES" if lifecycle.get("reference_persisted") else "NO",
    )
    c4.metric("Signal attempts", int(lifecycle.get("signal_attempts") or 0))

    st.dataframe(
        _arrow_safe_rows([{
            "level_type": lifecycle.get("level_type"),
            "status": lifecycle.get("status"),
            "source_timestamp": lifecycle.get("source_timestamp"),
            "source_high": lifecycle.get("source_high"),
            "source_low": lifecycle.get("source_low"),
            "midpoint": lifecycle.get("midpoint"),
            "interval_minutes": lifecycle.get("interval_minutes"),
            "data_quality": lifecycle.get("data_quality"),
            "latest_signal_state": lifecycle.get("latest_signal_state"),
            "direction": lifecycle.get("direction"),
            "cross_timestamp": lifecycle.get("cross_timestamp"),
            "confirmation_timestamp": lifecycle.get("confirmation_timestamp"),
            "detail": lifecycle.get("detail"),
        }]),
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Persisted Red Bar reference")
    red_refs = [row for row in levels if row.get("level_type") == "NEXT_RED_CANDLE"]
    if red_refs:
        st.dataframe(_arrow_safe_rows(red_refs), width="stretch", hide_index=True)
    else:
        st.warning(
            "NEXT_RED_CANDLE is not present in reference_levels for this session. "
            "That means the issue is before signal confirmation."
        )

    st.markdown("#### Persisted Red Bar signal attempts")
    red_attempts = [
        row for row in attempts
        if row.get("level_type") == "NEXT_RED_CANDLE"
    ]
    if red_attempts:
        st.dataframe(
            _arrow_safe_rows(red_attempts),
            width="stretch",
            hide_index=True,
        )
    else:
        if red_refs:
            st.info(
                "Red Bar reference exists, but there is no NEXT_RED_CANDLE signal "
                "attempt yet. The current stage is waiting for a qualifying 5-minute cross."
            )
        else:
            st.caption("No Red Bar signal attempts can exist until the reference is detected.")

    st.markdown("#### Other live signal attempts (context)")
    if attempts:
        st.dataframe(
            _arrow_safe_rows(attempts),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No signal attempts are persisted for the selected session.")
