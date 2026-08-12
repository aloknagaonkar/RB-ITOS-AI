from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExecutionIntent:
    intent_id: str
    signal_id: str
    instrument_token: int
    tradingsymbol: str
    exchange: str
    side: str
    quantity: int
    mode: str


class ExecutionProvider(Protocol):
    name: str
    mode: str

    def submit(self, intent: ExecutionIntent) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class ExecutionSafetyState:
    live_execution_enabled: bool
    kill_switch_active: bool
    market_hours_ok: bool
    instrument_verified: bool
    quantity_verified: bool
    duplicate_free: bool

    @property
    def live_allowed(self) -> bool:
        return (
            self.live_execution_enabled
            and not self.kill_switch_active
            and self.market_hours_ok
            and self.instrument_verified
            and self.quantity_verified
            and self.duplicate_free
        )


class ZerodhaLiveExecutionProvider:
    """Future live provider foundation.

    RB-0.7.4.6 hard-disables this provider. There is intentionally no broker
    order call here. Later releases can implement the same submit interface
    only after explicit live safety gates are introduced and validated.
    """

    name = "ZERODHA"
    mode = "LIVE"
    LIVE_EXECUTION_ENABLED = False

    def __init__(self, *, kill_switch_active: bool = True):
        self.kill_switch_active = bool(kill_switch_active)

    def safety_state(
        self,
        *,
        market_hours_ok: bool,
        instrument_verified: bool,
        quantity_verified: bool,
        duplicate_free: bool,
    ) -> ExecutionSafetyState:
        return ExecutionSafetyState(
            live_execution_enabled=self.LIVE_EXECUTION_ENABLED,
            kill_switch_active=self.kill_switch_active,
            market_hours_ok=market_hours_ok,
            instrument_verified=instrument_verified,
            quantity_verified=quantity_verified,
            duplicate_free=duplicate_free,
        )

    def submit(self, intent: ExecutionIntent) -> dict[str, object]:
        raise RuntimeError(
            "LIVE EXECUTION IS DISABLED in RB-0.7.4.6. "
            "The Zerodha live provider is foundation-only."
        )
