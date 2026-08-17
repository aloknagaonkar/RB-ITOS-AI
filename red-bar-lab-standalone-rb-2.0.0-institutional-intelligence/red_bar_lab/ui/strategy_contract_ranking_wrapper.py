from __future__ import annotations

from functools import wraps
from types import ModuleType
from typing import Mapping

from red_bar_lab.ui.strategy_contract_ranking import (
    POLICIES as RANKING_POLICIES,
    rank_strategy_contracts,
    render_strategy_contract_ranking,
)
from red_bar_lab.ui.strategy_contract_readiness import build_contract_data_readiness
from red_bar_lab.ui.strategy_execution_source_gate import POLICIES, build_execution_source_gate


def build_contract_ranking_page_wrapper(module: ModuleType, page: str):
    """Append read-only Section 5B after the already-installed Section 5A wrapper."""
    policy = POLICIES[page]
    ranking_policy = RANKING_POLICIES[policy.strategy_id]
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
        resolution = captured.get("resolution") if isinstance(captured.get("resolution"), Mapping) else None
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
                "reason": "Database or instrument context is unavailable to Section 5B.",
                "strategy_id": policy.strategy_id,
                "signal_id": str(gate.get("signal_id") or "Not created"),
                "bundle_id": str(gate.get("bundle_id") or "Not created"),
                "requested_side": "Unavailable",
                "snapshot_timestamp": "Unavailable",
                "contract_rows": [],
            }
        else:
            readiness = build_contract_data_readiness(
                gate=gate,
                resolution=resolution,
                database=database,
                instrument_key=str(instrument_key),
            )
        ranking = rank_strategy_contracts(readiness, policy=ranking_policy)
        render_strategy_contract_ranking(ranking)
        return result

    setattr(module, policy.builder_name, capture_resolution)
    return wrapped_render
