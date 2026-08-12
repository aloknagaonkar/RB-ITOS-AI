import red_bar_lab.ui._shared as shared_ui
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.ui._shared import *
from red_bar_lab.ui.pages import (
    committee_diagnostics,
    institutional_intelligence,
    intelligence,
    level_explorer,
    live_trading,
    operations_center,
    opportunity_reward_diagnostics,
    paper_trading,
    pd_readiness,
    performance_diagnostics,
    previous_session_context,
    red_bar_diagnostics,
    research_lab,
    signal_explorer,
    trade_history,
)

shared_ui.PaperExitEngine = PaperExitEngine

_PAGE_MODULES = {
    "Operations Center": operations_center,
    "Live Trading": live_trading,
    "Paper Trading": paper_trading,
    "Research Lab": research_lab,
    "Signal Explorer": signal_explorer,
    "Level Explorer": level_explorer,
    "PD Startup Readiness": pd_readiness,
    "Previous Session Context": previous_session_context,
    "Red Bar Diagnostics": red_bar_diagnostics,
    "Committee Gate Trace": committee_diagnostics,
    "Performance Hard Block Trace": performance_diagnostics,
    "Opportunity Reward Trace": opportunity_reward_diagnostics,
    "Trade History": trade_history,
    "Institutional Intelligence": institutional_intelligence,
    "Intelligence": intelligence,
}


def render(settings: RedBarSettings) -> None:
    layout = ArtifactLayout(settings)
    layout.ensure()
    database = _cached_database(str(settings.database_path))

    st.title("Red Bar Strategy Lab")
    st.caption(f"{settings.version} · Independent research application · Port {settings.port}")

    token = st.sidebar.text_input("Upstox access token", value="", type="password", help="Used only in memory. It is not written to Red Bar artifacts.")
    underlying_name = st.sidebar.selectbox("Underlying", tuple(UNDERLYINGS), index=0)
    instrument_key = UNDERLYINGS[underlying_name]
    interval = st.sidebar.selectbox("Download candle interval", (1, 3, 5, 15), index=0)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Workspace")
    workspace_pages = (
        "Operations Center", "Live Trading", "Paper Trading", "Research Lab",
        "Signal Explorer", "Level Explorer", "PD Startup Readiness", "Previous Session Context", "Red Bar Diagnostics",
        "Committee Gate Trace", "Performance Hard Block Trace", "Opportunity Reward Trace",
        "Trade History", "Institutional Intelligence", "Intelligence",
    )
    saved_page = st.query_params.get("page", "Operations Center")
    if saved_page not in workspace_pages:
        saved_page = "Operations Center"
    page = st.sidebar.radio("Navigate", workspace_pages, index=workspace_pages.index(saved_page), label_visibility="collapsed", key="workspace_navigation")
    if st.query_params.get("page") != page:
        st.query_params["page"] = page
    module = _PAGE_MODULES[page]
    module.render_page(settings, layout, database, token, underlying_name, instrument_key, interval)
