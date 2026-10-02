#!/usr/bin/env python3
from market_lab.midpoint_strategy.config import MidpointShadowConfig

cfg = MidpointShadowConfig()
cfg.assert_safe()

print("V56 FAMILY E LIVE-SHADOW CONFIG")
print("=" * 60)
for name in (
    "family_b_enabled", "family_e_enabled", "family_c_enabled",
    "family_d_enabled", "pm_e_enabled", "observation_only",
    "execution_enabled", "paper_order_enabled", "quantity",
):
    print(f"{name}={getattr(cfg, name)}")

assert cfg.family_b_enabled is True
assert cfg.family_e_enabled is True
assert cfg.family_c_enabled is False
assert cfg.family_d_enabled is False
assert cfg.pm_e_enabled is False
assert cfg.observation_only is True
assert cfg.execution_enabled is False
assert cfg.paper_order_enabled is False
assert cfg.quantity is None
print("PASS V56 safety/config")
