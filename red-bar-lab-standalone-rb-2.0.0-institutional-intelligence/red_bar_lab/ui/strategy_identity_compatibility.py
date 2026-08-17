from __future__ import annotations

from dataclasses import replace


def install_strategy_identity_compatibility() -> None:
    """Emit canonical strategy ownership while preserving legacy read aliases."""
    from red_bar_lab.ui import strategy_execution_source_gate as gate_module

    current = gate_module.POLICIES["Directional Regime Intelligence"]
    if current.strategy_id != "DIRECTIONAL_REGIME":
        gate_module.POLICIES["Directional Regime Intelligence"] = replace(
            current,
            strategy_id="DIRECTIONAL_REGIME",
        )
