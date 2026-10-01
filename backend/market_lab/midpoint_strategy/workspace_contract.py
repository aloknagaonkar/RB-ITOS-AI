from __future__ import annotations

from .config import MidpointShadowConfig


def midpoint_workspace_status(config: MidpointShadowConfig | None = None) -> dict:
    cfg = config or MidpointShadowConfig()
    cfg.assert_safe()
    return {
        "workspace": "MIDPOINT_STRATEGY",
        "display_name": "Midpoint Strategy",
        "version": cfg.version,
        "mode": "SHADOW",
        "families": {
            "B": {"enabled": cfg.family_b_enabled},
            "E": {"enabled": cfg.family_e_enabled},
            "C": {"enabled": cfg.family_c_enabled},
            "BE_REARM": {"enabled": cfg.be_rearm_enabled},
            "D": {"enabled": cfg.family_d_enabled},
            "PM_E": {"enabled": cfg.pm_e_enabled},
        },
        "management": {
            "primary_exit_enabled": cfg.primary_exit_enabled,
            "cap20_rescue_enabled": cfg.cap20_rescue_enabled,
            "post_rescue_reentry_enabled": cfg.post_rescue_reentry_enabled,
            "post_rescue_reentry_window_minutes":
                cfg.post_rescue_reentry_window_minutes,
            "max_post_rescue_reentries": cfg.max_post_rescue_reentries,
            "second_rescue_after_reentry_enabled":
                cfg.second_rescue_after_reentry_enabled,
            "normal_b_proved_candidate_enabled":
                cfg.normal_b_proved_candidate_enabled,
            "degraded_exit_candidate_enabled":
                cfg.degraded_exit_candidate_enabled,
        },
        "safety": {
            "observation_only": cfg.observation_only,
            "execution_enabled": cfg.execution_enabled,
            "paper_order_enabled": cfg.paper_order_enabled,
            "quantity": cfg.quantity,
        },
    }
