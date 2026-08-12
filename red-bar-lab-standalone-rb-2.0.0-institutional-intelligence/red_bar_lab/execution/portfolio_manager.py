from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class PortfolioCandidate:
    queue_id: str
    signal_id: str
    symbol: str
    option_type: str
    rank: int
    candidate_score: float
    opportunity_health: float
    expectancy_pct: float
    reference_price: float
    stop_loss_pct: float
    quantity: int

    @property
    def estimated_capital(self) -> float:
        return max(0.0, self.reference_price) * max(0, self.quantity)

    @property
    def estimated_risk(self) -> float:
        return self.estimated_capital * max(0.0, self.stop_loss_pct) / 100.0

    @property
    def priority(self) -> tuple[float, float, float, float]:
        return (float(self.opportunity_health), float(self.expectancy_pct), float(self.candidate_score), -float(self.rank))

@dataclass(frozen=True)
class PortfolioAdmission:
    queue_id: str
    admitted: bool
    status: str
    reason: str
    risk_used: float
    capital_used: float

class PortfolioRiskManager:
    """Admit multiple qualified paper trades within exposure/risk budgets."""
    def __init__(self, *, maximum_open_trades: int = 5, maximum_same_direction: int = 3,
                 maximum_capital_pct: float = 40.0, maximum_risk_pct: float = 2.0,
                 minimum_opportunity_health: float = 75.0):
        self.maximum_open_trades = max(1, int(maximum_open_trades))
        self.maximum_same_direction = max(1, int(maximum_same_direction))
        self.maximum_capital_pct = max(1.0, min(100.0, float(maximum_capital_pct)))
        self.maximum_risk_pct = max(0.1, min(100.0, float(maximum_risk_pct)))
        self.minimum_opportunity_health = max(0.0, min(100.0, float(minimum_opportunity_health)))

    def admit(self, candidates: Iterable[PortfolioCandidate], *, initial_capital: float,
              current_open_trades: int = 0, current_deployed_capital: float = 0.0,
              current_risk: float = 0.0, current_ce: int = 0, current_pe: int = 0) -> tuple[PortfolioAdmission, ...]:
        capital = max(0.0, float(initial_capital))
        capital_limit = capital * self.maximum_capital_pct / 100.0
        risk_limit = capital * self.maximum_risk_pct / 100.0
        open_count = max(0, int(current_open_trades))
        direction_counts = {"CE": max(0, int(current_ce)), "PE": max(0, int(current_pe))}
        deployed = max(0.0, float(current_deployed_capital))
        risk_used = max(0.0, float(current_risk))
        result: list[PortfolioAdmission] = []
        for item in sorted(tuple(candidates), key=lambda x: x.priority, reverse=True):
            admitted, reason = True, "PORTFOLIO_APPROVED"
            if item.opportunity_health < self.minimum_opportunity_health:
                admitted, reason = False, f"OPPORTUNITY_HEALTH={item.opportunity_health:.2f}<MIN={self.minimum_opportunity_health:.2f}"
            elif open_count >= self.maximum_open_trades:
                admitted, reason = False, f"PORTFOLIO_MAX_OPEN={self.maximum_open_trades}"
            elif direction_counts.get(item.option_type, 0) >= self.maximum_same_direction:
                admitted, reason = False, f"PORTFOLIO_MAX_{item.option_type}={self.maximum_same_direction}"
            elif deployed + item.estimated_capital > capital_limit + 1e-9:
                admitted, reason = False, f"CAPITAL_BUDGET={deployed + item.estimated_capital:.2f}>MAX={capital_limit:.2f}"
            elif risk_used + item.estimated_risk > risk_limit + 1e-9:
                admitted, reason = False, f"RISK_BUDGET={risk_used + item.estimated_risk:.2f}>MAX={risk_limit:.2f}"
            if admitted:
                open_count += 1
                direction_counts[item.option_type] = direction_counts.get(item.option_type, 0) + 1
                deployed += item.estimated_capital
                risk_used += item.estimated_risk
            result.append(PortfolioAdmission(item.queue_id, admitted, "APPROVED" if admitted else "WAITING", reason, round(risk_used, 2), round(deployed, 2)))
        return tuple(result)
