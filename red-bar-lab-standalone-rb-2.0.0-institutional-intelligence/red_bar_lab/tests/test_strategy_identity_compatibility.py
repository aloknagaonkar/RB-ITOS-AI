from __future__ import annotations

from dataclasses import replace

from red_bar_lab.ui import strategy_execution_source_gate as gate_module
from red_bar_lab.ui.strategy_identity_compatibility import (
    install_strategy_identity_compatibility,
)


def test_installer_canonicalizes_dri_strategy_id_and_is_idempotent():
    original = gate_module.POLICIES["Directional Regime Intelligence"]
    try:
        gate_module.POLICIES["Directional Regime Intelligence"] = replace(
            original,
            strategy_id="DIRECTIONAL_REGIME_INTELLIGENCE",
        )
        install_strategy_identity_compatibility()
        install_strategy_identity_compatibility()

        policy = gate_module.POLICIES["Directional Regime Intelligence"]
        assert policy.strategy_id == "DIRECTIONAL_REGIME"
        assert policy.strategy_owner == original.strategy_owner
        assert policy.enable_environment == original.enable_environment
    finally:
        gate_module.POLICIES["Directional Regime Intelligence"] = original
