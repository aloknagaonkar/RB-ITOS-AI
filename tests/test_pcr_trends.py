from datetime import datetime, timedelta

import pytest

from market_lab.domain import PCRHistoryRecord, PCRTrendClassification, PCRTrendConfig
from market_lab.trends import calculate_trend


AT = datetime.fromisoformat("2026-09-09T09:20:00+05:30")


def panel_record(identifier: int, received_at: datetime, pcr: float | None) -> PCRHistoryRecord:
    return PCRHistoryRecord(
        id=identifier,
        observation_id=identifier,
        configuration_version=1,
        record_kind="panel",
        mode="moving",
        fingerprint="moving-pcr-fingerprint",
        provider_timestamp=received_at,
        received_at=received_at,
        processed_at=received_at,
        underlying_spot=25_000,
        atm_reference=25_000,
        panel_pcr=pcr,
        data_status="AVAILABLE" if pcr is not None else "UNAVAILABLE",
    )


def test_trend_uses_the_latest_valid_backward_baseline() -> None:
    current = panel_record(3, AT + timedelta(minutes=5), 1.2)
    exact_target = panel_record(1, AT, 1.0)
    newer_than_target = panel_record(2, AT + timedelta(minutes=1), 1.1)

    result = calculate_trend(
        current,
        [exact_target, newer_than_target, current],
        horizon_seconds=300,
        config=PCRTrendConfig(flat_threshold=0.01, timestamp_tolerance_seconds=15),
    )

    assert result.baseline_pcr == 1.0
    assert result.absolute_pcr_change == pytest.approx(0.2)
    assert result.classification == PCRTrendClassification.RISING


def test_trend_remains_unavailable_without_a_valid_baseline() -> None:
    current = panel_record(2, AT + timedelta(minutes=5), 1.1)
    invalid = panel_record(1, AT + timedelta(minutes=1), 1.0)

    result = calculate_trend(current, [invalid, current], horizon_seconds=300, config=PCRTrendConfig())

    assert result.baseline_pcr is None
    assert result.classification == PCRTrendClassification.UNAVAILABLE


@pytest.mark.parametrize(
    "horizon_seconds,drift_seconds",
    [(900, 18), (1800, 35)],
)
def test_longer_horizons_accept_normal_backward_collection_drift(
    horizon_seconds: int, drift_seconds: int
) -> None:
    current = panel_record(2, AT + timedelta(minutes=40), 1.2)
    target = current.received_at - timedelta(seconds=horizon_seconds)
    baseline = panel_record(1, target - timedelta(seconds=drift_seconds), 1.0)

    result = calculate_trend(current, [baseline, current], horizon_seconds, PCRTrendConfig())

    assert result.status == "AVAILABLE"
    assert result.baseline_received_at == baseline.received_at
    assert result.actual_elapsed_seconds == horizon_seconds + drift_seconds


def test_exact_target_is_preferred_over_older_eligible_baseline() -> None:
    current = panel_record(3, AT + timedelta(minutes=15), 1.2)
    exact = panel_record(2, AT, 1.0)
    older = panel_record(1, AT - timedelta(seconds=45), 0.9)

    result = calculate_trend(current, [older, exact, current], 900, PCRTrendConfig())

    assert result.baseline_received_at == exact.received_at
    assert result.baseline_pcr == 1.0


def test_baseline_newer_than_target_is_rejected() -> None:
    current = panel_record(2, AT + timedelta(minutes=15), 1.2)
    newer = panel_record(1, AT + timedelta(seconds=1), 1.0)

    result = calculate_trend(current, [newer, current], 900, PCRTrendConfig())

    assert result.status == "UNAVAILABLE"
    assert result.baseline_received_at is None


def test_baseline_more_than_sixty_seconds_behind_target_is_rejected() -> None:
    current = panel_record(2, AT + timedelta(minutes=30), 1.2)
    too_old = panel_record(1, AT - timedelta(seconds=61), 1.0)

    result = calculate_trend(current, [too_old, current], 1800, PCRTrendConfig())

    assert result.status == "UNAVAILABLE"
    assert result.baseline_received_at is None


def test_baseline_from_previous_ist_session_date_is_rejected() -> None:
    current_at = datetime.fromisoformat("2026-09-10T00:00:30+05:30")
    current = panel_record(2, current_at, 1.2)
    previous_session = panel_record(1, current_at - timedelta(seconds=60), 1.0)

    result = calculate_trend(current, [previous_session, current], 60, PCRTrendConfig())

    assert result.status == "UNAVAILABLE"
    assert result.baseline_received_at is None
