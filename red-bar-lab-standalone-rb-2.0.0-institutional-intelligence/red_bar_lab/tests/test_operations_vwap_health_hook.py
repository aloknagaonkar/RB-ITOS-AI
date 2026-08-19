from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from red_bar_lab.operations.service import (
    HealthItem,
    OperationsSnapshot,
    RedBarOperationsCenterService,
)
from red_bar_lab.ui.operations_vwap_health_hook import (
    install_operations_vwap_health_hook,
)


def _snapshot() -> OperationsSnapshot:
    return OperationsSnapshot(
        health_score=100,
        platform_health=(HealthItem("Database", "HEALTHY", "ok"),),
        market={},
        pipeline={},
        ai_readiness={},
        data_quality={},
        performance={},
        timeline=(),
    )


def test_operations_hook_appends_vwap_health_once(monkeypatch, tmp_path: Path):
    current = RedBarOperationsCenterService.snapshot
    original = getattr(current, "__wrapped__", current)
    monkeypatch.setattr(RedBarOperationsCenterService, "snapshot", original)

    def fake_snapshot(self, *args, **kwargs):
        return _snapshot()

    monkeypatch.setattr(RedBarOperationsCenterService, "snapshot", fake_snapshot)
    install_operations_vwap_health_hook()
    install_operations_vwap_health_hook()

    service = RedBarOperationsCenterService.__new__(RedBarOperationsCenterService)
    service.settings = SimpleNamespace(artifacts_root=tmp_path)
    result = service.snapshot(instrument_key="NIFTY")

    matching = [
        item
        for item in result.platform_health
        if item.name == "Red Bar V2 Futures VWAP"
    ]
    assert len(matching) == 1
    assert matching[0].state == "WARNING"
    assert "No historical replay" in matching[0].detail
    assert result.platform_health[0].name == "Database"
