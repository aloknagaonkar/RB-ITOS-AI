from __future__ import annotations

from collections.abc import Iterator, Mapping
from importlib import import_module
from types import ModuleType

import red_bar_lab.ui._shared as shared_ui


PAGE_MODULE_PATHS = {
    "Operations Center": "red_bar_lab.ui.pages.operations_center",
    "Red Bar Strategy": "red_bar_lab.ui.pages.red_bar_strategy",
    "RSI Extreme Reversal": "red_bar_lab.ui.pages.rsi_extreme_reversal_strategy",
    "Directional Regime Intelligence": "red_bar_lab.ui.pages.directional_regime_strategy",
    "Live Trading": "red_bar_lab.ui.pages.live_trading",
    "Paper Trading": "red_bar_lab.ui.pages.paper_trading",
    "Paper Architecture Reconciliation": (
        "red_bar_lab.ui.pages.paper_architecture_reconciliation_v4"
    ),
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
    {"Red Bar Strategy", "RSI Extreme Reversal", "Directional Regime Intelligence"}
)
_BACKGROUND_BOOTSTRAP_PAGES = frozenset(
    {
        "Operations Center",
        "Red Bar Strategy",
        "RSI Extreme Reversal",
        "Directional Regime Intelligence",
        "Paper Trading",
        "Paper Architecture Reconciliation",
    }
)
_MODULE_CACHE: dict[str, ModuleType] = {}
_CONFIGURED: set[str] = set()


def _research_option_sync_factory(provider, layout, historical, database=None):
    from red_bar_lab.services.historical_dri_research_readiness import (
        HistoricalDRIResearchReadinessService,
    )

    base_sync = shared_ui.HistoricalOptionChainSyncService(
        provider, layout, historical, database=database
    )
    return HistoricalDRIResearchReadinessService(base_sync, historical)


def _configure_strategy_cache(page: str, module: ModuleType) -> None:
    from red_bar_lab.ui.strategy_identity_compatibility import (
        install_strategy_identity_compatibility,
    )
    from red_bar_lab.ui.strategy_analysis_eligibility import (
        install_analysis_eligibility_separation,
    )

    install_strategy_identity_compatibility()
    install_analysis_eligibility_separation()

    from red_bar_lab.ui.strategy_candle_cache import read_cached_strategy_candles
    from red_bar_lab.ui.strategy_contract_ranking_wrapper import (
        build_contract_ranking_page_wrapper,
    )
    from red_bar_lab.ui.strategy_contract_readiness_wrapper import (
        build_contract_readiness_page_wrapper,
    )
    from red_bar_lab.ui.strategy_execution_source_gate import (
        build_execution_source_gate_page_wrapper,
    )
    from red_bar_lab.ui.strategy_query_cache import (
        build_strategy_query_cache_wrapper,
    )

    module._read_cached_candles = read_cached_strategy_candles
    if page == "RSI Extreme Reversal":
        from red_bar_lab.ui.rsi_decision_trace_alignment import (
            install_rsi_decision_trace_alignment,
        )

        install_rsi_decision_trace_alignment(module)
    module.render_page = build_strategy_query_cache_wrapper(module.render_page)
    module.render_page = build_execution_source_gate_page_wrapper(module, page)
    module.render_page = build_contract_readiness_page_wrapper(module, page)
    module.render_page = build_contract_ranking_page_wrapper(module, page)


def _configure_paper_trading(paper_trading: ModuleType) -> None:
    from red_bar_lab.execution.attribution_automation import (
        AttributionAwarePaperAutomationService,
    )
    from red_bar_lab.ui.paper_consistency import (
        build_candidate_workbench_wrapper,
        build_paper_exit_panel_wrapper,
    )
    from red_bar_lab.ui.paper_operational_wrapper import (
        build_operational_paper_page_wrapper,
    )

    paper_trading.RedBarPaperAutomationService = AttributionAwarePaperAutomationService
    paper_trading._render_candidate_workbench_fragment = build_candidate_workbench_wrapper(
        shared_ui._render_candidate_workbench_fragment
    )
    paper_trading._render_paper_exit_engine_panel = build_paper_exit_panel_wrapper(
        shared_ui._render_paper_exit_engine_panel
    )
    paper_trading.render_page = build_operational_paper_page_wrapper(
        paper_trading.render_page
    )


def _configure_research_lab(research_lab: ModuleType) -> None:
    import red_bar_lab.ui.historical_dri_10day as historical_dri_10day_ui
    from red_bar_lab.services.evidence_replay import (
        EvidenceAwareHistoricalDecisionReplayService,
    )
    from red_bar_lab.ui.historical_dri_10day import build_10day_validation_wrapper
    from red_bar_lab.ui.historical_dri_20day import build_20day_validation_wrapper
    from red_bar_lab.ui.historical_dri_relevant_coverage import (
        build_relevant_coverage_wrapper,
    )

    historical_dri_10day_ui.HistoricalOptionChainSyncService = _research_option_sync_factory
    research_lab.HistoricalDecisionReplayService = EvidenceAwareHistoricalDecisionReplayService
    research_lab.render_page = build_10day_validation_wrapper(
        research_lab.render_page, research_lab
    )
    research_lab.render_page = build_20day_validation_wrapper(
        research_lab.render_page, research_lab
    )
    research_lab.render_page = build_relevant_coverage_wrapper(research_lab.render_page)


def configure_page(page: str, module: ModuleType) -> ModuleType:
    if page in _CONFIGURED:
        return module
    if page in _CACHED_CANDLE_PAGES:
        _configure_strategy_cache(page, module)
    if page == "Paper Trading":
        _configure_paper_trading(module)
    elif page == "Research Lab":
        _configure_research_lab(module)
    if page in _BACKGROUND_BOOTSTRAP_PAGES:
        from red_bar_lab.ui.background_architecture_runtime import (
            build_background_architecture_bootstrap_wrapper,
        )

        module.render_page = build_background_architecture_bootstrap_wrapper(
            module.render_page
        )
    _CONFIGURED.add(page)
    return module


def load_page_module(page: str) -> ModuleType:
    module = _MODULE_CACHE.get(page)
    if module is None:
        module = import_module(PAGE_MODULE_PATHS[page])
        _MODULE_CACHE[page] = module
    return configure_page(page, module)


class LazyPageModules(Mapping[str, ModuleType]):
    def __getitem__(self, page: str) -> ModuleType:
        return load_page_module(page)

    def __iter__(self) -> Iterator[str]:
        return iter(PAGE_MODULE_PATHS)

    def __len__(self) -> int:
        return len(PAGE_MODULE_PATHS)


PAGE_MODULES: Mapping[str, ModuleType] = LazyPageModules()


def install_import_compatibility() -> None:
    """Preserve historical Research Lab wiring expected immediately on workspace import."""
    load_page_module("Research Lab")
