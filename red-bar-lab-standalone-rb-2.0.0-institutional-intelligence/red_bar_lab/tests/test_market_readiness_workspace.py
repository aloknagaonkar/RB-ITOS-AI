import inspect

from red_bar_lab.ui import workspace
from red_bar_lab.ui.pages import market_readiness


def test_workspace_exposes_trade_evidence_page():
    assert workspace._PAGE_MODULE_PATHS["Trade Evidence"] == "red_bar_lab.ui.pages.market_readiness"
    assert "Market Readiness" not in workspace._PAGE_MODULE_PATHS


def test_trade_evidence_page_consumes_authoritative_persisted_bundle():
    source = inspect.getsource(market_readiness.render_page)
    # The page delegates the persisted-bundle consumption to the
    # authoritative renderers (which read the monitor-created bundle).
    assert "render_market_direction_summary(" in source
    assert "render_market_direction_validation_panel(" in source
    assert "Authoritative market conclusion" in source
    assert "Authoritative evidence diagnostics" in source
    assert "Persisted evidence bundle" in source
    assert "Legacy global readiness diagnostics" in source

    # The UI is a read-only consumer of the monitor-created authoritative bundle.
    assert "build_independent_market_recommendation(" not in source
    assert "build_trade_evidence_recommendation(" not in source
    assert "build_global_readiness_shadow_report(" not in source
    assert "replay_global_readiness(" not in source
    assert "persist_market_evidence_bundle(" not in source
    assert "automation.run_cycle" not in source
    assert "place_order" not in source
