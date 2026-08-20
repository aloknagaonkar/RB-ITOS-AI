import inspect

from red_bar_lab.ui import workspace
from red_bar_lab.ui.pages import market_readiness


def test_workspace_exposes_market_readiness_page():
    assert workspace._PAGE_MODULE_PATHS["Market Readiness"] == "red_bar_lab.ui.pages.market_readiness"


def test_market_readiness_page_is_persisted_and_observational():
    source = inspect.getsource(market_readiness.render_page)
    assert "read_global_readiness_snapshots(" in source
    assert "build_global_readiness_shadow_report(" in source
    assert "replay_global_readiness(" in source
    assert "no execution authority" in source
    assert "automation.run_cycle" not in source
    assert "place_order" not in source
