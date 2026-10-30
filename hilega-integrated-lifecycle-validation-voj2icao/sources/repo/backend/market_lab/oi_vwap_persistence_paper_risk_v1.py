
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ExitDecision(str, Enum):
    HOLD = "HOLD"
    STOP_LOSS = "STOP_LOSS"
    BREAKEVEN = "BREAKEVEN"
    TRAILING_STOP = "TRAILING_STOP"


@dataclass
class PremiumExitState:
    entry_price: float
    hard_stop_pct: float = 5.0
    breakeven_activation_pct: float = 5.0
    trail_activation_pct: float = 10.0
    trail_distance_pct: float = 3.0

    breakeven_active: bool = False
    trailing_active: bool = False
    best_price: Optional[float] = None

    def __post_init__(self):
        if self.entry_price <= 0:
            raise ValueError("entry_price must be > 0")
        self.best_price = self.entry_price

    def evaluate(self, current_price: float) -> ExitDecision:
        if current_price <= 0:
            return ExitDecision.HOLD

        self.best_price = max(self.best_price or current_price, current_price)
        pnl_pct = (current_price / self.entry_price - 1.0) * 100.0

        if pnl_pct <= -self.hard_stop_pct:
            return ExitDecision.STOP_LOSS

        if pnl_pct >= self.breakeven_activation_pct:
            self.breakeven_active = True

        if pnl_pct >= self.trail_activation_pct:
            self.trailing_active = True

        if self.trailing_active:
            trailing_floor = (self.best_price or current_price) * (1.0 - self.trail_distance_pct / 100.0)
            if current_price <= trailing_floor:
                return ExitDecision.TRAILING_STOP

        if self.breakeven_active and current_price <= self.entry_price:
            return ExitDecision.BREAKEVEN

        return ExitDecision.HOLD
