import red_bar_lab.ui._shared as shared_ui
import red_bar_lab.ui.historical_dri_10day as historical_dri_10day_ui
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.execution.attribution_automation import AttributionAwarePaperAutomationService
from red_bar_lab.services.evidence_replay import EvidenceAwareHistoricalDecisionReplayService
from red_bar_lab.services.historical_dri_research_readiness import (
    HistoricalDRIResearchReadinessService,
)
from red_bar_lab.ui.active_trade_views import build_paper_page_wrapper
from red_bar_lab.ui.historical_dri_10day import build_10day_validation_wrapper
from red_bar_lab.ui.historical_dri_relevant_coverage import (
    build_relevant_coverage_wrapper,
)
from red_bar_lab.ui.paper_time_display import install as install_paper_time_display
from red_bar_lab.ui.paper_consistency import (
    build_candidate_workbench_wrapper,
    build_paper_exit_panel_wrapper,
)
from red_bar_lab.ui._shared import *
from red_bar_lab.ui.pages import (
    committee_diagnostics,
    historical_intelligence,
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
    shadow_directional_diagnostics,
    signal_explorer,
    trade_history,
)

install_paper_time_display()

shared_ui.PaperExitEngine = PaperExitEngine
paper_trading.RedBarPaperAutomationService = AttributionAwarePaperAutomationService
paper_trading._render_candidate_workbench_fragment = (
    build_candidate_workbench_wrapper(
        shared_ui._render_candidate_workbench_fragment
    )
)
paper_trading._render_paper_exit_engine_panel = (
    build_paper_exit_panel_wrapper(
        shared_ui._render_paper_exit_engine_panel
    )
)
research_lab.HistoricalDecisionReplayService = EvidenceAwareHistoricalDecisionReplayService

# Limit the strategy-relevant readiness policy to the enhanced historical
# 10-day Research Lab workflow. The normal option sync class remains unchanged
# everywhere else, including live and paper execution.
def _research_option_sync_factory(provider, layout, historical, database=None):
    base_sync = shared_ui.HistoricalOptionChainSyncService(
        provider,
        layout,
        historical,
        database=database,
    )
    return HistoricalDRIResearchReadinessService(base_sync, historical)


historical_dri_10day_ui.HistoricalOptionChainSyncService = (
    _research_option_sync_factory
)
research_lab.render_page = build_10day_validation_wrapper(
    research_lab.render_page,
    research_lab,
)
research_lab.render_page = build_relevant_coverage_wrapper(
    research_lab.render_page,
)
paper_trading.render_page = build_paper_page_wrapper(paper_trading.render_page)

_PAGE_MODULES = {
    "Operations Center": operations_center,
    "Live Trading": live_trading,
    "Paper Trading": paper_trading,
    "Research Lab": research_lab,
    "Shadow Directional": shadow_directional_diagnostics,
    "Historical Intelligence": historical_intelligence,
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
        "Operations Center", "Live Trading", "Paper Trading", "Research Lab", "Shadow Directional", "Historical Intelligence",
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
