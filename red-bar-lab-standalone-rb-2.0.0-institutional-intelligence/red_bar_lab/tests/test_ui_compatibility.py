from pathlib import Path



def _ui_source() -> str:
    """Compatibility view of the modular UI source.

    Older regression tests intentionally inspect UI source strings. After
    RB-0.8.0 the UI is split across _shared.py + pages/, so synthesize the
    former page markers while preserving the original page order.

    Presentation logic later moved again, out of the page modules and into
    ``services/ui_business_logic.py`` (``_shared.py`` now thinly delegates to
    it). That module owns the row/column vocabulary these tests assert on, so
    it belongs in this synthesized view too.
    """
    ui_dir = Path(__file__).resolve().parents[1] / "ui"
    parts = [
        (ui_dir / "_shared.py").read_text(encoding="utf-8"),
        (ui_dir / "workspace.py").read_text(encoding="utf-8"),
        (
            Path(__file__).resolve().parents[1]
            / "services"
            / "ui_business_logic.py"
        ).read_text(encoding="utf-8"),
    ]
    pages = [
        ("Operations Center", "operations_center.py"),
        ("Paper Trading", "paper_trading.py"),
        ("Research Lab", "research_lab.py"),
        ("Live Trading", "live_trading.py"),
        ("Level Explorer", "level_explorer.py"),
        ("Signal Explorer", "signal_explorer.py"),
        ("Trade History", "trade_history.py"),
        ("Intelligence", "intelligence.py"),
    ]
    pages_dir = ui_dir / "pages"
    for page_name, filename in pages:
        parts.append(
            f'\nif page == "{page_name}":\n'
            + (pages_dir / filename).read_text(encoding="utf-8")
        )
    return "\n".join(parts)



def test_workspace_uses_new_streamlit_width_api_and_arrow_safe_rows():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "use_container_width=True" not in text
    assert "def _arrow_safe_rows(" in text
    assert '"successful_failed"' in text
    assert '"points_gained"' in text



def test_rb068_workspace_has_target_progress_and_drilldown():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert '"targets_hit"' in text
    assert '"points_to_next_target"' in text
    assert "live_signal_drilldown" in text
    assert "session_complete=_is_session_complete" in text



def test_rb069_workspace_has_completed_signals_and_numbering():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Completed Signals Today" in text
    assert '"signal_label"' in text
    assert '"signal_marker"' in text
    assert "completed_signal_drilldown" in text
    assert "Live / Open Signals" in text



def test_rb0610_workspace_has_backtest_filters():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Backtest Filters" in text
    assert "bt_filter_signal_type" in text
    assert "bt_filter_direction" in text
    assert "bt_filter_exit_model" in text
    assert "bt_filter_trade_result" in text
    assert "Models 1–10 are actionable" in text



def test_rb0611_workspace_has_quality_filters():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "bt_filter_signal_quality" in text
    assert "bt_filter_min_success_score" in text
    assert '"quality_explanation"' in text
    assert '"actionable_score"' in text
    assert '"quality_symbol"' in text



def test_rb0612_workspace_has_tx_fields():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Precise Entry / Exit" in text
    assert "Trade Timeline" in text
    assert "Current P/L" in text
    assert "EOD Benchmark" in text
    assert "entry_time_ist" in text
    assert "best_exit_time" in text
    assert "trade_status" in text



def test_rb06121_has_current_trade_dashboard_above_live_signals():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()

    dashboard = text.index('st.markdown("#### Current Trade Dashboard")')
    live = text.index('st.markdown("#### Live / Open Signals")')
    assert dashboard < live

    assert '"entry_time_ist"' in text
    assert '"entry_price"' in text
    assert '"current_price"' in text
    assert '"current_p_l"' in text
    assert '"exit_time_ist"' in text
    assert '"exit_price"' in text
    assert '"best_p_l"' in text
    assert '"score"' in text
    assert '"quality"' in text



def test_rb070_workspace_has_intelligence_foundation():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Intelligence Foundation" in text
    assert "Build Intelligence Dataset" in text



def test_rb071_workspace_has_market_context_engine():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Market Context Engine" in text
    assert "Build Market Context" in text
    assert "RedBarMarketContextService" in text



def test_rb072_workspace_has_volume_structure_context():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Volume & Structure Context" in text
    assert "Build Volume & Structure Context" in text
    assert "RedBarVolumeStructureService" in text



def test_rb073_workspace_navigation_architecture():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    for page in (
        "Dashboard",
        "Live Trading",
        "Research Lab",
        "Signal Explorer",
        "Level Explorer",
        "Trade History",
        "Intelligence",
    ):
        assert page in text
    assert 'st.sidebar.radio(' in text


def test_rb073_live_page_has_no_context_builders():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    live_start = text.index('if page == "Live Trading"')
    level_start = text.index('if page == "Level Explorer"')
    live_block = text[live_start:level_start]
    assert "Build Market Context" not in live_block
    assert "Build Volume & Structure Context" not in live_block
    assert "Build Intelligence Dataset" not in live_block


def test_rb073_intelligence_workspace_contains_context_and_health():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    intel_start = text.index('if page == "Intelligence"')
    intel_block = text[intel_start:]
    assert "Market Context Engine" in intel_block
    assert "Volume & Structure Context" in intel_block
    assert "Options Context" in intel_block
    assert "Intelligence Foundation" in intel_block
    assert "Dataset Health" in intel_block



def test_rb074_intelligence_has_options_infrastructure():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    intel = text[text.index('if page == "Intelligence"'):]
    assert "Capture Options Context for Today's Confirmed Signals" in intel
    assert "Import Options Context CSV" in intel
    assert "Entry alignment window" in intel
    assert "Options Context" in intel
    assert "RedBarFeatureStore" in text



def test_rb074_live_auto_capture_is_non_intrusive():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    live_start = text.index('if page == "Live Trading"')
    level_start = text.index('if page == "Level Explorer"')
    live = text[live_start:level_start]
    assert "capture_recent_missing_signals" in live
    assert "Entry alignment window" not in live
    assert "Capture Options Context for Today's Confirmed Signals" not in live



def test_rb0741_intelligence_has_dual_collector_panel():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    intel = text[text.index('if page == "Intelligence"'):]
    assert "Dual Market Data Collector" in intel
    assert "Run Online Collector Tick" in intel
    assert "Run Offline / EOD Collector Tick" in intel
    assert "run_market_collector.ps1" in intel


def test_rb0741_live_fallback_capture_remains_present():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    live_start = text.index('if page == "Live Trading"')
    level_start = text.index('if page == "Level Explorer"')
    live = text[live_start:level_start]
    assert "capture_recent_missing_signals" in live



def test_rb0742_intelligence_pipeline_is_automatic():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Automatic Intelligence Pipeline" in text
    assert "Maintenance / Backfill" in text
    live_start = text.index('if page == "Live Trading"')
    level_start = text.index('if page == "Level Explorer"')
    live = text[live_start:level_start]
    assert "pipeline.sync_day" in live
    assert "Intelligence pipeline synchronized automatically" in live



def test_rb0743_intelligence_has_historical_options_backfill():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    intel = text[text.index('if page == "Intelligence"'):]
    assert "Historical Options Backfill" in intel
    assert "Backfill Historical Options Data" in intel
    assert "Historical Options EOD Context" in intel
    assert "entry-aligned HYBRID features" in intel



def test_rb0744_operations_center_workspace_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert '"Operations Center"' in text
    ops = text[text.index('if page == "Operations Center"'):]
    for heading in (
        "Overall Health",
        "Platform Health",
        "Market Operations",
        "Intelligence Pipeline",
        "AI Readiness",
        "Data Quality",
        "Performance & Storage",
        "Today's Timeline",
    ):
        assert heading in ops
    assert "RedBarOperationsCenterService" in text



def test_rb0745_paper_trading_workspace_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert '"Paper Trading"' in text
    paper = text[text.index('if page == "Paper Trading"'):]
    candidate_ui = text
    assert "Paper Trading Command Center" in paper
    assert "Execution" in paper
    assert "Live Orders" in paper
    assert "HARD DISABLED" in paper
    assert "Top CE / PE Candidates" in paper
    assert "Open Virtual Position" in paper
    assert "Open Paper Position" in paper
    assert "Selected Option Candle" in paper
    assert "Paper Trade Journal & Statistics" in paper



def test_rb0745_platform_launcher_can_start_paper_monitor():
    root = Path(__file__).resolve().parents[2]
    launcher = (root / "start_red_bar_platform.ps1").read_text(
        encoding="utf-8"
    )
    monitor = (root / "run_paper_monitor.ps1").read_text(
        encoding="utf-8"
    )
    assert "UPSTOX_ACCESS_TOKEN" in launcher
    assert "run_paper_monitor.ps1" in launcher
    assert "UPSTOX_ACCESS_TOKEN" in monitor
    assert "red_bar_lab.execution.paper_monitor" in monitor



def test_rb0746_paper_automation_and_live_foundation_visible():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    assert "Run Automatic Paper Cycle Now" in paper
    assert "RULE-BASED PAPER RECOMMENDATION" in text
    assert "Execution Timeline" in paper
    assert "HARD DISABLED" in paper
    assert "ZerodhaLiveExecutionProvider" in text

def test_rb0747_paper_trading_uses_upstox_market_intelligence():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    candidate_ui = text
    assert 'metric("Market Data", "UPSTOX")' in paper
    assert (
        "from red_bar_lab.market.upstox_intelligence import "
        "UnifiedUpstoxMarketIntelligenceService"
    ) in text
    assert (
        "from red_bar_lab.market.paper_adapter import "
        "UpstoxPaperMarketAdapter"
    ) in text
    assert "Market Health & Paper Account" in paper



def test_rb0748_paper_command_center_sections_exist():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    candidate_ui = text
    for section in (
        "Command Status",
        "Market Health & Paper Account",
        "Current Red Bar Decision",
        "Top CE / PE Candidates",
        "Paper Execution",
        "Open Paper Position",
        "Selected Option Candle",
        "Why This Option?",
        "Execution Timeline",
        "Paper Trade Journal & Statistics",
        "AI Status",
    ):
        assert section in paper



def test_rb0749_trader_dashboard_features_exist():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    candidate_ui = text
    for section in (
        "Trader Recommendation",
        "Rule Confidence",
        "Entry Reference",
        "Paper Stop",
        "Target 1",
        "Target 2",
        "Risk",
        "Momentum %",
        "Candle Bars",
    ):
        assert section in candidate_ui
    assert "Auto-refresh live paper status every 5 seconds" in paper
    assert "location.reload" not in _ui_source()



def test_rb07410_paper_automation_observability_ui_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    candidate_ui = text
    for label in (
        "Paper Automation Status",
        "Background Monitor",
        "Heartbeat",
        "Current State",
        "Automatic Execution Eligibility",
        "Signal Age",
        "Freshness Gate",
        "Monitor Result",
        "Why Was / Wasn't a Paper Trade Executed?",
        "Duplicate Free",
        "Score Gate",
    ):
        assert label in candidate_ui



def test_rb075_trade_lifecycle_and_stable_navigation_exist():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert 'st.query_params.get("page"' in text
    assert 'st.query_params["page"] = page' in text
    paper = text[text.index('if page == "Paper Trading"'):]
    candidate_ui = text
    for label in (
        "Trade Lifecycle & Provenance",
        "Signal Type",
        "Execution Delay",
        "Opened By",
        "Inspect Trade Lifecycle",
        "Trade Timeline",
        "CLOSED_PROFIT",
        "CLOSED_LOSS",
        "Result",
        "Holding",
    ):
        assert label in paper



def test_rb0761_side_by_side_shadow_intelligence_ui_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "Decision Engine Comparison" in text
    assert "RULE EVIDENCE — CANDIDATE DETAIL" in text
    assert "INTELLIGENCE EVIDENCE — CANDIDATE DETAIL" in text
    assert "SHADOW ANALYSIS" in text
    assert "Execution Impact = NONE" in text

def test_rb0762_shadow_validation_dashboard_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    intelligence = text[text.index('if page == "Intelligence"'):]
    for label in (
        "Shadow Validation Dashboard",
        "Current Engine Win Rate",
        "Shadow Accuracy",
        "Resolved Shadow Samples",
        "Agreement Rate",
        "Agreement Win Rate",
        "Recommendation Stability",
        "Intelligence Scoreboard",
        "Promotion Candidates",
        "Agreement Analytics",
        "UNRESOLVED",
    ):
        assert label in intelligence
    assert "Shadow Validation Snapshot" in text



def test_rb077_clickable_top5_candidate_inspection_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    for label in (
        "Top Ranked Candidates",
        "Inspect Candidate / Analyse Candidate",
        "Candidate Detail — Committee Inspection",
        "Candidate Health",
        "Candidate Score & Contribution Breakdown",
    ):
        assert label in text
    assert "paper_candidate_radio" in text
    assert "paper_inspected_candidate_symbol" in text

def test_rb0773_details_are_driven_by_selector_symbol():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert 'key="paper_candidate_radio"' in text
    assert "selected_symbol = symbol_by_label[selected_label]" in text
    assert "paper_inspected_candidate_symbol" in text
    assert "selected_row = next(" in text

def test_rb078_candidate_workbench_and_comparison_exist():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    for label in (
        "Candidate Detail — Committee Inspection",
        "Decision Engine Comparison",
        "RULE EVIDENCE — CANDIDATE DETAIL",
        "INTELLIGENCE EVIDENCE — CANDIDATE DETAIL",
    ):
        assert label in text
    assert 'horizontal=True' in text

def test_rb078_execution_candidate_remains_rank_one():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    assert "current_best = ranked_rows[0] if ranked_rows else None" in paper
    assert "execution_candidate = ranked_rows[0]" in text

def test_rb0781_performance_optimizations_exist():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "@st.cache_resource" in text
    assert "_cached_paper_market_stack" in text
    assert "_cached_database" in text
    assert "@st.fragment" in text
    assert "_render_candidate_workbench_fragment" in text
    assert "Load Trade Lifecycle & Provenance" in text
    assert "Load Advanced Diagnostics, Timeline & Journal" in text


def test_rb0781_market_adapter_has_candle_cache():
    path = (
        Path(__file__).resolve().parents[1]
        / "market"
        / "paper_adapter.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "_candle_cache" in text
    assert "candle_cache_ttl_seconds" in text
    assert "monotonic" in text


def test_rb0781_execution_engine_still_uses_rank_one():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    assert "current_best = ranked_rows[0] if ranked_rows else None" in paper

def test_rb0782_selected_rank_drives_both_analysis_engines():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "RULE EVIDENCE — CANDIDATE DETAIL" in text
    assert "INTELLIGENCE EVIDENCE — CANDIDATE DETAIL" in text
    assert "Both panels analyse the SAME selected Rank" in text
    assert "selected_row" in text
    assert "best_candidate=selected_row" in text
    assert "Rank is discovery order only" in text
    assert "Institutional Execution Committee" in text
    assert "Why Rank #" in text
    assert "Where selected candidate is stronger" in text
    assert "Where Rank #1 has the advantage" in text


def test_rb0782_only_rank_one_shadow_is_persisted():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "if current_signal_id and selected_rank == 1:" in text
    assert "insert_shadow_intelligence_evaluation" in text


def test_rb0782_automatic_execution_engine_remains_rank_one():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    paper = text[text.index('if page == "Paper Trading"'):]
    assert "current_best = ranked_rows[0] if ranked_rows else None" in paper
    assert "execution_candidate = ranked_rows[0]" in text


def test_rb079_exit_engine_ui_and_removed_panel():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    for label in (
        "Paper Exit Engine",
        "POSITION & PROTECTION",
        "EXIT HEALTH",
        "EXIT DECISION",
        "Trade Health",
        "Initial SL",
        "Breakeven",
        "Trailing Stop",
        "NIFTY Thesis",
        "Opposite Red Bar",
        "Option VWAP",
        "Option EMA",
        "Momentum",
        "OI / PCR",
        "Greeks",
        "Exit Timeline",
    ):
        assert label in text

def test_rb079_automation_uses_new_exit_engine():
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "automation.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "PaperExitEngine" in text
    assert "AUTO_" in text
    assert "update_paper_exit_protection" in text
    assert "hard_exit_reason" in text



def test_rb0791_candidate_panel_restored_and_chart_removed():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()

    for label in (
        "Discovery Leader / Candidate Detail",
        "Execution Candidate",
        "Candidate Detail",
        "Compare Two Candidates",
        "Candidate A",
        "Candidate B",
        "Difference vs Rank #1",
        "Rule-score winner:",
    ):
        assert label in text

    assert "Recommended Option Candle — Selected Candidate" not in text


def test_rb0791_exit_engine_stays_intact():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    assert "_render_paper_exit_engine_panel" in text
    assert "Paper Exit Engine" in text



def test_rb0792_exit_engine_visual_completion():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    for label in (
        "POSITION & PROTECTION",
        "EXIT HEALTH",
        "EXIT DECISION",
        "PROTECT PROFIT",
        "TIGHTEN STOP",
        "EXIT NOW",
        "Trade Health",
        "Exit Pressure",
        "Primary Reason",
        "Additional Confirmation",
        "Exit Reason Code",
        "Next Trigger",
        "Hard/operational conditions can exit",
        "+15% · BREAKEVEN ARMED",
        "+20% · TRAILING ACTIVE",
        "TRAIL UPDATED",
        "EXIT / CLOSED",
    ):
        assert label in text


def test_rb0792_exit_milestones_are_recorded():
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "automation.py"
    )
    text = path.read_text(encoding="utf-8")
    for state in (
        'state="BREAKEVEN_ARMED"',
        'state="TRAILING_ACTIVATED"',
        'state="TRAIL_UPDATED"',
        'state="EXIT_TRIGGERED"',
    ):
        assert state in text
    assert "combined_reason" in text
    assert "previous_trail" in text


def test_rb0792_exit_rules_remain_unchanged():
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "exit_engine.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "breakeven_trigger_pct: float = 15.0" in text
    assert "trailing_trigger_pct: float = 20.0" in text
    assert "trailing_distance_pct: float = 10.0" in text
    assert 'hard_exit_reason = "TARGET_1"' in text
    assert 'hard_exit_reason = "EOD_EXIT"' in text
    assert 'hard_exit_reason = "NIFTY_INVALIDATION"' in text
    assert 'hard_exit_reason = "OPPOSITE_RED_BAR"' in text
    assert 'hard_exit_reason = "OPTION_TECHNICAL_BREAKDOWN"' in text



def test_rb0793_exit_engine_idle_preview_exists():
    path = Path(__file__).resolve().parents[1] / "ui" / "workspace.py"
    text = _ui_source()
    for label in (
        "Paper Exit Engine — IDLE",
        "PROTECTION RULES",
        "EXIT AUTHORITY",
        "SHADOW / ADVISORY",
        "Initial Premium SL",
        "Breakeven",
        "Trailing Activation",
        "Trailing Distance",
        "Target 1",
        "Target 2",
        "NIFTY Thesis Invalidation",
        "Opposite Red Bar",
        "Option Technical Breakdown",
        "WAIT",
    ):
        assert label in text
    assert "_render_paper_exit_engine_idle_panel()" in text


def test_rb0793_idle_preview_does_not_change_exit_rules():
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "exit_engine.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "breakeven_trigger_pct: float = 15.0" in text
    assert "trailing_trigger_pct: float = 20.0" in text
    assert "trailing_distance_pct: float = 10.0" in text



def test_rb080_modular_ui_and_fragment_refresh_architecture():
    ui_dir = Path(__file__).resolve().parents[1] / "ui"
    workspace = (ui_dir / "workspace.py").read_text(encoding="utf-8")
    shared = (ui_dir / "_shared.py").read_text(encoding="utf-8")
    paper = (
        ui_dir / "pages" / "paper_trading.py"
    ).read_text(encoding="utf-8")

    assert len(workspace.splitlines()) < 150
    assert "_PAGE_MODULES" in workspace
    assert "operations_center" in workspace
    assert "paper_trading" in workspace
    assert "live_trading" in workspace
    assert "intelligence" in workspace

    assert '@st.fragment(run_every="5s")' in shared
    assert "_render_paper_live_status_fragment" in shared
    assert "read_open_paper_execution_orders" in shared
    assert "location.reload" not in shared
    assert "location.reload" not in paper
    assert "setTimeout" not in paper

    assert "Performance Diagnostics" in paper
    assert "TOTAL PAGE RENDER" in paper
    assert "Slowest Section" in paper
    assert "not cached to avoid stale trading state" in paper


def test_rb080_page_modules_exist():
    pages = (
        Path(__file__).resolve().parents[1] / "ui" / "pages"
    )
    expected = {
        "operations_center.py",
        "paper_trading.py",
        "research_lab.py",
        "live_trading.py",
        "level_explorer.py",
        "signal_explorer.py",
        "trade_history.py",
        "intelligence.py",
    }
    assert expected.issubset({path.name for path in pages.glob("*.py")})



def test_rb080_paper_page_has_no_runtime_statements_at_module_scope():
    path = (
        Path(__file__).resolve().parents[1]
        / "ui"
        / "pages"
        / "paper_trading.py"
    )
    source = path.read_text(encoding="utf-8")
    import ast

    tree = ast.parse(source)
    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    assert all(isinstance(node, allowed) for node in tree.body)



def test_rb090_opportunity_extension_ui_exists():
    text = _ui_source()
    for label in (
        "Opportunity Health Engine",
        "Entry Mode",
        "Opportunity Health",
        "Reward Remaining",
        "Move Consumed",
        "OLDER SIGNAL / STRONG OPPORTUNITY",
        "OLDER SIGNAL / WEAK OPPORTUNITY",
        "OPPORTUNITY_EXTENSION",
        "Health ≥75",
        "Age has zero execution weight",
    ):
        assert label in text


def test_rb090_old_signal_is_not_age_only_rejected_in_automation_source():
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "automation.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "enable_opportunity_extension: bool = True" in text
    assert "stale_for_extension" in text
    assert "OpportunityIntelligenceEngine" in text
    assert "OPPORTUNITY_EXTENSION_APPROVED" in text
    assert "SKIPPED_OPPORTUNITY" in text
    assert "AUTO_OPPORTUNITY_EXTENSION" in text
    assert "update_paper_entry_intelligence" in text


def test_rb090_opportunity_history_schema_exists():
    path = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "database.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS opportunity_evaluations" in text
    assert "entry_mode" in text
    assert "signal_age_at_entry" in text
    assert "opportunity_score" in text
    assert "reward_remaining_pct" in text
    assert "insert_opportunity_evaluation" in text
    assert "read_opportunity_evaluations" in text



def test_rb090_opportunity_extension_ui_and_execution_wiring():
    root = Path(__file__).resolve().parents[1]
    paper = (
        root / "ui" / "pages" / "paper_trading.py"
    ).read_text(encoding="utf-8")
    automation = (
        root / "execution" / "automation.py"
    ).read_text(encoding="utf-8")
    database = (
        root / "storage" / "database.py"
    ).read_text(encoding="utf-8")

    for label in (
        "Opportunity Health Engine",
        "Opportunity Health",
        "Reward Remaining",
        "Move Consumed",
        "OLDER SIGNAL / STRONG OPPORTUNITY",
        "OLDER SIGNAL / WEAK OPPORTUNITY",
    ):
        assert label in paper

    assert "enable_opportunity_extension: bool = True" in automation
    assert "OPPORTUNITY_EXTENSION_APPROVED" in automation
    assert "SKIPPED_OPPORTUNITY" in automation
    assert "AUTO_OPPORTUNITY_EXTENSION" in automation
    assert "update_paper_entry_intelligence" in automation

    assert "CREATE TABLE IF NOT EXISTS opportunity_evaluations" in database
    assert '"entry_mode": "TEXT"' in database
    assert '"signal_age_at_entry": "REAL"' in database
    assert '"opportunity_score": "REAL"' in database
    assert '"reward_remaining_pct": "REAL"' in database


def test_rb_0_9_4_execution_committee_dashboard_copy_present():
    text = _ui_source()

    assert "Execution Committee Dashboard" in text
    assert "Institutional Execution Committee — Candidate Detail" in text
    assert "Rank is discovery order only" in text
    assert "COMMITTEE CONTROLLED" in text

