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
    trading_date = selected_date.isoformat()
    levels = database.read_reference_levels(instrument_key, trading_date)
    cached_dates = _cached_dates(layout, instrument_key)
    readiness = build_pd_startup_readiness(cached_dates, levels, selected_date)

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Previous sessions",
        f"{int(readiness['prior_sessions'])}/{int(readiness['required_prior_sessions'])}",
    )
    c2.metric(
        "PD levels",
        f"{int(readiness['pd_levels'])}/{int(readiness['required_pd_levels'])}",
    )
    c3.metric("PD signal scanning", str(readiness.get("status") or "—"))

    if readiness.get("signal_scanning_ready"):
        st.success(str(readiness.get("detail") or "PD live signal scanning is ready."))
    elif readiness.get("status") == "BACKFILLING":
        st.warning(str(readiness.get("detail") or "Previous-session history is still backfilling."))
    else:
        st.error(str(readiness.get("detail") or "PD level coverage is incomplete."))

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
            "Live Trading so the historical backfill and level-generation path can run."
        )

    st.markdown("#### Morning acceptance criteria")
    st.code(
        "Previous sessions: 10/10\n"
        "PD levels: 10/10\n"
        "PD signal scanning: READY",
        language=None,
    )
    st.caption(
        "Treat live PD coverage as ready only when all three checks pass before the first "
        "completed 5-minute setup is evaluated."
    )
