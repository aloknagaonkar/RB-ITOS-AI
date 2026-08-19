from __future__ import annotations

from dataclasses import replace
from functools import wraps

from red_bar_lab.operations.red_bar_v2_vwap_source import operations_health_row
from red_bar_lab.operations.service import (
    HealthItem,
    RedBarOperationsCenterService,
)


_PATCH_MARKER = "_red_bar_v2_vwap_health_hook_applied"


def install_operations_vwap_health_hook() -> None:
    """Append persisted Red Bar V2 VWAP health to Operations Center output.

    The existing Operations Center page already renders every ``platform_health``
    item. This hook keeps the page and strategy logic unchanged while exposing
    the durable historical-replay data-lineage record through that established
    UI contract.
    """
    snapshot_method = RedBarOperationsCenterService.snapshot
    if getattr(snapshot_method, _PATCH_MARKER, False):
        return

    @wraps(snapshot_method)
    def snapshot_with_vwap_health(self, *args, **kwargs):
        snapshot = snapshot_method(self, *args, **kwargs)
        row = operations_health_row(self.settings.artifacts_root)
        item = HealthItem(
            name=str(row.get("Service") or "Red Bar V2 Futures VWAP"),
            state=str(row.get("State") or "WARNING"),
            detail=str(row.get("Detail") or "No health detail is available."),
        )
        existing = tuple(
            health
            for health in snapshot.platform_health
            if health.name != item.name
        )
        return replace(snapshot, platform_health=existing + (item,))

    setattr(snapshot_with_vwap_health, _PATCH_MARKER, True)
    RedBarOperationsCenterService.snapshot = snapshot_with_vwap_health
