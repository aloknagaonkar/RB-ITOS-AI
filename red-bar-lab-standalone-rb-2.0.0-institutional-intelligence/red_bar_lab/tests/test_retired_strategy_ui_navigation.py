from __future__ import annotations

import pytest

from red_bar_lab.ui.workspace_page_runtime import (
    PAGE_MODULE_PATHS,
    RETIRED_PAGE_MODULE_PATHS,
    load_page_module,
)


@pytest.mark.parametrize(
    "page",
    (
        "Directional Regime Intelligence",
        "RSI Extreme Reversal",
    ),
)
def test_retired_strategy_pages_are_not_active_workspace_navigation(page: str):
    assert page not in PAGE_MODULE_PATHS
    assert page in RETIRED_PAGE_MODULE_PATHS


@pytest.mark.parametrize(
    "page",
    (
        "Directional Regime Intelligence",
        "RSI Extreme Reversal",
    ),
)
def test_retired_strategy_pages_cannot_be_loaded_from_active_registry(page: str):
    with pytest.raises(KeyError):
        load_page_module(page)


def test_red_bar_strategy_remains_active_workspace_navigation():
    assert PAGE_MODULE_PATHS["Red Bar Strategy"] == (
        "red_bar_lab.ui.pages.red_bar_strategy"
    )
