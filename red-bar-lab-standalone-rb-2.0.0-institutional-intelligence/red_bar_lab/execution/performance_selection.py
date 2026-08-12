from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


def _num(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class HistoricalPerformance:
    sample_size: int
    wins: int
    losses: int
    win_rate_pct: float | None
    average_return_pct: float | None
    average_winner_pct: float | None
    average_loser_pct: float | None
    profit_factor: float | None
    expectancy_pct: float | None
    average_mfe_pct: float | None
    average_mae_pct: float | None
    evidence_ready: bool


@dataclass(frozen=True)
class TradeSelectionEvaluation:
    candidate_rank: int
    candidate_symbol: str
    candidate_score: float
    opportunity_score: float
    reward_remaining_pct: float
    reward_risk_ratio: float
    execution_quality_score: float
    historical_score: float
    selection_score: float
    historical: HistoricalPerformance
    eligible: bool
    decision: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["historical"] = asdict(self.historical)
        return row


class PerformanceTradeSelectionEngine:
    """Deterministic multi-candidate performance selection.

    Reward/Risk is retained as informational data only. Selection authority is
    based on Candidate quality, current Opportunity quality, Historical evidence
    and Execution quality. There is intentionally no maximum trade count here;
    Portfolio Risk remains authoritative later in the pipeline.
    """

    CANDIDATE_WEIGHT = 35.0 / 90.0
    OPPORTUNITY_WEIGHT = 20.0 / 90.0
    HISTORICAL_WEIGHT = 25.0 / 90.0
    EXECUTION_WEIGHT = 10.0 / 90.0

    def __init__(
        self,
        *,
        minimum_selection_score: float = 70.0,
        minimum_history_samples: int = 10,
        minimum_historical_win_rate_pct: float = 45.0,
        minimum_profit_factor: float = 1.10,
        minimum_expectancy_pct: float = 0.0,
    ):
        self.minimum_selection_score = float(minimum_selection_score)
        self.minimum_history_samples = int(minimum_history_samples)
        self.minimum_historical_win_rate_pct = float(
            minimum_historical_win_rate_pct
        )
        self.minimum_profit_factor = float(minimum_profit_factor)
        self.minimum_expectancy_pct = float(minimum_expectancy_pct)

    def historical_performance(
        self,
        orders: Iterable[dict[str, object]],
        *,
        option_type: str,
        entry_mode: str,
    ) -> HistoricalPerformance:
        returns: list[float] = []
        mfe: list[float] = []
        mae: list[float] = []
        option_type = str(option_type or "").upper()
        mode = str(entry_mode or "").upper()

        for row in orders:
            if str(row.get("status") or "").upper() != "CLOSED":
                continue
            if str(row.get("option_type") or "").upper() != option_type:
                continue
            row_mode = str(row.get("entry_mode") or "FRESH_SIGNAL").upper()
            if row_mode != mode:
                continue
            entry = _num(row.get("entry_price"))
            exit_price = _num(row.get("exit_price"))
            if entry <= 0 or exit_price <= 0:
                continue
            returns.append((exit_price - entry) / entry * 100.0)
            mfe_points = _num(row.get("mfe_points"))
            mae_points = _num(row.get("mae_points"))
            mfe.append(max(0.0, mfe_points / entry * 100.0))
            mae.append(max(0.0, abs(mae_points) / entry * 100.0))

        sample = len(returns)
        wins = [item for item in returns if item > 0]
        losses = [item for item in returns if item <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (
            gross_win / gross_loss
            if gross_loss > 0
            else (999.0 if gross_win > 0 else None)
        )
        return HistoricalPerformance(
            sample_size=sample,
            wins=len(wins),
            losses=len(losses),
            win_rate_pct=(round(len(wins) / sample * 100.0, 2) if sample else None),
            average_return_pct=(round(sum(returns) / sample, 3) if sample else None),
            average_winner_pct=(round(sum(wins) / len(wins), 3) if wins else None),
            average_loser_pct=(round(sum(losses) / len(losses), 3) if losses else None),
            profit_factor=(round(profit_factor, 3) if profit_factor is not None else None),
            expectancy_pct=(round(sum(returns) / sample, 3) if sample else None),
            average_mfe_pct=(round(sum(mfe) / len(mfe), 3) if mfe else None),
            average_mae_pct=(round(sum(mae) / len(mae), 3) if mae else None),
            evidence_ready=sample >= self.minimum_history_samples,
        )

    @staticmethod
    def _historical_score(history: HistoricalPerformance) -> float:
        if not history.evidence_ready:
            return 50.0
        win = min(100.0, max(0.0, _num(history.win_rate_pct)))
        pf = min(100.0, max(0.0, _num(history.profit_factor) / 2.5 * 100.0))
        exp = min(100.0, max(0.0, 50.0 + _num(history.expectancy_pct) * 2.0))
        return round(win * 0.45 + pf * 0.35 + exp * 0.20, 2)

    def evaluate(
        self,
        *,
        candidate,
        candidate_rank: int,
        opportunity,
        historical_orders: Iterable[dict[str, object]],
        entry_mode: str,
        minimum_candidate_score: float,
        stop_loss_pct: float,
        target_pct: float,
        require_opportunity_gate: bool,
    ) -> TradeSelectionEvaluation:
        history = self.historical_performance(
            historical_orders,
            option_type=candidate.contract.option_type,
            entry_mode=entry_mode,
        )
        historical_score = self._historical_score(history)

        # Retained only for backward-compatible reporting / historical comparison.
        rr = (
            float(target_pct) / float(stop_loss_pct)
            if float(stop_loss_pct) > 0 else 0.0
        )
        execution_quality = min(
            100.0,
            (
                min(1.0, _num(candidate.spread_score) / 15.0) * 45.0
                + min(1.0, _num(candidate.liquidity_score) / 20.0) * 55.0
            ),
        )
        opportunity_score = _num(opportunity.opportunity_score, 50.0)
        reward_remaining = _num(opportunity.reward_remaining_pct, 100.0)

        selection_score = round(
            min(100.0, _num(candidate.total_score)) * self.CANDIDATE_WEIGHT
            + min(100.0, opportunity_score) * self.OPPORTUNITY_WEIGHT
            + historical_score * self.HISTORICAL_WEIGHT
            + execution_quality * self.EXECUTION_WEIGHT,
            2,
        )

        hard_blockers: list[str] = []
        soft_evidence: list[str] = []

        if _num(candidate.spread_score) <= 0:
            hard_blockers.append("SPREAD")
        if _num(candidate.liquidity_score) <= 0:
            hard_blockers.append("LIQUIDITY")

        if _num(candidate.total_score) < float(minimum_candidate_score):
            soft_evidence.append(
                f"CANDIDATE_SCORE={_num(candidate.total_score):.2f}<MIN={float(minimum_candidate_score):.2f}"
            )
        if require_opportunity_gate and not bool(opportunity.eligible):
            soft_evidence.append(
                f"OPPORTUNITY_EXTENSION={str(getattr(opportunity, 'reason', 'NOT_ELIGIBLE'))}"
            )
        if selection_score < self.minimum_selection_score:
            soft_evidence.append(
                f"TSS={selection_score:.2f}<REFERENCE={self.minimum_selection_score:.2f}"
            )

        if history.evidence_ready:
            if _num(history.win_rate_pct) < self.minimum_historical_win_rate_pct:
                soft_evidence.append(
                    f"HISTORICAL_WIN_RATE={_num(history.win_rate_pct):.2f}<REFERENCE={self.minimum_historical_win_rate_pct:.2f}"
                )
            if history.profit_factor is None or _num(history.profit_factor) < self.minimum_profit_factor:
                soft_evidence.append(
                    f"PROFIT_FACTOR={_num(history.profit_factor):.3f}<REFERENCE={self.minimum_profit_factor:.3f}"
                )
            if history.expectancy_pct is None or _num(history.expectancy_pct) <= self.minimum_expectancy_pct:
                soft_evidence.append(
                    f"EXPECTANCY={_num(history.expectancy_pct):.3f}<=REFERENCE={self.minimum_expectancy_pct:.3f}"
                )

        eligible = not hard_blockers
        parts: list[str] = []
        if hard_blockers:
            parts.append("HARD_BLOCK:" + ",".join(hard_blockers))
        else:
            parts.append("NO_HARD_PERFORMANCE_BLOCKERS")
        if soft_evidence:
            parts.append("SOFT_EVIDENCE:" + "; ".join(soft_evidence))
        else:
            parts.append("SOFT_EVIDENCE:ALL_REFERENCE_LEVELS_MET")
        parts.append("REWARD_RISK_INFORMATIONAL_ONLY")

        return TradeSelectionEvaluation(
            candidate_rank=int(candidate_rank),
            candidate_symbol=candidate.contract.tradingsymbol,
            candidate_score=round(_num(candidate.total_score), 2),
            opportunity_score=round(opportunity_score, 2),
            reward_remaining_pct=round(reward_remaining, 2),
            reward_risk_ratio=round(rr, 3),
            execution_quality_score=round(execution_quality, 2),
            historical_score=historical_score,
            selection_score=selection_score,
            historical=history,
            eligible=eligible,
            decision=(f"BUY {candidate.contract.option_type}" if eligible else "SKIP"),
            reason=" | ".join(parts),
        )
