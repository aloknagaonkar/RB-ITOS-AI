"""Baseline-adjusted cross-feature ranking for historical PCR evidence.

This module is deliberately observational. It evaluates a small, pre-declared set
of PCR/OI/ATM conditions against later NIFTY point changes, compares each
condition with a matched unconditional baseline, and reports cross-session
coverage/consistency. It does not emit BUY/SELL decisions.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from .historical_analysis import FORWARD_FIELDS, _forward_stats, _quantile, load_evidence_csv

PRIMARY_FORWARD = "forward_change_15m"
MIN_SESSIONS_FOR_RANKING = 8
MIN_ROWS_FOR_RANKING = 100


class HistoricalRankingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BaselineOutcome(HistoricalRankingModel):
    count: int
    session_count: int
    mean: float | None = None
    positive_pct: float | None = None
    negative_pct: float | None = None
    positive_session_pct: float | None = None
    negative_session_pct: float | None = None


class AdjustedOutcome(HistoricalRankingModel):
    count: int
    session_count: int
    mean: float | None = None
    median: float | None = None
    mean_absolute: float | None = None
    stdev: float | None = None
    positive_pct: float | None = None
    negative_pct: float | None = None
    positive_session_pct: float | None = None
    negative_session_pct: float | None = None
    baseline_mean: float | None = None
    adjusted_mean: float | None = None
    observed_direction: str = "FLAT"
    directional_hit_pct: float | None = None
    baseline_directional_hit_pct: float | None = None
    hit_rate_lift_pct_points: float | None = None
    directional_session_pct: float | None = None


class RankedCondition(HistoricalRankingModel):
    rank: int | None = None
    condition_id: str
    description: str
    required_features: list[str]
    row_count: int
    session_count: int
    coverage_pct: float
    eligible_for_ranking: bool
    ranking_score: float | None = None
    primary_forward: str = PRIMARY_FORWARD
    forwards: dict[str, AdjustedOutcome]


class HistoricalRankingReport(HistoricalRankingModel):
    status: str
    source: str
    row_count: int
    session_count: int
    primary_forward: str
    minimum_sessions_for_ranking: int
    minimum_rows_for_ranking: int
    methodology: list[str] = Field(default_factory=list)
    thresholds: dict[str, dict[str, float]]
    baselines: dict[str, BaselineOutcome]
    ranked_conditions: list[RankedCondition]


@dataclass(frozen=True)
class Candidate:
    condition_id: str
    description: str
    required_features: tuple[str, ...]
    predicate: Callable[[dict[str, object], dict[str, dict[str, float]]], bool]


def _numeric(row: dict[str, object], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _tail_thresholds(rows: list[dict[str, object]], features: set[str]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for feature in sorted(features):
        values = [_numeric(row, feature) for row in rows]
        numeric = [value for value in values if value is not None]
        if not numeric:
            continue
        result[feature] = {
            "q20": _quantile(numeric, 0.2),
            "q40": _quantile(numeric, 0.4),
            "q60": _quantile(numeric, 0.6),
            "q80": _quantile(numeric, 0.8),
        }
    return result


def _le(row, thresholds, feature, quantile):
    value = _numeric(row, feature)
    return value is not None and feature in thresholds and value <= thresholds[feature][quantile]


def _ge(row, thresholds, feature, quantile):
    value = _numeric(row, feature)
    return value is not None and feature in thresholds and value >= thresholds[feature][quantile]


def _lt_zero(row, feature):
    value = _numeric(row, feature)
    return value is not None and value < 0


def _gt_zero(row, feature):
    value = _numeric(row, feature)
    return value is not None and value > 0


def _candidates() -> list[Candidate]:
    m = "moving_pcr_change_15m"
    f = "fixed_pcr_change_15m"
    full = "full_pcr_change_15m"
    moi = "moving_oi_imbalance_pct"
    foi = "fixed_oi_imbalance_pct"
    spread = "fixed_moving_pcr_spread"
    atm = "atm_divergence_points"
    return [
        Candidate("MOVING_PCR_STRONG_FALL", "Moving PCR 15m change in bottom 20%", (m,), lambda r,t: _le(r,t,m,"q20")),
        Candidate("MOVING_PCR_STRONG_RISE", "Moving PCR 15m change in top 20%", (m,), lambda r,t: _ge(r,t,m,"q80")),
        Candidate("PCR_ALL_FALL", "Fixed, Moving and Full 15m PCR changes are all negative", (f,m,full), lambda r,t: _lt_zero(r,f) and _lt_zero(r,m) and _lt_zero(r,full)),
        Candidate("PCR_ALL_RISE", "Fixed, Moving and Full 15m PCR changes are all positive", (f,m,full), lambda r,t: _gt_zero(r,f) and _gt_zero(r,m) and _gt_zero(r,full)),
        Candidate("PCR_FIXED_MOVING_STRONG_FALL", "Fixed and Moving PCR 15m changes both in bottom 20%", (f,m), lambda r,t: _le(r,t,f,"q20") and _le(r,t,m,"q20")),
        Candidate("PCR_FIXED_MOVING_STRONG_RISE", "Fixed and Moving PCR 15m changes both in top 20%", (f,m), lambda r,t: _ge(r,t,f,"q80") and _ge(r,t,m,"q80")),
        Candidate("MOVING_FALL_CALL_OI_PRESSURE", "Moving PCR strong-falling with Moving Put-minus-Call OI imbalance in bottom 20%", (m,moi), lambda r,t: _le(r,t,m,"q20") and _le(r,t,moi,"q20")),
        Candidate("MOVING_FALL_PUT_OI_PRESSURE", "Moving PCR strong-falling with Moving Put-minus-Call OI imbalance in top 20%", (m,moi), lambda r,t: _le(r,t,m,"q20") and _ge(r,t,moi,"q80")),
        Candidate("MOVING_RISE_PUT_OI_PRESSURE", "Moving PCR strong-rising with Moving Put-minus-Call OI imbalance in top 20%", (m,moi), lambda r,t: _ge(r,t,m,"q80") and _ge(r,t,moi,"q80")),
        Candidate("MOVING_RISE_CALL_OI_PRESSURE", "Moving PCR strong-rising with Moving Put-minus-Call OI imbalance in bottom 20%", (m,moi), lambda r,t: _ge(r,t,m,"q80") and _le(r,t,moi,"q20")),
        Candidate("FIXED_FALL_CALL_OI_PRESSURE", "Fixed PCR strong-falling with Fixed Put-minus-Call OI imbalance in bottom 20%", (f,foi), lambda r,t: _le(r,t,f,"q20") and _le(r,t,foi,"q20")),
        Candidate("FIXED_RISE_PUT_OI_PRESSURE", "Fixed PCR strong-rising with Fixed Put-minus-Call OI imbalance in top 20%", (f,foi), lambda r,t: _ge(r,t,f,"q80") and _ge(r,t,foi,"q80")),
        Candidate("PCR_SPREAD_LOW", "Moving-minus-Fixed PCR spread in bottom 20%", (spread,), lambda r,t: _le(r,t,spread,"q20")),
        Candidate("PCR_SPREAD_HIGH", "Moving-minus-Fixed PCR spread in top 20%", (spread,), lambda r,t: _ge(r,t,spread,"q80")),
        Candidate("ATM_BELOW_FIXED_PCR_FALL", "Moving ATM below Fixed ATM while Moving PCR 15m is negative", (atm,m), lambda r,t: (_numeric(r,atm) or 0) < 0 and _lt_zero(r,m)),
        Candidate("ATM_ABOVE_FIXED_PCR_RISE", "Moving ATM above Fixed ATM while Moving PCR 15m is positive", (atm,m), lambda r,t: (_numeric(r,atm) or 0) > 0 and _gt_zero(r,m)),
        Candidate("PCR_FALL_SPREAD_LOW", "Moving PCR strong-falling and Moving-minus-Fixed PCR spread in bottom 20%", (m,spread), lambda r,t: _le(r,t,m,"q20") and _le(r,t,spread,"q20")),
        Candidate("PCR_RISE_SPREAD_HIGH", "Moving PCR strong-rising and Moving-minus-Fixed PCR spread in top 20%", (m,spread), lambda r,t: _ge(r,t,m,"q80") and _ge(r,t,spread,"q80")),
    ]


def _required_available(row: dict[str, object], features: tuple[str, ...]) -> bool:
    return all(_numeric(row, feature) is not None for feature in features)


def _baseline(rows: list[dict[str, object]], forward: str) -> BaselineOutcome:
    stats = _forward_stats(rows, forward)
    return BaselineOutcome(
        count=stats.count,
        session_count=stats.session_count,
        mean=stats.mean,
        positive_pct=stats.positive_pct,
        negative_pct=stats.negative_pct,
        positive_session_pct=stats.positive_session_pct,
        negative_session_pct=stats.negative_session_pct,
    )


def _adjusted(condition_rows, eligible_rows, forward: str) -> AdjustedOutcome:
    stats = _forward_stats(condition_rows, forward)
    base = _forward_stats(eligible_rows, forward)
    if stats.mean is None or base.mean is None:
        direction = "FLAT"
        adjusted_mean = None
    else:
        adjusted_mean = stats.mean - base.mean
        direction = "BULLISH" if adjusted_mean > 0 else "BEARISH" if adjusted_mean < 0 else "FLAT"

    if direction == "BULLISH":
        hit = stats.positive_pct
        base_hit = base.positive_pct
        session_pct = stats.positive_session_pct
    elif direction == "BEARISH":
        hit = stats.negative_pct
        base_hit = base.negative_pct
        session_pct = stats.negative_session_pct
    else:
        hit = base_hit = session_pct = None

    lift = hit - base_hit if hit is not None and base_hit is not None else None
    return AdjustedOutcome(
        count=stats.count,
        session_count=stats.session_count,
        mean=stats.mean,
        median=stats.median,
        mean_absolute=stats.mean_absolute,
        stdev=stats.stdev,
        positive_pct=stats.positive_pct,
        negative_pct=stats.negative_pct,
        positive_session_pct=stats.positive_session_pct,
        negative_session_pct=stats.negative_session_pct,
        baseline_mean=base.mean,
        adjusted_mean=adjusted_mean,
        observed_direction=direction,
        directional_hit_pct=hit,
        baseline_directional_hit_pct=base_hit,
        hit_rate_lift_pct_points=lift,
        directional_session_pct=session_pct,
    )


def _score(outcome: AdjustedOutcome, session_count: int, total_sessions: int) -> float | None:
    """Transparent heuristic for prioritising hypotheses, not statistical significance."""
    if (
        outcome.adjusted_mean is None
        or outcome.hit_rate_lift_pct_points is None
        or outcome.directional_session_pct is None
        or total_sessions <= 0
    ):
        return None
    coverage = session_count / total_sessions
    session_consistency = max(0.0, (outcome.directional_session_pct - 50.0) / 50.0)
    hit_lift = max(0.0, outcome.hit_rate_lift_pct_points / 100.0)
    return abs(outcome.adjusted_mean) * coverage * (1.0 + session_consistency + hit_lift)


def build_historical_ranking_report(rows: list[dict[str, object]], source: str) -> HistoricalRankingReport:
    sessions = sorted({str(row["session_date"]) for row in rows if row.get("session_date")})
    candidates = _candidates()
    all_features = {feature for candidate in candidates for feature in candidate.required_features}
    thresholds = _tail_thresholds(rows, all_features)
    baselines = {forward: _baseline(rows, forward) for forward in FORWARD_FIELDS}

    results: list[RankedCondition] = []
    for candidate in candidates:
        eligible_rows = [row for row in rows if _required_available(row, candidate.required_features)]
        condition_rows = [row for row in eligible_rows if candidate.predicate(row, thresholds)]
        condition_sessions = {str(row["session_date"]) for row in condition_rows if row.get("session_date")}
        eligible = len(condition_rows) >= MIN_ROWS_FOR_RANKING and len(condition_sessions) >= MIN_SESSIONS_FOR_RANKING
        forwards = {field: _adjusted(condition_rows, eligible_rows, field) for field in FORWARD_FIELDS}
        score = _score(forwards[PRIMARY_FORWARD], len(condition_sessions), len(sessions)) if eligible else None
        results.append(RankedCondition(
            condition_id=candidate.condition_id,
            description=candidate.description,
            required_features=list(candidate.required_features),
            row_count=len(condition_rows),
            session_count=len(condition_sessions),
            coverage_pct=(len(condition_rows) * 100.0 / len(eligible_rows)) if eligible_rows else 0.0,
            eligible_for_ranking=eligible,
            ranking_score=score,
            forwards=forwards,
        ))

    ranked = sorted(
        results,
        key=lambda item: (item.ranking_score is not None, item.ranking_score or -1.0),
        reverse=True,
    )
    rank = 0
    finalized: list[RankedCondition] = []
    for item in ranked:
        if item.ranking_score is not None:
            rank += 1
            finalized.append(item.model_copy(update={"rank": rank}))
        else:
            finalized.append(item)

    return HistoricalRankingReport(
        status="AVAILABLE" if rows else "UNAVAILABLE",
        source=source,
        row_count=len(rows),
        session_count=len(sessions),
        primary_forward=PRIMARY_FORWARD,
        minimum_sessions_for_ranking=MIN_SESSIONS_FOR_RANKING,
        minimum_rows_for_ranking=MIN_ROWS_FOR_RANKING,
        methodology=[
            "Observational hypothesis ranking only; no BUY/SELL classification.",
            "Candidate conditions are pre-declared PCR/OI/ATM combinations rather than exhaustively data-mined expressions.",
            "Tail conditions use dataset-derived 20th/80th percentile thresholds.",
            "Each condition is compared with a matched baseline containing rows where that condition's required features are available.",
            "Primary ranking uses the 15-minute forward move, adjusted mean effect, directional hit-rate lift, session coverage, and session consistency.",
            "Ranking score is a transparent prioritisation heuristic, not a p-value or proof of predictive significance.",
            "Minute rows are autocorrelated; session count and session-direction consistency must be considered before promoting a hypothesis.",
        ],
        thresholds=thresholds,
        baselines=baselines,
        ranked_conditions=finalized,
    )


def rank_historical_evidence_csv(path: str | Path) -> HistoricalRankingReport:
    return build_historical_ranking_report(load_evidence_csv(path), str(path))


def write_historical_ranking_json(report: HistoricalRankingReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
