from red_bar_lab.services.nifty_futures_positioning import (
    INSUFFICIENT_DATA,
    LONG_BUILDUP,
    LONG_UNWINDING,
    NEUTRAL,
    SHORT_BUILDUP,
    SHORT_COVERING,
    classify_nifty_futures_positioning,
)


def _classify(latest_close, previous_close, latest_oi, previous_oi):
    return classify_nifty_futures_positioning(
        latest_close=latest_close,
        previous_close=previous_close,
        latest_oi=latest_oi,
        previous_oi=previous_oi,
        latest_volume=150,
        prior_volumes=[100, 200],
    )


def test_classifies_long_buildup():
    result = _classify(101, 100, 1100, 1000)

    assert result.status == "READY"
    assert result.state == LONG_BUILDUP
    assert result.price_change == 1.0
    assert result.price_change_pct == 1.0
    assert result.oi_change == 100.0
    assert result.oi_change_pct == 10.0
    assert result.relative_volume == 1.0
    assert result.baseline_volume == 150.0
    assert result.baseline_samples == 2


def test_classifies_short_buildup():
    assert _classify(99, 100, 1100, 1000).state == SHORT_BUILDUP


def test_classifies_short_covering():
    assert _classify(101, 100, 900, 1000).state == SHORT_COVERING


def test_classifies_long_unwinding():
    assert _classify(99, 100, 900, 1000).state == LONG_UNWINDING


def test_zero_or_threshold_bound_changes_are_neutral():
    unchanged = _classify(100, 100, 1000, 1000)
    thresholded = classify_nifty_futures_positioning(
        latest_close=100.05,
        previous_close=100,
        latest_oi=1005,
        previous_oi=1000,
        latest_volume=100,
        prior_volumes=[100],
        price_change_threshold_pct=0.1,
        oi_change_threshold_pct=1.0,
    )

    assert unchanged.state == NEUTRAL
    assert thresholded.state == NEUTRAL


def test_missing_close_or_oi_is_insufficient_data():
    result = classify_nifty_futures_positioning(
        latest_close=101,
        previous_close=None,
        latest_oi=1100,
        previous_oi=1000,
        latest_volume=100,
        prior_volumes=[80, 120],
    )

    assert result.status == INSUFFICIENT_DATA
    assert result.state == NEUTRAL
    assert result.relative_volume is None


def test_relative_volume_ignores_missing_zero_negative_and_invalid_baselines():
    result = classify_nifty_futures_positioning(
        latest_close=101,
        previous_close=100,
        latest_oi=1100,
        previous_oi=1000,
        latest_volume=300,
        prior_volumes=[None, 0, -1, "bad", 100, 200],
    )

    assert result.baseline_volume == 150.0
    assert result.baseline_samples == 2
    assert result.relative_volume == 2.0


def test_zero_previous_close_or_oi_does_not_invent_percentage_direction():
    result = classify_nifty_futures_positioning(
        latest_close=101,
        previous_close=0,
        latest_oi=1100,
        previous_oi=0,
        latest_volume=100,
        prior_volumes=[],
    )

    assert result.status == "READY"
    assert result.price_change_pct is None
    assert result.oi_change_pct is None
    assert result.state == NEUTRAL
    assert result.relative_volume is None
