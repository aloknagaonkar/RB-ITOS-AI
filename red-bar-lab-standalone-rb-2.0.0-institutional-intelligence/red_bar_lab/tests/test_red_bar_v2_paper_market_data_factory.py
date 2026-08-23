from dataclasses import replace
from pathlib import Path

import pytest

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.run_red_bar_v2_paper_canary import (
    PaperCanaryStartupAction,
    evaluate_paper_canary_startup,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataConfigurationError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_factory import (
    build_paper_canary_market_data,
)


def _settings(provider="UNCONFIGURED"):
    return replace(
        RedBarSettings(),
        red_bar_v2_paper_canary_worker_enabled=True,
        red_bar_v2_canonical_shadow_enabled=True,
        red_bar_v2_canonical_reservation_enabled=True,
        red_bar_v2_canonical_paper_execution_enabled=True,
        red_bar_v2_canonical_paper_execution_mode="PAPER_CANARY",
        red_bar_v2_paper_canary_market_data_provider=provider,
    )


def test_startup_requires_explicit_provider_without_credentials():
    missing = evaluate_paper_canary_startup(_settings())
    assert missing.action is PaperCanaryStartupAction.CONFIGURATION_INVALID
    assert missing.reason_code == "MARKET_DATA_PROVIDER_UNCONFIGURED"
    invalid = evaluate_paper_canary_startup(_settings("INVALID"))
    assert invalid.reason_code == "MARKET_DATA_PROVIDER_INVALID"
    assert evaluate_paper_canary_startup(_settings("UPSTOX")).runtime_construction_allowed is True


def test_factory_fails_closed_for_provider_specific_missing_credentials():
    with pytest.raises(PaperMarketDataConfigurationError, match="UPSTOX_CONFIGURATION_MISSING"):
        build_paper_canary_market_data(settings=_settings("UPSTOX"), environment={})
    with pytest.raises(PaperMarketDataConfigurationError, match="ZERODHA_CONFIGURATION_MISSING"):
        build_paper_canary_market_data(settings=_settings("ZERODHA"), environment={})


def test_factory_constructs_only_selected_provider():
    upstox = build_paper_canary_market_data(
        settings=_settings("UPSTOX"),
        environment={"UPSTOX_ACCESS_TOKEN": "test-token"},
    )
    assert upstox.provider_name == "UPSTOX"
    zerodha = build_paper_canary_market_data(
        settings=_settings("ZERODHA"),
        environment={"ZERODHA_API_KEY": "key", "ZERODHA_ACCESS_TOKEN": "token"},
    )
    assert zerodha.provider_name == "ZERODHA"


def test_runner_has_no_live_execution_imports():
    source = Path(
        "red_bar_lab/execution/run_red_bar_v2_paper_canary.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "ZerodhaLiveExecutionProvider",
        "live order adapter",
        "place_order",
        "modify_order",
        "cancel_order",
    )
    assert all(item not in source for item in forbidden)
