import inspect

from red_bar_lab.ui import workspace
from red_bar_lab.ui.pages import market_readiness


def test_workspace_exposes_trade_evidence_page():
    assert workspace._PAGE_MODULE_PATHS["Trade Evidence"] == "red_bar_lab.ui.pages.market_readiness"
    assert "Market Readiness" not in workspace._PAGE_MODULE_PATHS


def test_trade_evidence_page_is_persisted_and_observational():
    source = inspect.getsource(market_readiness.render_page)
    assert "build_trade_evidence_recommendation(" in source
    assert "read_global_readiness_snapshots(" in source
    assert "read_nifty_futures_snapshots(" in source
    assert "build_global_readiness_shadow_report(" in source
    assert "replay_global_readiness(" in source
    assert "OBSERVATIONAL_ONLY" not in source or "observational" in source.lower()
    assert "automation.run_cycle" not in source
    assert "place_order" not in source
