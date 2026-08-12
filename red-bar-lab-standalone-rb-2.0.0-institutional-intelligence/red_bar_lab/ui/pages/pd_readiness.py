from red_bar_lab.ui._shared import *
from red_bar_lab.services.pd_readiness import build_pd_startup_readiness


def _cached_dates(layout, instrument_key):
    sample = layout.candle_path("upstox", instrument_key, 1, "2000-01-01")
    folder = sample.parent
    if not folder.exists():
        return []
    result = []
    for path in folder.glob("*.csv"):
        try:
            result.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return sorted(set(result))


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("PD Startup Readiness")
    st.caption(
        "Read-only morning readiness for PD1_315..PD10_315. This page does not "
        "change PD levels, signal confirmation, Decision Engine, or execution rules."
    )

    selected_date = st.date_input("Trading date", value=date.today(), key="pd_readiness_date")
    levels = database.read_reference_levels(instrument_key, selected_date.isoformat())
    readiness = build_pd_startup_readiness(
        _cached_dates(layout, instrument_key), levels, selected_date
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Previous sessions", f"{readiness['prior_sessions']}/10")
    c2.metric("PD levels", f"{readiness['pd_levels']}/10")
    c3.metric("PD signal scanning", str(readiness.get("status") or "—"))

    if readiness.get("signal_scanning_ready"):
        st.success(str(readiness.get("detail")))
    elif readiness.get("status") == "BACKFILLING":
        st.warning(str(readiness.get("detail")))
    else:
        st.error(str(readiness.get("detail")))

    missing = list(readiness.get("missing_pd_levels") or ())
    if missing:
        st.caption("Missing PD levels: " + ", ".join(missing))

    pd_rows = [
        row for row in levels
        if str(row.get("level_type") or "").startswith("PD")
        and str(row.get("level_type") or "").endswith("_315")
    ]
    st.markdown("#### Persisted PD reference levels")
    if pd_rows:
        st.dataframe(_arrow_safe_rows(pd_rows), width="stretch", hide_index=True)
    else:
        st.info(
            "No PD reference levels are persisted for this session yet. Start or refresh "
            "Live Trading so historical backfill and level generation can run."
        )

    st.markdown("#### Morning acceptance criteria")
    st.code(
        "Previous sessions: 10/10\nPD levels: 10/10\nPD signal scanning: READY",
        language=None,
    )
