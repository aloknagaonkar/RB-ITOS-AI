from __future__ import annotations

from red_bar_lab.execution.attribution_automation import (
    AttributionAwarePaperAutomationService,
)


def test_dri_runtime_is_retired_by_default(monkeypatch):
    monkeypatch.delenv("DRI_STRATEGY_ENABLED", raising=False)

    assert AttributionAwarePaperAutomationService._dri_runtime_enabled() is False


def test_dri_background_refresh_reports_retired_state(monkeypatch):
    monkeypatch.setenv("DRI_STRATEGY_ENABLED", "false")
    service = object.__new__(AttributionAwarePaperAutomationService)

    result = service._refresh_directional_regime_background()

    assert result == {
        "status": "RETIRED",
        "reason": "STANDALONE_DRI_RETIRED",
    }


def test_dri_runtime_cannot_be_reenabled_by_environment(monkeypatch):
    monkeypatch.setenv("DRI_STRATEGY_ENABLED", "true")

    assert AttributionAwarePaperAutomationService._dri_runtime_enabled() is False
