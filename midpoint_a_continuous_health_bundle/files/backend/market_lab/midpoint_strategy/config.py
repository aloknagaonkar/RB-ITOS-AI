from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MidpointShadowConfig:
    """Frozen Phase-M1 rollout configuration.

    Safety invariants are deliberately explicit and immutable by default.
    """

    strategy_name: str = "MIDPOINT_STRATEGY"
    version: str = "shadow-v1"

    # Family A is a parallel, non-blocking observation lane.  It never owns
    # or suppresses the canonical B/E lifecycle.
    family_a_enabled: bool = False
    family_b_enabled: bool = True
    # V56: Family E is enabled for observation-only live shadow.
    family_e_enabled: bool = True
    family_c_enabled: bool = False
    # Replaces Family C with recursively repeatable canonical B/E revalidation.
    be_rearm_enabled: bool = False
    family_d_enabled: bool = False
    pm_e_enabled: bool = False

    observation_only: bool = True
    execution_enabled: bool = False
    paper_order_enabled: bool = False
    quantity: None = None

    # Frozen current Family-B management candidate.
    primary_exit_enabled: bool = False
    cap20_rescue_enabled: bool = True
    post_rescue_reentry_enabled: bool = False
    post_rescue_reentry_window_minutes: int = 20
    max_post_rescue_reentries: int = 1
    second_rescue_after_reentry_enabled: bool = False
    # Observation-only parallel exit candidate for proved NORMAL_B trades.
    normal_b_proved_candidate_enabled: bool = True
    # Observation-only candidate exit on the first DEGRADED_STARTED close.
    degraded_exit_candidate_enabled: bool = True
    # Parallel T+5 initial-risk observations; never authoritative exits.
    t5_two_of_three_candidate_enabled: bool = True
    t5_combined_edge_candidate_enabled: bool = True
    pre_entry_health_observation_enabled: bool = True
    continuous_health_exit_candidate_enabled: bool = False

    def assert_safe(self) -> None:
        if not self.observation_only:
            raise ValueError("Midpoint shadow-v1 must remain observation_only")
        if self.execution_enabled:
            raise ValueError("execution_enabled must remain false")
        if self.paper_order_enabled:
            raise ValueError("paper_order_enabled must remain false")
        if self.quantity is not None:
            raise ValueError("quantity must remain None")
        if not self.family_b_enabled:
            raise ValueError("Phase M1 requires Family B enabled")
        if self.family_d_enabled:
            raise ValueError("Family D is excluded from Midpoint live shadow")
        if self.family_c_enabled and self.be_rearm_enabled:
            raise ValueError("Family C and repeated B/E rearm are mutually exclusive")


def _enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean flag")


def live_shadow_config_from_env() -> MidpointShadowConfig:
    """Read observation-only family gates without exposing execution controls."""
    defaults = MidpointShadowConfig()
    config = MidpointShadowConfig(
        family_a_enabled=_enabled(
            "MIDPOINT_FAMILY_A_SHADOW_ENABLED", defaults.family_a_enabled
        ),
        family_c_enabled=_enabled(
            "MIDPOINT_FAMILY_C_SHADOW_ENABLED", defaults.family_c_enabled
        ),
        be_rearm_enabled=_enabled(
            "MIDPOINT_BE_REARM_SHADOW_ENABLED", defaults.be_rearm_enabled
        ),
        pm_e_enabled=_enabled(
            "MIDPOINT_PM_E_SHADOW_ENABLED", defaults.pm_e_enabled
        ),
        normal_b_proved_candidate_enabled=_enabled(
            "MIDPOINT_NORMAL_B_PROVED_CANDIDATE_ENABLED",
            defaults.normal_b_proved_candidate_enabled,
        ),
        degraded_exit_candidate_enabled=_enabled(
            "MIDPOINT_DEGRADED_EXIT_CANDIDATE_ENABLED",
            defaults.degraded_exit_candidate_enabled,
        ),
        t5_two_of_three_candidate_enabled=_enabled(
            "MIDPOINT_T5_TWO_OF_THREE_CANDIDATE_ENABLED",
            defaults.t5_two_of_three_candidate_enabled,
        ),
        t5_combined_edge_candidate_enabled=_enabled(
            "MIDPOINT_T5_COMBINED_EDGE_CANDIDATE_ENABLED",
            defaults.t5_combined_edge_candidate_enabled,
        ),
        pre_entry_health_observation_enabled=_enabled(
            "MIDPOINT_PRE_ENTRY_HEALTH_OBSERVATION_ENABLED",
            defaults.pre_entry_health_observation_enabled,
        ),
        continuous_health_exit_candidate_enabled=_enabled(
            "MIDPOINT_CONTINUOUS_HEALTH_EXIT_CANDIDATE_ENABLED",
            defaults.continuous_health_exit_candidate_enabled,
        ),
    )
    config.assert_safe()
    return config
