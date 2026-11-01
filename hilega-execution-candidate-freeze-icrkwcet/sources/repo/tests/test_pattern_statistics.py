from datetime import date, datetime, timedelta

from market_lab.domain import PCRTrendClassification, SessionAnalysisObservation
from market_lab.pattern_statistics import calculate_pattern_statistics, pcr_change_bucket


AT = datetime.fromisoformat("2026-09-09T09:20:00+05:30")


def observation(index, trend, change, forward):
    return SessionAnalysisObservation(
        observation_id=index, received_at=AT + timedelta(minutes=index), underlying="NIFTY", expiry=date(2026, 9, 15),
        calculation_fingerprint="full-fingerprint", configuration_version=1, underlying_spot=25_000,
        moving_pcr=1.0, full_pcr=1.0, moving_change_5m=change, full_change_5m=change,
        moving_trend_5m=trend, full_trend_5m=trend, forward_change_5m=forward,
        forward_change_10m=forward, forward_change_15m=None, forward_change_30m=0,
    )


def test_statistics_groups_and_uses_available_outcome_denominator():
    items = [observation(1, PCRTrendClassification.RISING, .02, 10), observation(2, PCRTrendClassification.RISING, .02, -5), observation(3, PCRTrendClassification.UNAVAILABLE, None, None)]
    first = calculate_pattern_statistics(items)
    assert first == calculate_pattern_statistics(items)
    rising = next(group for group in first[0].groups if group.kind == "single_mode_trend" and group.mode == "moving" and group.key == "RISING")
    outcome = next(value for value in rising.outcomes if value.horizon_minutes == 5)
    assert (outcome.observation_count, outcome.available_count, outcome.missing_count) == (2, 2, 0)
    assert (outcome.positive_count, outcome.negative_count, outcome.zero_count) == (1, 1, 0)
    assert outcome.median_points == 2.5


def test_bucket_boundaries_do_not_overlap():
    assert [pcr_change_bucket(value, __import__('market_lab.domain', fromlist=['PCRChangeBucketConfig']).PCRChangeBucketConfig()) for value in (-.05, -.02, -.01, .01, .02, .05)] == ["[-0.05, -0.02)", "[-0.02, -0.01)", "[-0.01, 0.01]", "[-0.01, 0.01]", "(0.01, 0.02]", "(0.02, 0.05]"]


def test_session_contributions_count_only_available_individual_outcomes():
    first = observation(1, PCRTrendClassification.RISING, .02, 10)
    second = observation(2, PCRTrendClassification.RISING, .02, -5).model_copy(update={"received_at": AT + timedelta(days=1)})
    missing = observation(3, PCRTrendClassification.RISING, .02, None).model_copy(update={"received_at": AT + timedelta(days=1)})
    report = calculate_pattern_statistics([first, second, missing])[0]
    group = next(item for item in report.groups if item.kind == "single_mode_trend" and item.mode == "moving")
    value = next(item for item in group.outcomes if item.horizon_minutes == 5)
    assert (value.available_count, value.available_session_count, value.largest_session_available_count) == (2, 2, 1)
    assert value.largest_session_share_percentage == 50
    assert value.average_points == 2.5
