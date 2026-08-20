from red_bar_lab.ui._shared import *
from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("NIFTY Futures Readiness")
    st.caption(
        "Read-only futures contract, completed-candle, volume, OI, positioning and "
        "strength diagnostics. This page has no execution authority."
    )

    if underlying_name != "NIFTY 50":
        st.info("NIFTY futures readiness is not applicable to the selected underlying.")
        return

    rows = read_nifty_futures_snapshots(
        settings.database_path,
        underlying_name=underlying_name,
        limit=250,
    )
    if not rows:
        st.warning(
            "No persisted futures diagnostics are available yet. Run the Phase 2 "
            "futures diagnostic pipeline during or after a market session."
        )
        return

    latest = rows[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Readiness", str(latest.get("readiness_status") or "—"))
    c2.metric("Positioning", str(latest.get("positioning_state") or "—"))
    c3.metric("Strength", str(latest.get("strength") or "—"))
    c4.metric("Relative volume", _format_metric(latest.get("relative_volume"), 4))

    st.markdown("#### Latest completed futures observation")
    detail = {
        "Observed at": latest.get("observed_at"),
        "Contract": latest.get("trading_symbol"),
        "Expiry": latest.get("expiry"),
        "Candle status": latest.get("candle_status"),
        "Close": latest.get("latest_close"),
        "Volume": latest.get("latest_volume"),
        "OI": latest.get("latest_oi"),
        "Price change %": latest.get("price_change_pct"),
        "OI change %": latest.get("oi_change_pct"),
        "Blocking reasons": ", ".join(latest.get("blocking_reasons") or ()) or "NONE",
        "Advisory reasons": ", ".join(latest.get("advisory_reasons") or ()) or "NONE",
        "Authority": latest.get("authority"),
    }
    st.dataframe(_arrow_safe_rows([detail]), width="stretch", hide_index=True)

    st.markdown("#### Recent futures diagnostic history")
    display_columns = (
        "observed_at",
        "trading_symbol",
        "readiness_status",
        "candle_status",
        "positioning_state",
        "strength",
        "price_change_pct",
        "oi_change_pct",
        "relative_volume",
        "latest_close",
        "latest_volume",
        "latest_oi",
        "authority",
    )
    history = [{key: row.get(key) for key in display_columns} for row in rows]
    st.dataframe(_arrow_safe_rows(history), width="stretch", hide_index=True)


def _format_metric(value, digits):
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"
