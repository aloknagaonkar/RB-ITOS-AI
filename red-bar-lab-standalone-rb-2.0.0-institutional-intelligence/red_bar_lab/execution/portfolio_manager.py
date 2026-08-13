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
        return (
            float(self.opportunity_health),
            float(self.expectancy_pct),
            float(self.candidate_score),
            -float(self.rank),
        )


@dataclass(frozen=True)
class PortfolioAdmission:
    queue_id: str
    admitted: bool
    status: str
    reason: str
    risk_used: float
    capital_used: float


class PortfolioRiskManager:
    """Compatibility pass-through after removal of portfolio trade blocking.

    The Institutional Execution Committee is the final business approval gate.
    Candidates reaching this component have already been approved and must proceed
    to execution. The legacy constructor and ``admit`` signature are retained so
    existing automation, configuration and UI code continue to work while the
    former portfolio limits no longer create WAITING decisions.
    """

    def __init__(
        self,
        *,
        maximum_open_trades: int = 5,
        maximum_same_direction: int = 3,
        maximum_capital_pct: float = 40.0,
        maximum_risk_pct: float = 2.0,
        minimum_opportunity_health: float = 75.0,
    ):
        # Retain legacy values for compatibility and diagnostics only.
        self.maximum_open_trades = max(1, int(maximum_open_trades))
        self.maximum_same_direction = max(1, int(maximum_same_direction))
        self.maximum_capital_pct = max(
            1.0, min(100.0, float(maximum_capital_pct))
        )
        self.maximum_risk_pct = max(
            0.1, min(100.0, float(maximum_risk_pct))
        )
        self.minimum_opportunity_health = max(
            0.0, min(100.0, float(minimum_opportunity_health))
        )

    def admit(
        self,
        candidates: Iterable[PortfolioCandidate],
        *,
        initial_capital: float,
        current_open_trades: int = 0,
        current_deployed_capital: float = 0.0,
        current_risk: float = 0.0,
        current_ce: int = 0,
        current_pe: int = 0,
    ) -> tuple[PortfolioAdmission, ...]:
        del initial_capital, current_open_trades, current_ce, current_pe

        deployed = max(0.0, float(current_deployed_capital))
        risk_used = max(0.0, float(current_risk))
        result: list[PortfolioAdmission] = []

        # Preserve deterministic candidate ordering, but never block a candidate
        # that has already been approved by the execution committee.
        for item in sorted(
            tuple(candidates), key=lambda candidate: candidate.priority, reverse=True
        ):
            deployed += item.estimated_capital
            risk_used += item.estimated_risk
            result.append(
                PortfolioAdmission(
                    queue_id=item.queue_id,
                    admitted=True,
                    status="APPROVED",
                    reason="COMMITTEE_APPROVED_PORTFOLIO_BYPASSED",
                    risk_used=round(risk_used, 2),
                    capital_used=round(deployed, 2),
                )
            )

        return tuple(result)
