from __future__ import annotations

from importlib import import_module
from types import ModuleType

import red_bar_lab.ui._shared as shared_ui
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.ui._shared import *
from red_bar_lab.ui.paper_time_display import install as install_paper_time_display


install_paper_time_display()
shared_ui.PaperExitEngine = PaperExitEngine


_PAGE_MODULE_PATHS = {
    "Operations Center": "red_bar_lab.ui.pages.operations_center",
    "Red Bar Strategy": "red_bar_lab.ui.pages.red_bar_strategy",
    "RSI Extreme Reversal": "red_bar_lab.ui.pages.rsi_extreme_reversal_strategy",
    "Directional Regime Intelligence": "red_bar_lab.ui.pages.directional_regime_strategy",
    "Live Trading": "red_bar_lab.ui.pages.live_trading",
    "Paper Trading": "red_bar_lab.ui.pages.paper_trading",
    "Research Lab": "red_bar_lab.ui.pages.research_lab",
    "Shadow Directional": "red_bar_lab.ui.pages.shadow_directional_diagnostics",
    "Historical Intelligence": "red_bar_lab.ui.pages.historical_intelligence",
    "Signal Explorer": "red_bar_lab.ui.pages.signal_explorer",
    "Level Explorer": "red_bar_lab.ui.pages.level_explorer",
    "PD Startup Readiness": "red_bar_lab.ui.pages.pd_readiness",
    "Previous Session Context": "red_bar_lab.ui.pages.previous_session_context",
    "Red Bar Diagnostics": "red_bar_lab.ui.pages.red_bar_diagnostics",
    "Committee Gate Trace": "red_bar_lab.ui.pages.committee_diagnostics",
    "Performance Hard Block Trace": "red_bar_lab.ui.pages.performance_diagnostics",
    "Opportunity Reward Trace": "red_bar_lab.ui.pages.opportunity_reward_diagnostics",
    "Trade History": "red_bar_lab.ui.pages.trade_history",
    "Institutional Intelligence": "red_bar_lab.ui.pages.institutional_intelligence",
    "Intelligence": "red_bar_lab.ui.pages.intelligence",
}

_CACHED_CANDLE_PAGES = frozenset(
    {
        "Red Bar Strategy",
        "RSI Extreme Reversal",
        "Directional Regime Intelligence",
    }
)
_PAGE_MODULE_CACHE: dict[str, ModuleType] = {}
_CONFIGURED_PAGE_MODULES: set[str] = set()


def _research_option_sync_factory(provider, layout, historical, database=None):
    """Apply enhanced readiness only to lazily loaded Research Lab workflows."""
    from red_bar_lab.services.historical_dri_research_readiness import (
        HistoricalDRIResearchReadinessService,
    )

    base_sync = shared_ui.HistoricalOptionChainSyncService(
        provider,
        layout,
        historical,
        database=database,
    )
    return HistoricalDRIResearchReadinessService(base_sync, historical)


def _configure_strategy_candle_cache(module: ModuleType) -> None:
    """Install the metadata-keyed candle reader on strategy pages only."""
    from red_bar_lab.ui.strategy_candle_cache import (
        read_cached_strategy_candles,
    )

    module._read_cached_candles = read_cached_strategy_candles


def _configure_paper_trading(module: ModuleType) -> None:
    from red_bar_lab.execution.attribution_automation import (
        AttributionAwarePaperAutomationService,
    )
    from red_bar_lab.ui.active_trade_views import build_paper_page_wrapper
    from red_bar_lab.ui.paper_consistency import (
        build_candidate_workbench_wrapper,
        build_paper_exit_panel_wrapper,
    )

    module.RedBarPaperAutomationService = AttributionAwarePaperAutomationService
    module._render_candidate_workbench_fragment = build_candidate_workbench_wrapper(
        shared_ui._render_candidate_workbench_fragment
    )
    module._render_paper_exit_engine_panel = build_paper_exit_panel_wrapper(
        shared_ui._render_paper_exit_engine_panel
    )
    module.render_page = build_paper_page_wrapper(module.render_page)


def _configure_research_lab(module: ModuleType) -> None:
    import red_bar_lab.ui.historical_dri_10day as historical_dri_10day_ui
    from red_bar_lab.services.evidence_replay import (
        EvidenceAwareHistoricalDecisionReplayService,
    )
    from red_bar_lab.ui.historical_dri_10day import build_10day_validation_wrapper
    from red_bar_lab.ui.historical_dri_20day import build_20day_validation_wrapper
    from red_bar_lab.ui.historical_dri_relevant_coverage import (
        build_relevant_coverage_wrapper,
    )

    historical_dri_10day_ui.HistoricalOptionChainSyncService = (
        _research_option_sync_factory
    )
    module.HistoricalDecisionReplayService = (
        EvidenceAwareHistoricalDecisionReplayService
    )
    module.render_page = build_10day_validation_wrapper(
        module.render_page,
        module,
    )
    module.render_page = build_20day_validation_wrapper(
        module.render_page,
        module,
    )
    module.render_page = build_relevant_coverage_wrapper(module.render_page)


def _configure_page(page: str, module: ModuleType) -> None:
    """Apply each page's existing integration hooks once, after lazy import."""
    if page in _CONFIGURED_PAGE_MODULES:
        return
    if page in _CACHED_CANDLE_PAGES:
        _configure_strategy_candle_cache(module)
    if page == "Paper Trading":
        _configure_paper_trading(module)
    elif page == "Research Lab":
        _configure_research_lab(module)
    _CONFIGURED_PAGE_MODULES.add(page)


def _load_page_module(page: str) -> ModuleType:
    """Import and configure only the page selected in the workspace."""
    module = _PAGE_MODULE_CACHE.get(page)
    if module is None:
        module_path = _PAGE_MODULE_PATHS[page]
        module = import_module(module_path)
        _PAGE_MODULE_CACHE[page] = module
    _configure_page(page, module)
    return module


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
    workspace_pages = tuple(_PAGE_MODULE_PATHS)
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

    module = _load_page_module(page)
    module.render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    )
