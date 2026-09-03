from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Iterable

from red_bar_lab.execution.execution_policy import RED_BAR_V2_STRATEGY_SOURCE


def _num(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class ModuleReliability:
    module: str
    sample_size: int
    supportive_samples: int
    supportive_wins: int
    win_rate_pct: float | None
    reliability_score: float
    adaptive_weight: float
    current_confidence: float
    current_recommendation: str
    current_support: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ExpertVote:
    expert: str
    score: float
    base_weight: float
    effective_weight: float
    contribution: float
    source: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InstitutionalExecutionEvaluation:
    execution_probability_pct: float
    expected_value_pct: float
    expectancy_pct: float
    expected_win_pct: float
    expected_loss_pct: float
    expectancy_source: str
    expectancy_confidence_pct: float
    kelly_fraction_pct: float
    expected_reward_pct: float
    expected_risk_pct: float
    intelligence_score: float
    adaptive_history_weight_pct: float
    rule_quality_score: float
    opportunity_score: float
    historical_score: float
    selection_score: float
    primary_decision: str
    primary_confidence_pct: float
    shadow_decision: str
    shadow_confidence_pct: float
    agreement: str
    shadow_adjustment_pct: float
    evidence_sample_size: int
    evidence_ready: bool
    modules: tuple[ModuleReliability, ...]
    expert_votes: tuple[ExpertVote, ...]
    eligible: bool
    decision: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["modules"] = [item.as_dict() for item in self.modules]
        return row


class InstitutionalExecutionCommittee:
    """Primary-only execution committee; payoff metrics are research evidence.

    Execution authority is held by the Primary Rule Engine plus deterministic
    safety/validity gates. Shadow Intelligence and payoff projections remain
    calculated, persisted and displayed, but contribute zero execution authority.
    """

    def __init__(
        self,
        *,
        minimum_execution_probability_pct: float = 70.0,
        minimum_expected_value_pct: float = 0.0,
        minimum_module_samples: int = 10,
        probability_prior_pct: float = 50.0,
        probability_prior_strength: int = 10,
    ) -> None:
        self.minimum_execution_probability_pct = float(
            minimum_execution_probability_pct
        )
        # Backward-compatible configuration only. Expected Value/Expectancy no
        # longer have execution authority.
        self.minimum_expected_value_pct = float(minimum_expected_value_pct)
        self.minimum_module_samples = int(minimum_module_samples)
        self.probability_prior_pct = float(probability_prior_pct)
        self.probability_prior_strength = max(1, int(probability_prior_strength))

    @staticmethod
    def _trade_return_pct(row: dict[str, object]) -> float | None:
        if str(row.get("status") or "").upper() != "CLOSED":
            return None
        entry = _num(row.get("entry_price"))
        exit_price = _num(row.get("exit_price"))
        if entry <= 0 or exit_price <= 0:
            return None
        return (exit_price - entry) / entry * 100.0

    @staticmethod
    def _parse_modules(row: dict[str, object]) -> list[dict[str, object]]:
        modules = row.get("modules")
        if isinstance(modules, list):
            return [item for item in modules if isinstance(item, dict)]
        raw = row.get("modules_json")
        if not raw:
            return []
        try:
            parsed = json.loads(str(raw))
            return [item for item in parsed if isinstance(item, dict)]
        except Exception:
            return []

    @staticmethod
    def _recommendation_supports_option(recommendation: str, option_type: str) -> bool:
        rec = str(recommendation or "").upper().strip()
        typ = str(option_type or "").upper().strip()
        return (typ == "CE" and rec == "BUY CE") or (typ == "PE" and rec == "BUY PE")

    def _module_reliability(
        self,
        *,
        option_type: str,
        current_shadow: dict[str, object] | None,
        historical_shadow: Iterable[dict[str, object]],
        historical_orders: Iterable[dict[str, object]],
        allow_candidate_specific_modules: bool,
    ) -> tuple[ModuleReliability, ...]:
        current_modules = {
            str(item.get("module") or "UNKNOWN"): item
            for item in self._parse_modules(current_shadow or {})
            if allow_candidate_specific_modules
            or str(item.get("module") or "") != "Greeks"
        }
        orders_by_signal: dict[str, list[dict[str, object]]] = {}
        for order in historical_orders:
            if str(order.get("option_type") or "").upper() != str(option_type).upper():
                continue
            if self._trade_return_pct(order) is None:
                continue
            signal_id = str(order.get("signal_id") or "")
            if signal_id:
                orders_by_signal.setdefault(signal_id, []).append(order)

        stats: dict[str, dict[str, int]] = {}
        seen_signal_module: set[tuple[str, str]] = set()
        for shadow in historical_shadow:
            signal_id = str(shadow.get("signal_id") or "")
            if not signal_id or signal_id not in orders_by_signal:
                continue
            for module in self._parse_modules(shadow):
                name = str(module.get("module") or "UNKNOWN")
                if not allow_candidate_specific_modules and name == "Greeks":
                    continue
                dedupe_key = (signal_id, name)
                if dedupe_key in seen_signal_module:
                    continue
                seen_signal_module.add(dedupe_key)
                rec = str(module.get("recommendation") or "WAIT")
                supportive = self._recommendation_supports_option(rec, option_type)
                bucket = stats.setdefault(
                    name,
                    {"samples": 0, "supportive": 0, "wins": 0},
                )
                bucket["samples"] += 1
                if supportive:
                    bucket["supportive"] += 1
                    if any(
                        (self._trade_return_pct(order) or 0.0) > 0
                        for order in orders_by_signal[signal_id]
                    ):
                        bucket["wins"] += 1

        names = sorted(set(current_modules) | set(stats))
        if not names:
            return ()

        raw_weights: dict[str, float] = {}
        reliability_rows: dict[str, tuple[int, int, int, float | None, float]] = {}
        for name in names:
            bucket = stats.get(name, {"samples": 0, "supportive": 0, "wins": 0})
            supportive = int(bucket["supportive"])
            wins = int(bucket["wins"])
            wr = (wins / supportive * 100.0) if supportive else None
            posterior = (
                (wins + self.probability_prior_strength * 0.5)
                / (supportive + self.probability_prior_strength)
                * 100.0
            )
            sample_confidence = min(1.0, supportive / max(1, self.minimum_module_samples))
            reliability = 50.0 + (posterior - 50.0) * sample_confidence
            current_conf = _clamp(_num(current_modules.get(name, {}).get("confidence"), 0.0))
            raw_weight = max(0.05, reliability / 100.0) if current_conf > 0 else 0.0
            raw_weights[name] = raw_weight
            reliability_rows[name] = (
                int(bucket["samples"]), supportive, wins,
                (round(wr, 2) if wr is not None else None), round(reliability, 2),
            )

        total_raw = sum(raw_weights.values()) or 1.0
        result: list[ModuleReliability] = []
        for name in names:
            current = current_modules.get(name, {})
            samples, supportive, wins, wr, reliability = reliability_rows[name]
            recommendation = str(current.get("recommendation") or "WAIT")
            if self._recommendation_supports_option(recommendation, option_type):
                support = "SUPPORT"
            elif recommendation.upper() in {"BUY CE", "BUY PE"}:
                support = "OPPOSE"
            else:
                support = "NEUTRAL"
            result.append(ModuleReliability(
                module=name,
                sample_size=samples,
                supportive_samples=supportive,
                supportive_wins=wins,
                win_rate_pct=wr,
                reliability_score=reliability,
                adaptive_weight=round(raw_weights[name] / total_raw * 100.0, 2),
                current_confidence=round(_clamp(_num(current.get("confidence"), 0.0)), 2),
                current_recommendation=recommendation,
                current_support=support,
            ))
        return tuple(result)

    @staticmethod
    def _intelligence_score(modules: tuple[ModuleReliability, ...]) -> float:
        active = [item for item in modules if item.current_confidence > 0]
        if not active:
            return 50.0
        score = 0.0
        for item in active:
            vote = 50.0
            if item.current_support == "SUPPORT":
                vote = item.current_confidence
            elif item.current_support == "OPPOSE":
                vote = 100.0 - item.current_confidence
            score += vote * item.adaptive_weight / 100.0
        active_weight = sum(item.adaptive_weight for item in active)
        if active_weight <= 0:
            return 50.0
        return round(_clamp(score / active_weight * 100.0), 2)

    def evaluate(
        self,
        *,
        candidate,
        selection,
        opportunity,
        historical_orders: Iterable[dict[str, object]],
        current_shadow: dict[str, object] | None,
        historical_shadow: Iterable[dict[str, object]],
        stop_loss_pct: float,
        target_pct: float,
        strategy_source: str = "",
    ) -> InstitutionalExecutionEvaluation:
        history = selection.historical
        modules = self._module_reliability(
            option_type=candidate.contract.option_type,
            current_shadow=current_shadow,
            historical_shadow=historical_shadow,
            historical_orders=historical_orders,
            allow_candidate_specific_modules=(
                int(getattr(selection, "candidate_rank", 1) or 1) == 1
            ),
        )
        intelligence_score = self._intelligence_score(modules)

        rule_quality = _clamp(_num(candidate.total_score))
        opportunity_score = _clamp(_num(opportunity.opportunity_score, 50.0))
        historical_score = _clamp(_num(selection.historical_score, 50.0))
        selection_score = _clamp(_num(selection.selection_score, 50.0))
        n = int(history.sample_size or 0)

        primary_decision = f"BUY {candidate.contract.option_type}"
        primary_confidence = round(rule_quality, 2)

        raw_shadow_decision = str(
            (current_shadow or {}).get("shadow_decision") or "WAIT"
        ).upper().strip()
        shadow_confidence = _clamp(
            _num((current_shadow or {}).get("shadow_confidence"), intelligence_score)
        )
        if raw_shadow_decision not in {"BUY CE", "BUY PE", "WAIT"}:
            raw_shadow_decision = "WAIT"

        if raw_shadow_decision == primary_decision:
            agreement = "AGREE"
        elif raw_shadow_decision == "WAIT":
            agreement = "NEUTRAL"
        else:
            agreement = "CONFLICT"

        shadow_adjustment = 0.0
        probability = round(_clamp(primary_confidence, 5.0, 95.0), 2)
        intelligence_score = self._intelligence_score(modules)
        history_weight = 0.05 if n == 0 else min(0.20, 0.05 + n / 50.0 * 0.15)

        expert_votes = (
            ExpertVote(
                expert="Primary Rule Engine",
                score=primary_confidence,
                base_weight=100.0,
                effective_weight=100.0,
                contribution=primary_confidence,
                source="PRIMARY",
                detail=f"{primary_decision}; authoritative execution confidence",
            ),
            ExpertVote(
                expert="Shadow Intelligence",
                score=round(shadow_confidence, 2),
                base_weight=0.0,
                effective_weight=0.0,
                contribution=0.0,
                source="SHADOW_INFORMATIONAL",
                detail=(
                    f"{raw_shadow_decision}; agreement={agreement}; "
                    "INFORMATIONAL ONLY; execution impact=NONE"
                ),
            ),
            ExpertVote(
                expert="Final Committee Confidence",
                score=probability,
                base_weight=0.0,
                effective_weight=0.0,
                contribution=probability,
                source="COMMITTEE",
                detail=f"Primary-only confidence {primary_confidence:.2f}; Shadow impact 0.00",
            ),
        )

        configured_target = max(0.0, float(target_pct))
        configured_stop = max(0.0, float(stop_loss_pct))
        adjusted_probability = probability

        hist_win = _num(getattr(history, "average_winner_pct", None), configured_target)
        hist_loss = abs(_num(getattr(history, "average_loser_pct", None), configured_stop))
        if hist_win <= 0:
            hist_win = configured_target
        if hist_loss <= 0:
            hist_loss = configured_stop

        payoff_history_weight = min(0.60, n / 50.0 * 0.60)
        expected_win = (
            configured_target * (1.0 - payoff_history_weight)
            + hist_win * payoff_history_weight
        )
        expected_loss = (
            configured_stop * (1.0 - payoff_history_weight)
            + hist_loss * payoff_history_weight
        )
        p = adjusted_probability / 100.0
        expectancy = round(
            p * expected_win - (1.0 - p) * expected_loss,
            3,
        )

        payoff_ratio = expected_win / expected_loss if expected_loss > 0 else 0.0
        kelly = ((payoff_ratio * p - (1.0 - p)) / payoff_ratio) if payoff_ratio > 0 else 0.0
        half_kelly_pct = round(max(0.0, min(0.25, kelly * 0.5)) * 100.0, 2)
        expectancy_confidence = round(min(100.0, 20.0 + min(1.0, n / 50.0) * 80.0), 2)
        expectancy_source = "HISTORICAL_BLEND" if n > 0 else "CONFIGURED_PAYOFF_PRIOR"

        # Change 3: Expected Value is neutral in execution ordering/portfolio.
        # Actual calculated expectancy is retained in expectancy_pct for research.
        expected_value = 0.0
        probability = adjusted_probability

        blockers: list[str] = []
        shadow_blockers: list[str] = []
        # Red Bar V2's entry authority is its own rule table -- a completed close
        # against the governing midpoint, futures VWAP alignment, one position at
        # a time, the 15:00 cutoff, a priceable stop inside the risk band, and a
        # tradable contract. Composite scores built from eight sub-scores are not
        # on that table, so for V2 rows they are recorded as evidence and scored
        # later rather than silently deciding the trade. Every other source keeps
        # the committee exactly as it was.
        v2_primary = (
            str(strategy_source or "").upper() == RED_BAR_V2_STRATEGY_SOURCE
        )
        if not bool(selection.eligible):
            blockers.append(f"PERFORMANCE_HARD_BLOCK[{selection.reason}]")

        # Reward consumption is no longer terminal. EMA10 continuation is owned by
        # the trend-aware Opportunity Engine. Structural/opposite-signal failures
        # remain authoritative.
        #
        # Match whole `|`-separated tokens, never substrings. The upstream engine
        # says "this no longer vetoes an entry" by appending a suffix -- e.g.
        # BEARISH_EMA10_LOST_INFORMATIONAL_ONLY, emitted with eligible=True -- and
        # a substring test reads the disclaimer as the blocker it disclaims. That
        # inversion blocked 23 already-eligible PE entries on 2026-09-03 alone.
        # A shadow line (SHADOW_ENTRY_WARNINGS=A,B) is likewise one token that
        # matches no code, which is what keeps demoted gates demoted here.
        opportunity_reason = str(getattr(opportunity, "reason", "") or "").upper()
        opportunity_tokens = {
            token.strip()
            for token in opportunity_reason.split("|")
            if token.strip()
        }
        terminal_opportunity = [
            code for code in ("OPPOSITE_RED_BAR", "STRUCTURE_INVALID", "BEARISH_EMA10_LOST", "BULLISH_EMA10_LOST", "EMA10_DATA_UNAVAILABLE")
            if code in opportunity_tokens
        ]
        if terminal_opportunity:
            (shadow_blockers if v2_primary else blockers).append(
                "OPPORTUNITY_TERMINAL[" + ",".join(terminal_opportunity) + "]"
            )
        if probability < self.minimum_execution_probability_pct:
            (shadow_blockers if v2_primary else blockers).append(
                f"EXECUTION_PROBABILITY={probability:.2f}<MIN={self.minimum_execution_probability_pct:.2f}"
            )

        eligible = not blockers
        shadow_line = (
            "SHADOW_ENTRY_WARNINGS="
            + ",".join(dict.fromkeys(shadow_blockers))
            if shadow_blockers
            else ""
        )
        committee_reason = (
            f"EXECUTION_COMMITTEE_APPROVED | {selection.reason} | PAYOFF_METRICS_INFORMATIONAL_ONLY"
            if eligible
            else " | ".join(blockers)
            + f" | PERFORMANCE_DETAIL[{selection.reason}] | PAYOFF_METRICS_INFORMATIONAL_ONLY"
        )
        if shadow_line:
            committee_reason = f"{committee_reason} | {shadow_line}"
        return InstitutionalExecutionEvaluation(
            execution_probability_pct=probability,
            expected_value_pct=expected_value,
            expectancy_pct=expectancy,
            expected_win_pct=round(expected_win, 3),
            expected_loss_pct=round(expected_loss, 3),
            expectancy_source=expectancy_source,
            expectancy_confidence_pct=expectancy_confidence,
            kelly_fraction_pct=half_kelly_pct,
            expected_reward_pct=round(expected_win, 3),
            expected_risk_pct=round(expected_loss, 3),
            intelligence_score=intelligence_score,
            adaptive_history_weight_pct=round(history_weight * 100.0, 2),
            rule_quality_score=round(rule_quality, 2),
            opportunity_score=round(opportunity_score, 2),
            historical_score=round(historical_score, 2),
            selection_score=round(selection_score, 2),
            primary_decision=primary_decision,
            primary_confidence_pct=round(primary_confidence, 2),
            shadow_decision=raw_shadow_decision,
            shadow_confidence_pct=round(shadow_confidence, 2),
            agreement=agreement,
            shadow_adjustment_pct=round(shadow_adjustment, 2),
            evidence_sample_size=n,
            evidence_ready=bool(history.evidence_ready),
            modules=modules,
            expert_votes=expert_votes,
            eligible=eligible,
            decision=(f"BUY {candidate.contract.option_type}" if eligible else "WAIT"),
            reason=committee_reason,
        )
