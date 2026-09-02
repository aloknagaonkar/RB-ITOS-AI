import inspect

from red_bar_lab.ui import market_direction_validation_panel, workspace
from red_bar_lab.ui.pages import market_readiness


def test_workspace_exposes_trade_evidence_page():
    assert workspace._PAGE_MODULE_PATHS["Trade Evidence"] == "red_bar_lab.ui.pages.market_readiness"
    assert "Market Readiness" not in workspace._PAGE_MODULE_PATHS


def test_trade_evidence_page_consumes_authoritative_persisted_bundle():
    # The inline "Authoritative Evidence" tab was retired in 9821ef0 and
    # test_market_readiness_legacy_tab.py now forbids it. The page still
    # consumes the monitor-created authoritative bundle, one level down:
    # render_market_direction_validation_panel reads it. Assert the delegation
    # here and the read at its new home rather than re-requiring the old tab.
    source = inspect.getsource(market_readiness.render_page)
    assert "render_market_direction_summary(" in source
    assert "render_market_trend_research_panel(" in source
    assert "render_market_direction_validation_panel(" in source

    panel = inspect.getsource(market_direction_validation_panel)
    assert "read_latest_market_evidence_bundle(" in panel

    # The UI is a read-only consumer of the monitor-created authoritative bundle.
    assert "build_independent_market_recommendation(" not in source
    assert "build_trade_evidence_recommendation(" not in source
    assert "build_global_readiness_shadow_report(" not in source
    assert "replay_global_readiness(" not in source
    assert "persist_market_evidence_bundle(" not in source
    assert "automation.run_cycle" not in source
    assert "place_order" not in source
