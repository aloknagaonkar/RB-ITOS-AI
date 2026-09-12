"""Combined robustness validation for frozen H3 across two OOS blocks.

This module never recomputes the H3 threshold.  It loads the frozen training
specification, validates each OOS block independently, then validates the
concatenated OOS rows with the same threshold/cooldown/regime rules.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .historical_hypothesis_backtest import load_hypothesis_evidence_csv
from .historical_oos import (
    AcceptanceCheck,
    FrozenH3Spec,
    OOSValidationReport,
    validate_h3_oos,
)


class CombinedOOSModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CombinedAcceptanceCheck(CombinedOOSModel):
    name: str
    passed: bool
    actual: float | int | str | None
    rule: str


class CombinedH3OOSReport(CombinedOOSModel):
    status: str
    hypothesis_id: str
    spec_version: str
    frozen_threshold: float
    block_a_source: str
    block_b_source: str
    block_a: OOSValidationReport
    block_b: OOSValidationReport
    combined: OOSValidationReport
    robustness_checks: list[CombinedAcceptanceCheck] = Field(default_factory=list)
    robustness_status: str
    methodology: list[str] = Field(default_factory=list)


def _primary(report: OOSValidationReport):
    return report.holds.get("15m")


def _combined_checks(
    block_a: OOSValidationReport,
    block_b: OOSValidationReport,
    combined: OOSValidationReport,
) -> tuple[list[CombinedAcceptanceCheck], str]:
    a = _primary(block_a)
    b = _primary(block_b)
    c = _primary(combined)

    checks = [
        CombinedAcceptanceCheck(
            name="both_blocks_positive_mean_15m",
            passed=(
                a is not None and b is not None
                and a.mean_directional_points is not None
                and b.mean_directional_points is not None
                and a.mean_directional_points > 0.0
                and b.mean_directional_points > 0.0
            ),
            actual=(
                f"A={a.mean_directional_points:.6f}, B={b.mean_directional_points:.6f}"
                if a is not None and b is not None
                and a.mean_directional_points is not None
                and b.mean_directional_points is not None
                else None
            ),
            rule="both OOS blocks have positive 15m mean directional points",
        ),
        CombinedAcceptanceCheck(
            name="combined_win_rate_15m",
            passed=c is not None and c.win_rate_pct is not None and c.win_rate_pct >= 52.0,
            actual=c.win_rate_pct if c else None,
            rule=">= 52%",
        ),
        CombinedAcceptanceCheck(
            name="combined_median_15m",
            passed=c is not None and c.median_directional_points is not None and c.median_directional_points > 0.0,
            actual=c.median_directional_points if c else None,
            rule="> 0",
        ),
        CombinedAcceptanceCheck(
            name="combined_mean_15m",
            passed=c is not None and c.mean_directional_points is not None and c.mean_directional_points > 0.0,
            actual=c.mean_directional_points if c else None,
            rule="> 0",
        ),
        CombinedAcceptanceCheck(
            name="combined_event_session_coverage",
            passed=combined.event_session_count >= 12,
            actual=combined.event_session_count,
            rule=">= 12 sessions",
        ),
        CombinedAcceptanceCheck(
            name="combined_mfe_vs_mae_15m",
            passed=(
                c is not None
                and c.mean_mfe_points is not None
                and c.mean_mae_points is not None
                and c.mean_mfe_points > c.mean_mae_points
            ),
            actual=(
                c.mean_mfe_points - c.mean_mae_points
                if c is not None and c.mean_mfe_points is not None and c.mean_mae_points is not None
                else None
            ),
            rule="mean MFE > mean MAE",
        ),
    ]
    return checks, "PASS" if all(check.passed for check in checks) else "FAIL"


def validate_h3_combined_oos(
    block_a_rows: list[dict[str, object]],
    block_b_rows: list[dict[str, object]],
    block_a_source: str,
    block_b_source: str,
    spec: FrozenH3Spec,
) -> CombinedH3OOSReport:
    block_a = validate_h3_oos(block_a_rows, block_a_source, spec)
    block_b = validate_h3_oos(block_b_rows, block_b_source, spec)
    combined_rows = list(block_a_rows) + list(block_b_rows)
    combined = validate_h3_oos(
        combined_rows,
        f"{block_a_source} + {block_b_source}",
        spec,
    )
    checks, robustness_status = _combined_checks(block_a, block_b, combined)
    return CombinedH3OOSReport(
        status="AVAILABLE" if combined_rows else "UNAVAILABLE",
        hypothesis_id=spec.hypothesis_id,
        spec_version=spec.spec_version,
        frozen_threshold=spec.frozen_threshold,
        block_a_source=block_a_source,
        block_b_source=block_b_source,
        block_a=block_a,
        block_b=block_b,
        combined=combined,
        robustness_checks=checks,
        robustness_status=robustness_status,
        methodology=[
            "The frozen H3 training threshold is reused unchanged in OOS-A, OOS-B, and the combined OOS report.",
            "No percentile or signal threshold is recalculated from either OOS block.",
            "Expiry-day rows are excluded independently in every validation block.",
            "Combined robustness gates are research gates only and do not imply option profitability or execution readiness.",
        ],
    )


def validate_h3_combined_oos_csv(
    block_a_path: str | Path,
    block_b_path: str | Path,
    spec: FrozenH3Spec,
) -> CombinedH3OOSReport:
    a = load_hypothesis_evidence_csv(block_a_path)
    b = load_hypothesis_evidence_csv(block_b_path)
    return validate_h3_combined_oos(a, b, str(block_a_path), str(block_b_path), spec)


def write_h3_combined_oos_json(report: CombinedH3OOSReport, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
