from red_bar_lab.ui._shared import *
from red_bar_lab.ui.pages import (
    intelligence,
    level_explorer,
    live_trading,
    operations_center,
    paper_trading,
    research_lab,
    signal_explorer,
    trade_history,
)


_PAGE_MODULES = {
    "Operations Center": operations_center,
    "Live Trading": live_trading,
    "Paper Trading": paper_trading,
    "Research Lab": research_lab,
    "Signal Explorer": signal_explorer,
    "Level Explorer": level_explorer,
    "Trade History": trade_history,
    "Intelligence": intelligence,
}


def render(settings: RedBarSettings) -> None:
    layout = ArtifactLayout(settings)
    layout.ensure()
    database = _cached_database(str(settings.database_path))

    st.title("Red Bar Strategy Lab")
    st.caption(
        f"{settings.version} · Independent research application · Port {settings.port}"
    )

    token = st.sidebar.text_input(
        "Upstox access token",
        value="",
        type="password",
        help="Used only in memory. It is not written to Red Bar artifacts.",
    )
    underlying_name = st.sidebar.selectbox(
        "Underlying",
        tuple(UNDERLYINGS),
        index=0,
    )
    instrument_key = UNDERLYINGS[underlying_name]
    interval = st.sidebar.selectbox(
        "Download candle interval",
        (1, 3, 5, 15),
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("Workspace")
    workspace_pages = (
        "Operations Center",
        "Live Trading",
        "Paper Trading",
        "Research Lab",
        "Signal Explorer",
        "Level Explorer",
        "Trade History",
        "Intelligence",
    )
    saved_page = st.query_params.get("page", "Operations Center")
    if saved_page not in workspace_pages:
        saved_page = "Operations Center"

    page = st.sidebar.radio(
        "Navigate",
        workspace_pages,
        index=workspace_pages.index(saved_page),
        label_visibility="collapsed",
        key="workspace_navigation",
    )
    if st.query_params.get("page") != page:
        st.query_params["page"] = page

    module = _PAGE_MODULES[page]
    module.render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    )
