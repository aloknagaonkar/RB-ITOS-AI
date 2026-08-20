from red_bar_lab.services.nifty_futures_shadow_validation import (
    validate_nifty_futures_shadow_session,
)
from red_bar_lab.services.nifty_futures_threshold_replay import (
    replay_nifty_futures_strength_thresholds,
)


def test_shadow_validation_uses_market_hours_only():
    rows = [
        {
            "observed_at": "2026-08-20T10:00:00+05:30",
            "readiness_status": "READY",
            "positioning_state": "LONG_BUILDUP",
            "strength": "STRONG",
        },
        {
            "observed_at": "2026-08-20T10:01:00+05:30",
            "readiness_status": "READY",
            "positioning_state": "NEUTRAL",
            "strength": "WEAK",
        },
        {
            "observed_at": "2026-08-20T21:00:00+05:30",
            "readiness_status": "READY",
            "positioning_state": "SHORT_BUILDUP",
            "strength": "STRONG",
        },
    ]

    result = validate_nifty_futures_shadow_session(rows)

    assert result.status == "READY"
    assert result.market_hours_observations == 2
    assert result.ready_observations == 2
    assert result.directional_observations == 1
    assert result.strong_or_moderate_observations == 1
    assert result.execution_impact == "NONE"


def test_shadow_validation_reports_insufficient_without_market_rows():
    result = validate_nifty_futures_shadow_session(
        [{"observed_at": "2026-08-20T21:00:00+05:30"}]
    )

    assert result.status == "INSUFFICIENT_DATA"
    assert result.market_hours_observations == 0


def test_threshold_replay_regrades_persisted_observations():
    rows = [
        {
            "positioning_status": "READY",
            "positioning_state": "LONG_BUILDUP",
            "price_change_pct": 0.05,
            "oi_change_pct": 0.06,
            "relative_volume": 1.3,
        },
        {
            "positioning_status": "READY",
            "positioning_state": "SHORT_BUILDUP",
            "price_change_pct": -0.05,
            "oi_change_pct": 0.06,
            "relative_volume": 0.9,
        },
        {
            "positioning_status": "READY",
            "positioning_state": "LONG_UNWINDING",
            "price_change_pct": -0.01,
            "oi_change_pct": -0.01,
            "relative_volume": 1.5,
        },
    ]

    result = replay_nifty_futures_strength_thresholds(rows)

    assert result.status == "READY"
    assert result.samples == 3
    assert result.directional_samples == 3
    assert result.strong == 1
    assert result.moderate == 1
    assert result.weak == 1
    assert result.execution_impact == "NONE"


def test_threshold_replay_empty_input_is_insufficient():
    result = replay_nifty_futures_strength_thresholds([])

    assert result.status == "INSUFFICIENT_DATA"
    assert result.samples == 0
