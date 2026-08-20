import inspect

from red_bar_lab.ui import workspace
from red_bar_lab.ui.pages import nifty_futures_readiness


def test_workspace_exposes_nifty_futures_readiness_page():
    assert workspace._PAGE_MODULE_PATHS["NIFTY Futures Readiness"] == (
        "red_bar_lab.ui.pages.nifty_futures_readiness"
    )


def test_readiness_page_is_observational_and_uses_persisted_snapshots():
    source = inspect.getsource(nifty_futures_readiness.render_page)

    assert "read_nifty_futures_snapshots(" in source
    assert "validate_nifty_futures_shadow_session(" in source
    assert "replay_nifty_futures_strength_thresholds(" in source
    assert "execution authority" in source
    assert "automation.run_cycle" not in source
    assert "place_order" not in source
