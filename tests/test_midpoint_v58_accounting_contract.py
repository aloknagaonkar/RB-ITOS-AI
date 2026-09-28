from market_lab.midpoint_strategy.config import MidpointShadowConfig

def test_v58_safe_current_be_configuration():
    cfg=MidpointShadowConfig(); cfg.assert_safe()
    assert cfg.family_b_enabled is True
    assert cfg.family_e_enabled is True
    assert cfg.observation_only is True
    assert cfg.execution_enabled is False
    assert cfg.paper_order_enabled is False
    assert cfg.quantity is None
