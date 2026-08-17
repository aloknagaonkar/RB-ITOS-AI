from __future__ import annotations

from functools import wraps
from types import ModuleType
from typing import Mapping

from red_bar_lab.ui.strategy_contract_readiness import (
    build_contract_data_readiness,
    render_contract_data_readiness,
)
from red_bar_lab.ui.strategy_execution_source_gate import (
    POLICIES,
    build_execution_source_gate,
)


def build_contract_readiness_page_wrapper(module: ModuleType, page: str):
    """Append Section 5A after the existing Sections 1-4 without page rewrites."""
    policy = POLICIES[page]
    original_builder = getattr(module, policy.builder_name)
    original_render = module.render_page
    captured: dict[str, object] = {}

    @wraps(original_builder)
    def capture_resolution(*args, **kwargs):
        resolution = original_builder(*args, **kwargs)
        captured["resolution"] = resolution
        return resolution

    @wraps(original_render)
    def wrapped_render(*args, **kwargs):
        captured.clear()
        result = original_render(*args, **kwargs)
        resolution = (
            captured.get("resolution")
            if isinstance(captured.get("resolution"), Mapping)
            else None
        )
        gate = build_execution_source_gate(resolution, policy)

        database = kwargs.get("database")
        instrument_key = kwargs.get("instrument_key")
        if database is None and len(args) > 2:
            database = args[2]
        if instrument_key is None and len(args) > 5:
            instrument_key = args[5]

        if database is None or not instrument_key:
            readiness = {
                "outcome": "UNAVAILABLE",
                "reason": "Database or instrument context is unavailable to Section 5A.",
                "strategy_owner": policy.strategy_owner,
                "strategy_id": policy.strategy_id,
                "signal_id": str(gate.get("signal_id") or "Not created"),
                "bundle_id": str(gate.get("bundle_id") or "Not created"),
                "requested_side": "Unavailable",
                "bundle_timestamp": "Unavailable",
                "snapshot_timestamp": "Unavailable",
                "snapshot_relation": "UNAVAILABLE",
                "contracts_available": 0,
                "requested_side_contracts": 0,
                "ready_for_ranking": 0,
                "contract_rows": [],
                "checks": [],
                "next_step": "Restore page database and instrument context.",
            }
        else:
            readiness = build_contract_data_readiness(
                gate=gate,
                resolution=resolution,
                database=database,
                instrument_key=str(instrument_key),
            )
        render_contract_data_readiness(readiness)
        return result

    setattr(module, policy.builder_name, capture_resolution)
    return wrapped_render
