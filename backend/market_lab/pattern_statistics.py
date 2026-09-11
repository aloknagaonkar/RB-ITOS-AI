"""Pure descriptive statistics over session-analysis facts; never trading interpretation."""

from statistics import median
from collections import defaultdict

from .domain import (
    ForwardOutcomeStatistics, IST, PCRChangeBucketConfig, PCRTrendClassification,
    PatternStatisticsGroup, PatternStatisticsReport, SessionAnalysisObservation,
)

HORIZONS = (5, 10, 15, 30)
MODES = ("fixed", "moving", "full")


def pcr_change_bucket(value: float | None, config: PCRChangeBucketConfig) -> str | None:
    if value is None:
        return None
    if value < -config.large: return f"< {-config.large:g}"
    if value < -config.medium: return f"[{ -config.large:g}, {-config.medium:g})"
    if value < -config.small: return f"[{ -config.medium:g}, {-config.small:g})"
    if value <= config.small: return f"[{ -config.small:g}, {config.small:g}]"
    if value <= config.medium: return f"({config.small:g}, {config.medium:g}]"
    if value <= config.large: return f"({config.medium:g}, {config.large:g}]"
    return f"> {config.large:g}"


def _outcomes(observations):
    output = []
    for horizon in HORIZONS:
        values = [getattr(item, f"forward_change_{horizon}m") for item in observations]
        available = [value for value in values if value is not None]
        session_counts = defaultdict(int)
        for item, value in zip(observations, values):
            if value is not None:
                session_counts[item.received_at.astimezone(IST).date()] += 1
        positive = sum(value > 0 for value in available)
        negative = sum(value < 0 for value in available)
        output.append(ForwardOutcomeStatistics(
            horizon_minutes=horizon, observation_count=len(values), available_count=len(available),
            missing_count=len(values) - len(available), average_points=sum(available) / len(available) if available else None,
            median_points=median(available) if available else None, minimum_points=min(available) if available else None,
            maximum_points=max(available) if available else None, positive_count=positive, negative_count=negative,
            zero_count=len(available) - positive - negative,
            positive_percentage=positive / len(available) * 100 if available else None,
            negative_percentage=negative / len(available) * 100 if available else None,
            available_session_count=len(session_counts),
            largest_session_available_count=max(session_counts.values(), default=0),
            largest_session_share_percentage=(max(session_counts.values()) / len(available) * 100) if available else None,
        ))
    return output


def calculate_pattern_statistics(observations, config: PCRChangeBucketConfig = PCRChangeBucketConfig()):
    by_fingerprint = defaultdict(list)
    for observation in observations:
        by_fingerprint[observation.calculation_fingerprint].append(observation)
    reports = []
    for fingerprint, items in sorted(by_fingerprint.items()):
        groups = []
        for mode in MODES:
            classified = defaultdict(list); bucketed = defaultdict(list)
            for item in items:
                classification = getattr(item, f"{mode}_trend_5m")
                if classification != PCRTrendClassification.UNAVAILABLE:
                    classified[classification.value].append(item)
                bucket = pcr_change_bucket(getattr(item, f"{mode}_change_5m"), config)
                if bucket is not None: bucketed[bucket].append(item)
            for key, members in sorted(classified.items()):
                groups.append(PatternStatisticsGroup(kind="single_mode_trend", key=key, mode=mode, outcomes=_outcomes(members)))
            for key, members in sorted(bucketed.items()):
                groups.append(PatternStatisticsGroup(kind="pcr_change_bucket", key=key, mode=mode, outcomes=_outcomes(members)))
        combined = defaultdict(list)
        for item in items:
            moving, full = item.moving_trend_5m, item.full_trend_5m
            if moving != PCRTrendClassification.UNAVAILABLE and full != PCRTrendClassification.UNAVAILABLE:
                combined[f"{moving.value} / {full.value}"].append(item)
        for key, members in sorted(combined.items()):
            groups.append(PatternStatisticsGroup(kind="moving_full_trend", key=key, outcomes=_outcomes(members)))
        first = items[0]
        reports.append(PatternStatisticsReport(
            calculation_fingerprint=fingerprint, configuration_version=first.configuration_version,
            underlying=first.underlying, expiry=first.expiry, observation_count=len(items),
            distinct_session_count=len({item.received_at.astimezone(IST).date() for item in items}), groups=groups,
        ))
    return reports
