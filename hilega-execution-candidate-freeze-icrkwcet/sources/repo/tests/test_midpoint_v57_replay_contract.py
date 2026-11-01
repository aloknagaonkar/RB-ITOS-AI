from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1

def test_v57_uses_current_safe_live_config():
    cfg = MidpointShadowConfig()
    cfg.assert_safe()
    assert cfg.family_b_enabled is True
    assert cfg.family_e_enabled is True
    assert cfg.observation_only is True
    assert cfg.execution_enabled is False
    assert cfg.paper_order_enabled is False
    assert cfg.quantity is None

def test_v57_replay_target_is_current_live_coordinator():
    assert MidpointLiveShadowCoordinatorV1.__name__ == "MidpointLiveShadowCoordinatorV1"
