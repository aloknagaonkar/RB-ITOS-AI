import inspect

from red_bar_lab.ui import workspace
from red_bar_lab.ui.pages import market_readiness


def test_workspace_exposes_trade_evidence_page():
    assert workspace._PAGE_MODULE_PATHS["Trade Evidence"] == "red_bar_lab.ui.pages.market_readiness"
    assert "Market Readiness" not in workspace._PAGE_MODULE_PATHS


def test_trade_evidence_page_consumes_authoritative_persisted_bundle():
    source = inspect.getsource(market_readiness.render_page)
    assert "read_latest_market_evidence_bundle(" in source
    assert "read_global_readiness_snapshots(" in source
    assert "Authoritative Market Evidence" in source
    assert "Legacy readiness diagnostics" in source

    # Rendering must not create a competing recommendation or recalculate
    # historical/shadow conclusions. Those belong to monitor/research runtimes.
    assert "build_independent_market_recommendation(" not in source
    assert "build_trade_evidence_recommendation(" not in source
    assert "build_global_readiness_shadow_report(" not in source
    assert "replay_global_readiness(" not in source

    # The workspace remains strictly observational and read-only.
    assert "automation.run_cycle" not in source
    assert "place_order" not in source
    assert "persist_market_evidence_bundle(" not in source
