from __future__ import annotations

from dataclasses import dataclass
import os

from red_bar_lab.execution import paper_order_guard as _paper_order_guard

RED_BAR_V2_SOURCE = "RED_BAR_V2"
LEGACY_RED_BAR_SOURCE = "REFERENCE_LEVEL"
DRI_SOURCE = "DIRECTIONAL_REGIME_INTELLIGENCE"
RSI_REVERSAL_SOURCE = "RSI_EXTREME_REVERSAL_V1"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PaperStrategyAuthority:
    primary_red_bar_version: str = "v2"
    red_bar_v2_enabled: bool = True
    red_bar_v2_mode: str = "paper"
    legacy_red_bar_v1_enabled: bool = False
    dri_strategy_enabled: bool = False
    rsi_extreme_reversal_enabled: bool = False
    broker_execution_enabled: bool = False

    @classmethod
    def from_env(cls) -> "PaperStrategyAuthority":
        return cls(
            primary_red_bar_version=os.getenv(
                "RED_BAR_PRIMARY_VERSION", "v2"
            ).strip().lower(),
            red_bar_v2_enabled=_env_bool("RED_BAR_V2_ENABLED", True),
            red_bar_v2_mode=os.getenv(
                "RED_BAR_V2_MODE", "paper"
            ).strip().lower(),
            legacy_red_bar_v1_enabled=_env_bool(
                "RED_BAR_LEGACY_V1_ENABLED", False
            ),
            dri_strategy_enabled=_env_bool(
                "DRI_STRATEGY_ENABLED", False
            ),
            rsi_extreme_reversal_enabled=_env_bool(
                "RSI_EXTREME_REVERSAL_ENABLED", False
            ),
            broker_execution_enabled=_env_bool(
                "BROKER_EXECUTION_ENABLED", False
            ),
        )

    @property
    def v2_paper_active(self) -> bool:
        return bool(
            self.primary_red_bar_version == "v2"
            and self.red_bar_v2_enabled
            and self.red_bar_v2_mode == "paper"
            and not self.broker_execution_enabled
        )

    def source_enabled(self, strategy_source: str) -> bool:
        source = str(strategy_source or "").upper().strip()
        if source == RED_BAR_V2_SOURCE:
            return self.v2_paper_active
        if source == LEGACY_RED_BAR_SOURCE:
            return self.legacy_red_bar_v1_enabled
        if source in {DRI_SOURCE, RSI_REVERSAL_SOURCE}:
            return False
        return False

    def validate(self) -> tuple[bool, str]:
        if self.broker_execution_enabled:
            return False, "BROKER_EXECUTION_MUST_REMAIN_DISABLED"
        if self.primary_red_bar_version not in {"v1", "v2"}:
            return False, "INVALID_RED_BAR_PRIMARY_VERSION"
        if self.primary_red_bar_version == "v2" and not self.red_bar_v2_enabled:
            return False, "V2_SELECTED_BUT_DISABLED"
        if self.primary_red_bar_version == "v2" and self.red_bar_v2_mode != "paper":
            return False, "V2_PAPER_AUTHORITY_REQUIRES_PAPER_MODE"
        return True, "READY"

    def status_payload(self) -> dict[str, object]:
        valid, reason = self.validate()
        return {
            "status": "READY" if valid else "BLOCKED",
            "reason": reason,
            "primary_red_bar_engine": self.primary_red_bar_version.upper(),
            "red_bar_v2_mode": self.red_bar_v2_mode.upper(),
            "red_bar_v2_paper_authority": self.v2_paper_active,
            "legacy_red_bar_v1": "ENABLED" if self.legacy_red_bar_v1_enabled else "DISABLED",
            "dri_strategy": "RETIRED",
            "rsi_extreme_reversal": "RETIRED",
            "broker_execution": "ENABLED" if self.broker_execution_enabled else "DISABLED",
        }
