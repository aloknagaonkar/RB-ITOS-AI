from datetime import date

import pytest

from market_lab.domain import (
    EvidenceMaturity, ForwardOutcomeStatistics, PatternEvidenceConfig,
    PatternStatisticsGroup, PatternStatisticsReport,
)
from market_lab.pattern_evidence import build_pattern_evidence, filter_evidence, sort_evidence


def outcome(*, horizon=5, observations=10, available=8, positive=5, negative=2, zero=1, average=2.5, available_sessions=1):
    return ForwardOutcomeStatistics(
        horizon_minutes=horizon, observation_count=observations, available_count=available,
        missing_count=observations - available, average_points=average if available else None,
        median_points=average if available else None, minimum_points=-2 if available else None,
        maximum_points=6 if available else None, positive_count=positive, negative_count=negative,
        zero_count=zero, positive_percentage=positive / available * 100 if available else None,
        negative_percentage=negative / available * 100 if available else None,
        available_session_count=available_sessions if available else 0,
        largest_session_available_count=available if available_sessions == 1 else 0,
        largest_session_share_percentage=100 if available and available_sessions == 1 else None,
    )


def report(*, sessions=1, outcomes=None):
    return PatternStatisticsReport(
        calculation_fingerprint="fingerprint-a", configuration_version=4, underlying="NIFTY",
        expiry=date(2026, 9, 15), observation_count=49, distinct_session_count=sessions,
        groups=[PatternStatisticsGroup(kind="single_mode_trend", key="RISING", mode="moving", outcomes=outcomes or [outcome()])],
    )


def row(**kwargs):
    return build_pattern_evidence(report(**kwargs)).rows[0]


def test_evidence_is_deterministic_and_preserves_report_metadata():
    source = report()
    assert build_pattern_evidence(source) == build_pattern_evidence(source)
    value = row()
    assert (value.calculation_fingerprint, value.configuration_version, value.underlying, value.expiry, value.distinct_session_count) == ("fingerprint-a", 4, "NIFTY", date(2026, 9, 15), 1)
    assert value.pattern_kind == "single_mode_trend" and value.pattern_key == "RISING" and value.mode == "moving"


def test_coverage_imbalance_and_positive_dominance():
    value = row()
    assert value.coverage_percentage == 80
    assert value.directional_imbalance_percentage == 37.5
    assert value.dominant_outcome == "POSITIVE"


@pytest.mark.parametrize(("positive", "negative", "expected"), [(2, 5, "NEGATIVE"), (4, 4, "BALANCED")])
def test_non_positive_dominant_outcomes(positive, negative, expected):
    value = row(outcomes=[outcome(positive=positive, negative=negative, zero=0)])
    assert value.dominant_outcome == expected


def test_unavailable_outcome_and_zero_observation_coverage_remain_null():
    value = row(outcomes=[outcome(observations=0, available=0, positive=0, negative=0, zero=0, average=None)])
    assert value.coverage_percentage is None
    assert value.directional_imbalance_percentage is None
    assert value.dominant_outcome == "UNAVAILABLE"
    assert value.average_points is None and value.median_points is None


def test_maturity_boundaries_and_low_coverage_30m_are_visible():
    config = PatternEvidenceConfig(minimum_available_samples=10, minimum_sessions_for_multi_session=3)
    insufficient = build_pattern_evidence(report(sessions=3, outcomes=[outcome(horizon=30, available=9, positive=9, negative=0, zero=0)]), config).rows[0]
    observational = build_pattern_evidence(report(sessions=3, outcomes=[outcome(available=10, available_sessions=2)]), config).rows[0]
    multi = build_pattern_evidence(report(sessions=3, outcomes=[outcome(available=10, available_sessions=3)]), config).rows[0]
    assert insufficient.horizon_minutes == 30 and insufficient.maturity == EvidenceMaturity.INSUFFICIENT_DATA
    assert observational.maturity == EvidenceMaturity.OBSERVATIONAL
    assert multi.maturity == EvidenceMaturity.MULTI_SESSION


def test_maturity_uses_available_sessions_and_preserves_single_config_metadata():
    config = PatternEvidenceConfig(minimum_available_samples=10, minimum_sessions_for_multi_session=3)
    source = report(sessions=5, outcomes=[outcome(available=10)])
    one = build_pattern_evidence(source, config).rows[0]
    two = build_pattern_evidence(source, config).rows[0].model_copy(update={"available_session_count": 2})
    assert one.maturity == EvidenceMaturity.OBSERVATIONAL
    assert two.available_session_count == 2
    evidence = build_pattern_evidence(source, config, "semantic-fingerprint")
    assert evidence.evidence_compatibility_fingerprint == "semantic-fingerprint"
    assert evidence.calculation_fingerprints == ("fingerprint-a",)
    assert evidence.configuration_versions == (4,) and evidence.expiries == (date(2026, 9, 15),)


def test_sorting_and_filtering_are_deterministic():
    values = build_pattern_evidence(report(outcomes=[outcome(horizon=5, available=4, average=-8, positive=4, negative=0, zero=0), outcome(horizon=10, available=9, average=2, positive=5, negative=4, zero=0), outcome(horizon=30, available=9, average=2, positive=5, negative=4, zero=0)])).rows
    assert [item.horizon_minutes for item in sort_evidence(values, "available_count")] == [10, 30, 5]
    assert [item.horizon_minutes for item in sort_evidence(values, "absolute_average_points")] == [5, 10, 30]
    assert [item.horizon_minutes for item in sort_evidence(values, "directional_imbalance_percentage")] == [5, 10, 30]
    assert [item.horizon_minutes for item in filter_evidence(values, minimum_available_samples=9)] == [5 + 5, 30]
    assert [item.horizon_minutes for item in filter_evidence(values, horizon_minutes=30, pattern_kind="single_mode_trend", mode="moving", maturity="INSUFFICIENT_DATA")] == [30]


def test_empty_statistics_report_returns_no_rows():
    empty = PatternStatisticsReport(calculation_fingerprint="none", configuration_version=1, underlying="NIFTY", expiry=date(2026, 9, 15), observation_count=0, distinct_session_count=0, groups=[])
    assert build_pattern_evidence(empty).rows == []
