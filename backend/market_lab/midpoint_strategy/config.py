from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MidpointShadowConfig:
    """Frozen Phase-M1 rollout configuration.

    Safety invariants are deliberately explicit and immutable by default.
    """

    strategy_name: str = "MIDPOINT_STRATEGY"
    version: str = "shadow-v1"

    family_b_enabled: bool = True
    # V56: Family E is enabled for observation-only live shadow.
    family_e_enabled: bool = True
    family_c_enabled: bool = False
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
        if self.family_c_enabled or self.family_d_enabled or self.pm_e_enabled:
            raise ValueError("V56 live shadow enables only Family B + Family E")
