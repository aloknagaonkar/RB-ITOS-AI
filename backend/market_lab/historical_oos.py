"""Frozen-threshold out-of-sample validation for the H3 PCR spread hypothesis.

H3 is a bearish/non-expiry research hypothesis: Moving-minus-Fixed PCR spread
in the bottom 20% of the training distribution.  The threshold is frozen from
training data and must not be recomputed on the out-of-sample dataset.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .historical_hypothesis_backtest import (
    HOLD_MINUTES,
    PRIMARY_HOLD_MINUTES,
    RECONSTRUCTION_PROVENANCE,
    EventResult,
    HoldOutcome,
    SegmentOutcome,
    Hypothesis,
    _build_events,
    _hold_summary,
    _max_consecutive_losses,
    _quantile,
    _segment,
    load_hypothesis_evidence_csv,
)

SPEC_VERSION = "H3-NX-v1"
H3_FEATURE = "fixed_moving_pcr_spread"


class OOSModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FrozenH3Spec(OOSModel):
    spec_version: str = SPEC_VERSION
    hypothesis_id: str = "H3_NX_PCR_SPREAD_LOW"
    description: str = "Moving-minus-Fixed PCR spread in training bottom 20%; non-expiry days only"
    direction: str = "BEARISH"
    regime: str = "NON_EXPIRY_DAY"
    feature: str = H3_FEATURE
    comparison: str = "LE"
    threshold_quantile: float = 0.20
    frozen_threshold: float
    cooldown_minutes: int = 15
    primary_hold_minutes: int = PRIMARY_HOLD_MINUTES
    training_source: str
    training_row_count: int
    training_session_count: int
    provenance: str = RECONSTRUCTION_PROVENANCE
    methodology: list[str] = Field(default_factory=list)


class AcceptanceCheck(OOSModel):
    name: str
    passed: bool
    actual: float | int | None
    rule: str


class OOSValidationReport(OOSModel):
    status: str
    source: str
    spec_version: str
    hypothesis_id: str
    frozen_threshold: float
    cooldown_minutes: int
    row_count: int
    session_count: int
    eligible_non_expiry_row_count: int
    excluded_expiry_row_count: int
    event_count: int
    event_session_count: int
    skipped_due_to_cooldown: int
    max_horizon_overlap_count: int
    max_consecutive_losses_15m: int
    holds: dict[str, HoldOutcome]
    per_session: list[SegmentOutcome]
    time_of_day: list[SegmentOutcome]
    acceptance_checks: list[AcceptanceCheck]
    acceptance_status: str
    events: list[EventResult]
    methodology: list[str] = Field(default_factory=list)


def freeze_h3_spec(
    training_rows: list[dict[str, object]],
    source: str,
    cooldown_minutes: int = 15,
) -> FrozenH3Spec:
    if cooldown_minutes < 1:
        raise ValueError("cooldown_minutes must be >= 1")
    values = [
        float(row[H3_FEATURE])
        for row in training_rows
        if isinstance(row.get(H3_FEATURE), float)
    ]
    if not values:
        raise ValueError(f"no numeric values available for {H3_FEATURE}")
    sessions = {str(row.get("session_date")) for row in training_rows if row.get("session_date")}
    return FrozenH3Spec(
        frozen_threshold=_quantile(values, 0.20),
        cooldown_minutes=cooldown_minutes,
        training_source=source,
        training_row_count=len(training_rows),
        training_session_count=len(sessions),
        methodology=[
            "Threshold frozen once from the training dataset 20th percentile; OOS data must not alter it.",
            "H3-NX is evaluated only on non-expiry sessions.",
            "Direction is bearish/PE-direction NIFTY spot study; no option premium or execution assumptions.",
        ],
    )


def freeze_h3_spec_csv(path: str | Path, cooldown_minutes: int = 15) -> FrozenH3Spec:
    rows = load_hypothesis_evidence_csv(path)
    return freeze_h3_spec(rows, str(path), cooldown_minutes)


def write_h3_spec_json(spec: FrozenH3Spec, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def load_h3_spec_json(path: str | Path) -> FrozenH3Spec:
    return FrozenH3Spec.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _h3_hypothesis(spec: FrozenH3Spec) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=spec.hypothesis_id,
        description=spec.description,
        required_features=(H3_FEATURE,),
        predicate=lambda row, thresholds: float(row[H3_FEATURE]) <= thresholds["frozen_h3_spread_threshold"],
    )


def _acceptance(hold: HoldOutcome, event_sessions: int) -> tuple[list[AcceptanceCheck], str]:
    checks = [
        AcceptanceCheck(
            name="win_rate_15m",
            passed=hold.win_rate_pct is not None and hold.win_rate_pct >= 53.0,
            actual=hold.win_rate_pct,
            rule=">= 53%",
        ),
        AcceptanceCheck(
            name="median_directional_points_15m",
            passed=hold.median_directional_points is not None and hold.median_directional_points > 0.0,
            actual=hold.median_directional_points,
            rule="> 0",
        ),
        AcceptanceCheck(
            name="mean_directional_points_15m",
            passed=hold.mean_directional_points is not None and hold.mean_directional_points > 0.0,
            actual=hold.mean_directional_points,
            rule="> 0",
        ),
        AcceptanceCheck(
            name="event_session_coverage",
            passed=event_sessions >= 8,
            actual=event_sessions,
            rule=">= 8 sessions",
        ),
        AcceptanceCheck(
            name="mfe_vs_mae_15m",
            passed=(
                hold.mean_mfe_points is not None
                and hold.mean_mae_points is not None
                and hold.mean_mfe_points > hold.mean_mae_points
            ),
            actual=(hold.mean_mfe_points - hold.mean_mae_points)
            if hold.mean_mfe_points is not None and hold.mean_mae_points is not None
            else None,
            rule="mean MFE > mean MAE",
        ),
    ]
    return checks, "PASS" if all(check.passed for check in checks) else "FAIL"


def validate_h3_oos(
    rows: list[dict[str, object]],
    source: str,
    spec: FrozenH3Spec,
) -> OOSValidationReport:
    sessions = {str(row.get("session_date")) for row in rows if row.get("session_date")}
    eligible = [row for row in rows if str(row.get("session_date") or "") != str(row.get("expiry") or "")]
    excluded_expiry = len(rows) - len(eligible)
    thresholds = {"frozen_h3_spread_threshold": spec.frozen_threshold}
    events, skipped, overlaps = _build_events(eligible, _h3_hypothesis(spec), thresholds, spec.cooldown_minutes)

    per_session_groups: dict[str, list[EventResult]] = defaultdict(list)
    time_groups: dict[str, list[EventResult]] = defaultdict(list)
    for event in events:
        per_session_groups[event.session_date].append(event)
        time_groups[event.time_bucket].append(event)

    holds = {f"{hold}m": _hold_summary(events, hold) for hold in HOLD_MINUTES}
    primary = holds[f"{PRIMARY_HOLD_MINUTES}m"]
    event_sessions = len({event.session_date for event in events})
    checks, acceptance_status = _acceptance(primary, event_sessions)

    return OOSValidationReport(
        status="AVAILABLE" if rows else "UNAVAILABLE",
        source=source,
        spec_version=spec.spec_version,
        hypothesis_id=spec.hypothesis_id,
        frozen_threshold=spec.frozen_threshold,
        cooldown_minutes=spec.cooldown_minutes,
        row_count=len(rows),
        session_count=len(sessions),
        eligible_non_expiry_row_count=len(eligible),
        excluded_expiry_row_count=excluded_expiry,
        event_count=len(events),
        event_session_count=event_sessions,
        skipped_due_to_cooldown=skipped,
        max_horizon_overlap_count=overlaps,
        max_consecutive_losses_15m=_max_consecutive_losses(events),
        holds=holds,
        per_session=[_segment(label, per_session_groups[label]) for label in sorted(per_session_groups)],
        time_of_day=[_segment(label, time_groups[label]) for label in sorted(time_groups)],
        acceptance_checks=checks,
        acceptance_status=acceptance_status,
        events=events,
        methodology=[
            "Out-of-sample validation uses the frozen training threshold exactly; no OOS percentile recalculation.",
            "Expiry-day rows are excluded before signal generation.",
            "Signals enter on the next exact 1-minute observation and use the frozen cooldown from the spec.",
            "Acceptance checks are research gates, not guarantees of tradability or profitability.",
        ],
    )


def validate_h3_oos_csv(path: str | Path, spec: FrozenH3Spec) -> OOSValidationReport:
    return validate_h3_oos(load_hypothesis_evidence_csv(path), str(path), spec)


def write_h3_oos_json(report: OOSValidationReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
