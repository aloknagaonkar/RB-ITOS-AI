"""Pure, descriptive evidence views of pattern statistics; no strategy semantics."""

from .domain import (
    DominantOutcome, EvidenceMaturity, PatternEvidenceConfig, PatternEvidenceReport,
    PatternEvidenceRow, PatternStatisticsReport,
)


def build_pattern_evidence(report: PatternStatisticsReport, config: PatternEvidenceConfig = PatternEvidenceConfig(), evidence_compatibility_fingerprint: str | None = None) -> PatternEvidenceReport:
    compatibility = evidence_compatibility_fingerprint or report.calculation_fingerprint
    rows = []
    for group in report.groups:
        for outcome in group.outcomes:
            available = outcome.available_count
            dominant = (DominantOutcome.UNAVAILABLE if not available else
                        DominantOutcome.POSITIVE if outcome.positive_count > outcome.negative_count else
                        DominantOutcome.NEGATIVE if outcome.negative_count > outcome.positive_count else DominantOutcome.BALANCED)
            maturity = (EvidenceMaturity.INSUFFICIENT_DATA if available < config.minimum_available_samples else
                        EvidenceMaturity.OBSERVATIONAL if outcome.available_session_count < config.minimum_sessions_for_multi_session else
                        EvidenceMaturity.MULTI_SESSION)
            rows.append(PatternEvidenceRow(
                calculation_fingerprint=report.calculation_fingerprint, evidence_compatibility_fingerprint=compatibility, configuration_version=report.configuration_version,
                underlying=report.underlying, expiry=report.expiry, distinct_session_count=report.distinct_session_count,
                available_session_count=outcome.available_session_count,
                largest_session_available_count=outcome.largest_session_available_count,
                largest_session_share_percentage=outcome.largest_session_share_percentage,
                pattern_kind=group.kind, pattern_key=group.key, mode=group.mode, horizon_minutes=outcome.horizon_minutes,
                observation_count=outcome.observation_count, available_count=available, missing_count=outcome.missing_count,
                coverage_percentage=available / outcome.observation_count * 100 if outcome.observation_count else None,
                average_points=outcome.average_points, median_points=outcome.median_points, minimum_points=outcome.minimum_points,
                maximum_points=outcome.maximum_points, positive_count=outcome.positive_count, negative_count=outcome.negative_count,
                zero_count=outcome.zero_count, positive_percentage=outcome.positive_percentage,
                negative_percentage=outcome.negative_percentage, dominant_outcome=dominant,
                directional_imbalance_percentage=abs(outcome.positive_count - outcome.negative_count) / available * 100 if available else None,
                maturity=maturity,
            ))
    return PatternEvidenceReport(
        calculation_fingerprint=report.calculation_fingerprint, evidence_compatibility_fingerprint=compatibility,
        calculation_fingerprints=(report.calculation_fingerprint,), configuration_versions=(report.configuration_version,), expiries=(report.expiry,),
        configuration_version=report.configuration_version,
        underlying=report.underlying, expiry=report.expiry, observation_count=report.observation_count,
        distinct_session_count=report.distinct_session_count, rows=rows,
    )


def sort_evidence(rows, sort_by: str = "available_count"):
    key = {
        "available_count": lambda row: -(row.available_count),
        "absolute_average_points": lambda row: -(abs(row.average_points) if row.average_points is not None else -1),
        "directional_imbalance_percentage": lambda row: -(row.directional_imbalance_percentage if row.directional_imbalance_percentage is not None else -1),
    }.get(sort_by)
    if key is None: raise ValueError("Unsupported evidence sort")
    return sorted(rows, key=lambda row: (key(row), row.pattern_kind, row.pattern_key, row.mode or "", row.horizon_minutes))


def filter_evidence(rows, *, minimum_available_samples=None, horizon_minutes=None, pattern_kind=None, mode=None, maturity=None):
    return [row for row in rows if
            (minimum_available_samples is None or row.available_count >= minimum_available_samples) and
            (horizon_minutes is None or row.horizon_minutes == horizon_minutes) and
            (pattern_kind is None or row.pattern_kind == pattern_kind) and
            (mode is None or row.mode == mode) and (maturity is None or row.maturity.value == maturity)]
